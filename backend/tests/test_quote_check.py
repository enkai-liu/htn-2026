"""Layer-1 verification: the deterministic quote-in-source check. No network: fetches go through a mock transport."""
from __future__ import annotations

import httpx

from app.schemas import Evidence, Verification
from app.signals import quote_check as qc
from app.signals.quote_check import QuoteCheck, blocked_reason, check_evidence, check_many, normalize, quote_in_text, to_verification, verify_event

SOURCE = (
    "## What it does\n\n"
    "**DevSpot** validates the uniqueness of your hackathon idea against *every* project on Devpost — before you "
    "write a line of code.  It scrapes the gallery, embeds each description with GPT-4, and returns a “uniqueness "
    "score” together with the five closest projects.\n\n"
    "## Challenges we ran into\n\nCompute was the bottleneck: embedding 10,000 projects took most of the weekend."
)


def ev(quote: str, url: str = "https://devpost.com/software/devspot") -> Evidence:
    return Evidence(evid="e1", eid="ent1", rid="devpost:devspot", quote=quote, url=url,
                    citation='[1] DevSpot team. "DevSpot." Devpost. 2024. https://devpost.com/software/devspot')


class NoNetwork(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"network call attempted: {request.url}")


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


# ---------------------------------------------------------------------------- normalisation
def test_normalize_strips_markup_and_unicode_punctuation():
    assert normalize("**DevSpot** — it’s  a <b>“uniqueness&nbsp;score”</b>\n[docs](https://x.y/z) `code`") == \
        "devspot its a uniqueness score docs code"
    assert normalize("snake_case and C# and  TABS\t\tand\nnewlines") == "snakecase and c and tabs and newlines"
    assert normalize("") == "" and normalize(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- quote_in_text
def test_verbatim_despite_case_whitespace_markdown_and_curly_quotes():
    m = quote_in_text('devspot validates the uniqueness of your hackathon idea against every project on Devpost - before you write', SOURCE)
    assert m and m.match and m.method == "exact" and m.score == 1.0
    assert m.detail == "quote found verbatim in the source"
    assert quote_in_text('returns a "uniqueness score" together with the five closest projects', SOURCE).method == "exact"
    assert quote_in_text("embedding 10,000 projects took most of the weekend.", SOURCE).method == "exact"


def test_fuzzy_tolerates_one_changed_word_in_a_long_quote():
    # 12 words, one substituted ("all" for "every"): 11/12 = 0.917 >= 0.9
    m = quote_in_text("validates the uniqueness of your hackathon idea against all project on Devpost before", SOURCE)
    assert m.match and m.method == "fuzzy" and 0.9 <= m.score < 1.0
    assert "minor differences" in m.detail
    # an inserted word is tolerated too
    assert quote_in_text("It scrapes the entire gallery, embeds each description with GPT-4, and returns a uniqueness score", SOURCE).match


def test_short_quotes_must_be_exact():
    assert quote_in_text("embeds each description with GPT-4", SOURCE).method == "exact"
    assert not quote_in_text("embeds every description with GPT-4", SOURCE).match  # 4/5 words = 0.8


def test_paraphrase_and_fabrication_do_not_match():
    assert not quote_in_text("DevSpot uses a vector database to cluster ideas and rank them by novelty for judges", SOURCE)
    m = quote_in_text("IdeaForge AI closes a seed round for its originality checker platform", SOURCE)
    assert not m.match and m.method == "none" and m.detail.startswith("quote not found in the source")


def test_same_words_in_a_different_order_do_not_match():
    assert not quote_in_text("Devpost on project every against idea hackathon your of uniqueness the validates", SOURCE).match


def test_words_scattered_across_the_document_do_not_match():
    scattered = "DevSpot scrapes compute bottleneck weekend gallery uniqueness projects embedding Devpost code score"
    assert not quote_in_text(scattered, SOURCE).match


def test_too_short_quotes_are_refused():
    for q in ("DevSpot", "on Devpost", "the five closest", "", "   "):
        m = quote_in_text(q, SOURCE)
        assert not m.match and "too short" in m.detail
    assert quote_in_text("the five closest projects", SOURCE).match  # 4 words is the minimum


def test_elided_quotes_are_checked_piece_by_piece():
    ok = quote_in_text("validates the uniqueness of your hackathon idea ... returns a uniqueness score together with", SOURCE)
    assert ok.match and ok.method == "exact" and "elided" in ok.detail
    assert quote_in_text("validates the uniqueness of your hackathon idea [...] embedding 10,000 projects took most", SOURCE).match
    bad = quote_in_text("validates the uniqueness of your hackathon idea ... and won the grand prize at HackPSU", SOURCE)
    assert not bad.match


def test_empty_source():
    m = quote_in_text("validates the uniqueness of your idea", "")
    assert not m.match and m.detail == "source text is empty"


def test_long_documents_stay_fast():
    import time

    filler = " ".join(f"token{i % 977} filler words about hackathons and projects" for i in range(12_000))
    text = filler + " " + SOURCE + " " + filler
    start = time.perf_counter()
    assert quote_in_text("validates the uniqueness of your hackathon idea against all project on Devpost before", text).match
    assert not quote_in_text("a quote that simply is not anywhere inside this very long document at all", text).match
    assert time.perf_counter() - start < 5.0


# ---------------------------------------------------------------------------- check_evidence
async def test_record_text_is_used_and_nothing_is_fetched():
    async with httpx.AsyncClient(transport=NoNetwork()) as client:
        res = await check_evidence(ev("validates the uniqueness of your hackathon idea"), record_text=SOURCE, client=client)
        assert isinstance(res, QuoteCheck) and res.match and res.source == "record" and res.method == "exact"
        assert res.detail == "quote found verbatim in the indexed record"
        miss = await check_evidence(ev("this project won the grand prize at the hackathon"), record_text=SOURCE, client=client)
        assert not miss.match and miss.source == "record" and miss.detail.startswith("quote not found in the indexed record")


async def test_fetches_the_url_and_reads_only_visible_text():
    seen = []
    page = ("<html><head><title>DevSpot | Devpost</title><style>.x{color:red}</style>"
            "<script>var hidden = 'secret phrase only inside a script tag';</script></head>"
            "<body><nav>Log in</nav><div id='app-details-left'><p>DevSpot validates the uniqueness of your "
            "<em>hackathon idea</em> against every project on&nbsp;Devpost.</p></div></body></html>")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, html=page)

    async with client_for(handler) as client:
        res = await check_evidence(ev("validates the uniqueness of your hackathon idea against every project on Devpost"), client=client)
        assert res.match and res.source == "fetched" and res.http_status == 200
        assert res.detail == "quote found verbatim in the fetched page"
        hidden = await check_evidence(ev("secret phrase only inside a script tag"), client=client)
        assert not hidden.match, "script contents are not visible text"
    ua = seen[0].headers["user-agent"]
    assert ua.startswith("Mozilla/5.0 (") and "Chrome/" in ua and ua != "Mozilla/5.0"


async def test_fetch_fallback_when_the_record_lacks_the_quote():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<p>The full page says: compute was the real bottleneck for our team.</p>")

    async with client_for(handler) as client:
        e = ev("compute was the real bottleneck for our team")
        assert not (await check_evidence(e, record_text="a truncated pitch without it, long enough to be checked", client=client)).match
        res = await check_evidence(e, record_text="a truncated pitch without it, long enough to be checked", client=client, fetch_fallback=True)
        assert res.match and res.source == "fetched"


async def test_missing_page_reads_as_a_fabricated_source():
    async with client_for(lambda req: httpx.Response(404, html="<h1>Not found</h1>")) as client:
        res = await check_evidence(ev("IdeaForge AI closes seed round for its originality checker", "https://example.invalid/ideaforge"), client=client)
    assert not res.match and res.detail == "cited page does not exist" and res.http_status == 404 and res.source == "none"


async def test_server_errors_timeouts_and_binary_content_never_raise():
    async with client_for(lambda req: httpx.Response(503)) as client:
        res = await check_evidence(ev("validates the uniqueness of your hackathon idea"), client=client)
        assert not res.match and "HTTP 503" in res.detail

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with client_for(boom) as client:
        res = await check_evidence(ev("validates the uniqueness of your hackathon idea"), client=client)
        assert not res.match and "timed out" in res.detail

    async with client_for(lambda req: httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})) as client:
        res = await check_evidence(ev("validates the uniqueness of your hackathon idea"), client=client)
        assert not res.match and "unsupported content type application/pdf" in res.detail


async def test_devpost_search_is_never_fetched():
    async with httpx.AsyncClient(transport=NoNetwork()) as client:
        for url in ("https://devpost.com/software/search?query=originality", "http://devpost.com/software/search",
                    "https://www.devpost.com/software/search/?page=2"):
            res = await check_evidence(ev("validates the uniqueness of your hackathon idea", url), client=client)
            assert not res.match and "Devpost search pages are never fetched" in res.detail
    assert blocked_reason("https://devpost.com/software/devspot") is None
    assert blocked_reason("https://devpost.com/software/searchlight") is None, "a project that merely starts with 'search' is fine"


async def test_redirect_into_the_search_page_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/software/old":
            return httpx.Response(302, headers={"location": "https://devpost.com/software/search?query=old"})
        raise AssertionError("the blocked page body must not be used")  # pragma: no cover

    async with client_for(lambda req: handler(req) if req.url.path == "/software/old" else httpx.Response(200, html="<p>x</p>")) as client:
        res = await check_evidence(ev("validates the uniqueness of your hackathon idea", "https://devpost.com/software/old"), client=client)
    assert not res.match and "blocked" in res.detail


def test_other_blocked_urls():
    assert blocked_reason("ftp://example.org/file") == "not an http(s) URL"
    assert blocked_reason("javascript:alert(1)") == "not an http(s) URL"
    assert blocked_reason("http://localhost:8000/admin") == "private host"
    assert blocked_reason("http://127.0.0.1/") == "private address"
    assert blocked_reason("http://10.0.0.8/x") == "private address"
    assert blocked_reason("https://github.com/Ayon-Bhowmick/HackathonProjectSearch") is None


async def test_body_size_is_capped(monkeypatch):
    monkeypatch.setattr(qc, "MAX_FETCH_BYTES", 2_000)
    page = "<p>" + "padding words " * 400 + "the quote sits far beyond the size cap of this page</p>"
    async with client_for(lambda req: httpx.Response(200, html=page)) as client:
        res = await check_evidence(ev("the quote sits far beyond the size cap"), client=client)
    assert not res.match and res.source == "fetched"


async def test_evidence_without_a_quote():
    res = await check_evidence(ev("   "))
    assert not res.match and res.detail == "evidence carries no quote"


async def test_check_many_uses_record_texts_by_rid():
    e1 = ev("validates the uniqueness of your hackathon idea")
    e2 = Evidence(evid="e2", eid="ent2", rid="web:fake", quote="a quote nobody ever wrote on any page at all",
                  url="https://devpost.com/software/search?query=x", citation="[2] x")
    out = await check_many([e1, e2], record_texts={"devpost:devspot": SOURCE})
    assert out["e1"].match and out["e1"].source == "record"
    assert not out["e2"].match and "never fetched" in out["e2"].detail


# ---------------------------------------------------------------------------- glue
def test_to_verification_keeps_layer_two():
    existing = Verification(gptzero_status="exist", stance="support", justification="found")
    v = to_verification(QuoteCheck(True, "quote found verbatim in the indexed record", "record", 1.0, "exact"), existing)
    assert v == Verification(local_quote_match=True, gptzero_status="exist", stance="support", justification="found")
    assert to_verification(QuoteCheck(False, "cited page does not exist")).local_quote_match is False


def test_verify_event_matches_the_events_contract():
    hit = verify_event("c1", QuoteCheck(True, "quote found verbatim in the fetched page", "fetched", 1.0, "exact", 200))
    assert hit == {"cid": "c1", "layer": "quote", "status": "match", "detail": "quote found verbatim in the fetched page"}
    miss = verify_event("c9", QuoteCheck(False, "cited page does not exist"))
    assert miss == {"cid": "c9", "layer": "quote", "status": "no_match", "detail": "cited page does not exist"}
