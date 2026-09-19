"""ingest/schema_map.py + ingest/common.py + ingest/devpost_page.py, offline, on real fixture rows."""
import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingest import common, schema_map as sm  # noqa: E402
from ingest.devpost_page import parse_gallery_page, parse_project_page  # noqa: E402

from app.schemas.records import GPTZeroScan, SourceRecord  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ALVANLII = {r["title"]: r for r in json.loads((FIXTURES / "alvanlii_rows.json").read_text())["rows"]}
TWANGODEV = {r["title"]: r for r in json.loads((FIXTURES / "twangodev_rows.json").read_text())["rows"]}
YC = {r["name"]: r for r in json.loads((FIXTURES / "yc_rows.json").read_text())["rows"]}
HACKATHONS = sm.load_hackathons(FIXTURES / "hackathons_sample.json")
MAPPING = json.loads((REPO_ROOT / "elastic" / "mappings" / "prior-art-v1.json").read_text())["mappings"]["properties"]


# ---------------------------------------------------------------- value helpers
@pytest.mark.parametrize("text,expected", [
    ("Oct 01 - Dec 04, 2024", (2024, dt.date(2024, 12, 4))),
    ("Mar 16 - 17, 2024", (2024, dt.date(2024, 3, 17))),
    ("Mar 10, 2018", (2018, dt.date(2018, 3, 10))),
    ("Dec 28, 2019 - Jan 05, 2020", (2020, dt.date(2020, 1, 5))),
    ("TBD", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_parse_submission_dates(text, expected):
    assert sm.parse_submission_dates(text) == expected


@pytest.mark.parametrize("value,expected", [
    ("['c#', 'unity']", ["c#", "unity"]),
    ("[]", []),
    ('["Best Use of AI", "1st Place"]', ["Best Use of AI", "1st Place"]),
    (["a", None, " b "], ["a", "b"]),
    (None, []),
    (float("nan"), []),
    ("python, react", ["python", "react"]),
])
def test_parse_listish(value, expected):
    assert sm.parse_listish(value) == expected


def test_slug_and_links():
    assert sm.slug_from_url("https://devpost.com/software/Crazy-Cows-Game/?ref=x") == "crazy-cows-game"
    links = sm.normalise_links([
        "github.com",  # bare generic host: says nothing about which project this is
        "https://github.com/a/b.git", "https://github.com/a/b",  # same repo twice
        "https://100x.bot?utm_source=inbound&utm_medium=bookface",  # tracking params break URL blocking
        "cisco-meraki-278014.ue.r.appspot.com",
    ])
    assert links == ["https://github.com/a/b.git", "https://100x.bot", "https://cisco-meraki-278014.ue.r.appspot.com"]


# ---------------------------------------------------------------- alvanlii
def test_alvanlii_year_join_winner_and_provenance():
    rec = sm.from_alvanlii(ALVANLII["DevSpot"], HACKATHONS)
    assert rec.rid == "devpost:devspot" and rec.source == "devpost"
    assert rec.url == "https://devpost.com/software/devspot"
    assert (rec.year, rec.date, rec.date_precision) == (2024, dt.date(2024, 3, 17), "inferred")
    assert rec.traction["is_winner"] is True and rec.traction["prize"] == ["Entrepreneurship Award"]
    assert rec.traction["hackathon"] == "HackPSU Spring 2024" and rec.traction["hackathon_id"] == "20679"
    assert "flask" in rec.tech and "react" in rec.tech  # the `tags` column is really "Built With"
    assert rec.tags == ["Beginner Friendly", "Education", "Open Ended"]  # hackathon themes
    fp = rec.field_provenance
    assert fp["title"] == "source" and fp["tech"] == "normalized" and fp["year"] == "normalized"
    assert fp["tags"] == "imputed" and fp["date"] == "imputed"
    assert rec.pitch.startswith("DevSpot") and len(rec.pitch) <= 1500


def test_alvanlii_empty_prize_string_is_not_a_win():
    rec = sm.from_alvanlii(ALVANLII["It Too Long I Don't Read"], HACKATHONS)
    assert rec.traction["is_winner"] is False and "prize" not in rec.traction
    assert rec.year == 2024 and rec.date == dt.date(2024, 12, 4)
    assert rec.tech == ["chromeextension", "gemini", "vuejs"]


def test_alvanlii_unknown_hackathon_leaves_year_empty():
    rec = sm.from_alvanlii(ALVANLII["Crazy Cows Game"], HACKATHONS)  # hackathon 10000 is not in the sample
    assert rec.year is None and rec.date is None and rec.date_precision is None and rec.tags == []
    assert rec.traction["is_winner"] is True and rec.traction["team_size"] == 2
    assert "year" not in rec.field_provenance
    assert sm.from_alvanlii(ALVANLII["Crazy Cows Game"], None).rid == "devpost:crazy-cows-game"


def test_alvanlii_tech_is_imputed_from_prose_when_the_column_is_empty():
    row = dict(ALVANLII["Crazy Cows Game"], tags="[]",
               full_desc="How we built it\n\nWe built it with Unity and C#, plus a Flask leaderboard.")
    rec = sm.from_alvanlii(row, HACKATHONS)
    assert {"unity", "c#", "flask"} <= set(rec.tech)
    assert rec.field_provenance["tech"] == "imputed"


# ---------------------------------------------------------------- twangodev
def test_twangodev_mapping():
    rec = sm.from_twangodev(TWANGODEV["DoGood"])
    assert rec.rid == "devpost:dogood-gu7clt"
    assert rec.tech[:3] == ["claude-by-anthropic", "figma-make", "interaction-co"]
    assert rec.field_provenance["tech"] == "source"
    assert rec.links == ["https://github.com/Sam-T-G/calhacks25"] and rec.field_provenance["links"] == "source"
    assert (rec.year, rec.date_precision) == (2025, "inferred") and rec.traction["hackathon"] == "Cal Hacks 12.0"
    assert "## README (Sam-T-G/calhacks25)" in rec.description  # READMEs go into the description (BM25) …
    assert "README" not in rec.pitch and "code bundle" not in rec.pitch  # … never into the pitch
    assert rec.traction["is_winner"] is False and "prize" not in rec.traction


def test_twangodev_winner_prize_and_unknown_hackathon_slug():
    rec = sm.from_twangodev(TWANGODEV["Githired"])
    assert rec.traction["is_winner"] is True
    assert rec.traction["prize"] == ["Composio: Best Use of Composio Toolrouter"]
    other = sm.from_twangodev(dict(TWANGODEV["Githired"], hackathon="hackmit-2027"))
    assert (other.year, other.date, other.date_precision) == (2027, None, "year")
    assert other.field_provenance["year"] == "imputed" and other.tags == []


# ---------------------------------------------------------------- YC
def test_yc_mapping():
    rec = sm.from_yc(YC["Gusto"])
    assert rec.rid == "yc:gusto" and rec.source == "yc" and rec.url == "https://www.ycombinator.com/companies/gusto"
    assert rec.tagline == YC["Gusto"]["one_liner"]
    assert rec.description.startswith("Launched in 2012 as ZenPayroll")
    assert rec.year == 2012 and rec.status == "active" and rec.links == ["https://gusto.com"]
    assert set(YC["Gusto"]["tags"]) | set(YC["Gusto"]["industries"]) == set(rec.tags)
    assert rec.traction["batch"] == "Winter 2012" and rec.traction["former_names"] == ["ZenPayroll"]
    assert rec.tech == [] and rec.field_provenance["status"] == "normalized" and rec.field_provenance["year"] == "normalized"


@pytest.mark.parametrize("status,expected", [("Active", "active"), ("Inactive", "dead"), ("Acquired", "acquired"),
                                             ("Public", "active"), ("Stealth", "unknown"), (None, "unknown")])
def test_yc_status_mapping(status, expected):
    assert sm.from_yc(dict(YC["Gusto"], status=status)).status == expected


@pytest.mark.parametrize("batch,year", [("Winter 2012", 2012), ("W12", 2012), ("S21", 2021), ("F24", 2024),
                                        ("X25", 2025), ("Spring 2025", 2025), ("", None), (None, None)])
def test_yc_batch_year(batch, year):
    assert sm.yc_batch_year(batch) == year


def test_yc_launch_date_is_only_trusted_near_the_batch_year():
    rec = sm.from_yc(dict(YC["Gusto"], launched_at=1700000000))  # 2023, batch is Winter 2012
    assert rec.date is None and rec.date_precision == "year" and rec.year == 2012


# ---------------------------------------------------------------- to_doc vs the strict mapping
def _all_records() -> list[SourceRecord]:
    return ([sm.from_alvanlii(r, HACKATHONS) for r in ALVANLII.values()] + [sm.from_twangodev(r) for r in TWANGODEV.values()]
            + [sm.from_yc(r) for r in YC.values()])


def test_to_doc_only_emits_mapped_fields():
    """The index is `dynamic: strict`: one unmapped key rejects the whole document."""
    scan = GPTZeroScan(predicted_class="ai", confidence_category="high", subclass="pure_ai", ai_sentence_share=0.8,
                       result_message="likely AI", model_version="x", scanned_at=dt.datetime(2026, 9, 19, tzinfo=dt.timezone.utc))
    for rec in _all_records():
        rec = rec.model_copy(update={"gptzero": scan, "retrieval": {"query": "q", "rank": 1}})
        doc = common.to_doc(rec, semantic=True)
        assert set(doc) <= set(MAPPING), set(doc) - set(MAPPING)
        assert set(doc["gptzero"]) <= set(MAPPING["gptzero"]["properties"])
        assert "retrieval" not in doc  # query-time state is never indexed


def test_to_doc_semantic_flag_and_first_seen():
    rec = sm.from_twangodev(TWANGODEV["DoGood"])
    sem, bm25 = common.to_doc(rec, semantic=True), common.to_doc(rec, semantic=False)
    assert sem["semantic_pitch"] == rec.pitch and sem["has_semantic"] is True
    assert "semantic_pitch" not in bm25 and bm25["has_semantic"] is False  # Tier 2 is BM25-only
    assert sem["first_seen_at"] == "2025-10-26"  # historical loads use the project date, so watches do not fire
    assert sem["_id"] if "_id" in sem else True
    now = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.timezone.utc)
    assert common.to_doc(rec, semantic=True, first_seen_at=now)["first_seen_at"] == now.isoformat()
    assert sem["is_winner"] is False and sem["hackathon"] == "Cal Hacks 12.0" and sem["hackathon_id"] == "cal-hacks-12-0"
    assert not any(k.startswith("other_dogood") for k in sem["sections"])  # README headings are not write-up sections
    prize = common.to_doc(sm.from_alvanlii(ALVANLII["DevSpot"], HACKATHONS), semantic=False)["prize"]
    assert prize == "Entrepreneurship Award"


# ---------------------------------------------------------------- bulk_index (patched client, no network)
def _fake_client(script):
    """Real client class (never connects) whose `bulk` answers from `script(call_no, ids) -> {id: status}`.

    It has to be a SUBCLASS override: the helpers call `client.options()`, which builds a fresh
    `type(self)(...)` instance, so a `bulk` patched onto one instance is silently dropped (and the helper
    then tries a real connection).
    """
    from elasticsearch import Elasticsearch

    calls = []

    def bulk(self, *args, operations=None, **kwargs):
        lines = [json.loads(op) if isinstance(op, (str, bytes)) else op for op in operations]
        metas = [ln for ln in lines if len(ln) == 1 and next(iter(ln)) in ("index", "create", "update")]
        ids = [next(iter(m.values()))["_id"] for m in metas]
        calls.append({"ids": ids, "kwargs": kwargs, "lines": lines})
        statuses = script(len(calls), ids)
        items = []
        for m, _id in zip(metas, ids):
            op = next(iter(m))
            status = statuses.get(_id, 201)
            item = {"_id": _id, "status": status}
            if status >= 300:
                item["error"] = {"type": "mapper_parsing_exception" if status == 400 else "es_rejected", "reason": f"status {status}"}
            items.append({op: item})
        return types.SimpleNamespace(body={"errors": any(s >= 300 for s in statuses.values()), "items": items})

    fake_cls = type("FakeElasticsearch", (Elasticsearch,), {"bulk": bulk})
    return fake_cls("http://localhost:9200"), calls


def test_bulk_index_retries_429_with_backoff_and_counts_them():
    docs = [{"rid": f"yc:{i}", "pitch": "p" * 300} for i in range(5)]
    client, calls = _fake_client(lambda n, ids: {"yc:1": 429, "yc:3": 429} if n == 1 else {})
    sleeps = []
    stats = common.bulk_index(docs, index="prior-art-v1", semantic=True, chunk_size=10, threads=1, es=client, sleep=sleeps.append)
    assert (stats.ok, stats.failed, stats.retried, stats.http_429, stats.rounds) == (5, 0, 2, 2, 2)
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 2.0
    assert sorted(calls[1]["ids"]) == ["yc:1", "yc:3"]  # only the throttled documents are re-sent
    first_source = calls[0]["lines"][1]
    assert first_source["semantic_pitch"] == first_source["pitch"] and first_source["has_semantic"] is True


def test_bulk_index_quarantines_permanent_failures_and_strips_semantic_when_bm25_only():
    docs = [sm.from_yc(YC["Gusto"]), sm.from_yc(YC["PlanGrid"])]
    client, calls = _fake_client(lambda n, ids: {"yc:gusto": 400} if n == 1 else {})
    stats = common.bulk_index(docs, index="prior-art-v1", semantic=False, chunk_size=10, threads=1, es=client,
                              quarantine_index="prior-art-quarantine", sleep=lambda s: None)
    assert (stats.ok, stats.failed, stats.quarantined) == (1, 1, 1)
    assert "yc:gusto: [400]" in stats.first_errors[0]
    assert all("semantic_pitch" not in ln for ln in calls[0]["lines"])
    q = calls[1]
    assert q["ids"] == ["yc:gusto"] and q["kwargs"].get("pipeline") == "_none"
    assert q["lines"][0]["index"]["_index"] == "prior-art-quarantine" and "[400]" in q["lines"][1]["ingest_error"]


def test_bulk_index_create_treats_existing_documents_as_skipped():
    docs = [{"rid": "devpost:a", "pitch": "x"}, {"rid": "devpost:b", "pitch": "y"}]
    client, _ = _fake_client(lambda n, ids: {"devpost:a": 409})
    done = []
    stats = common.bulk_index(docs, index="i", semantic=False, chunk_size=10, threads=1, es=client, op_type="create",
                              on_batch_done=lambda n, s: done.append(n), sleep=lambda s: None)
    assert (stats.ok, stats.skipped_existing, stats.failed) == (1, 1, 0) and done == [2]


def test_bulk_index_gives_up_after_max_retries():
    client, _ = _fake_client(lambda n, ids: {i: 429 for i in ids})
    stats = common.bulk_index([{"rid": "yc:x", "pitch": "p"}], index="i", semantic=False, chunk_size=5, threads=1, es=client,
                              max_retries=2, sleep=lambda s: None)
    assert (stats.ok, stats.failed, stats.http_429, stats.rounds) == (0, 1, 3, 3)


def test_checkpoint_roundtrip(tmp_path):
    ck = common.Checkpoint("job", resume=False, directory=tmp_path)
    assert ck.offset == 0
    ck.advance(2000, common.BulkStats(ok=1990, failed=10))
    ck.advance(500)
    resumed = common.Checkpoint("job", resume=True, directory=tmp_path)
    assert resumed.offset == 2500 and resumed.state["stats"]["ok"] == 1990
    assert common.Checkpoint("job", resume=False, directory=tmp_path).offset == 0  # no --resume: start over


def test_require_elastic_has_a_clear_message():
    from app.config import Settings

    with pytest.raises(common.ElasticNotConfigured, match="ES_URL and ES_API_KEY"):
        common.require_elastic(Settings(_env_file=None, es_url="", es_api_key=""))


def test_polite_fetcher_refuses_the_search_endpoint_without_any_request():
    fetcher = common.PoliteFetcher(min_interval=0.0)
    try:
        assert fetcher.min_interval >= 1.0  # the 1 req/s floor cannot be configured away
        with pytest.raises(ValueError, match="off-limits"):
            fetcher.get("https://devpost.com/software/search?query=originality")
    finally:
        fetcher.close()


# ---------------------------------------------------------------- live-page parsers (saved HTML)
def test_parse_project_page_fixture():
    rec = parse_project_page((FIXTURES / "devpost_project_page.html").read_text(encoding="utf-8"))
    assert rec.rid == "devpost:hackanalyzer" and rec.title == "HackAnalyzer"
    assert rec.tech == ["javascript", "next", "openai", "react", "sql"]
    assert rec.links == ["https://github.com/angeblecon/hackharvard-project"]
    assert rec.traction["is_winner"] is True and rec.traction["prize"] == ["2nd Best Overall Hack", "Most Creative Use of GitHub"]
    assert rec.traction["hackathon"] == "HackHarvard 2023" and rec.traction["team_size"] == 4
    assert (rec.year, rec.date, rec.date_precision) == (2023, dt.date(2023, 10, 22), "day")
    assert "measures the similarity and originality of new ideas" in rec.pitch and "<" not in rec.pitch
    assert set(common.to_doc(rec, semantic=True)) <= set(MAPPING)
    with pytest.raises(ValueError):
        parse_project_page("<html></html>", "https://devpost.com/hackathons")


def test_parse_gallery_page():
    html = """<div id="submission-gallery">
      <div class="gallery-item"><a class="link-to-software" href="https://devpost.com/software/telespeech?ref=g">
        <h5> TeleSpeech </h5><p class="small tagline">Telegram to speech</p></a>
        <aside class="entry-badge"><img class="winner" alt="Winner"> Winner</aside></div>
      <div class="gallery-item"><a class="link-to-software" href="https://devpost.com/software/hackanalyzer"><h5>HackAnalyzer</h5></a></div>
      <ul class="pagination"><li class="current"><a href="/project-gallery?page=1">1</a></li>
        <li class="next next_page"><a rel="next" href="/project-gallery?page=2">»</a></li></ul></div>"""
    entries, nxt = parse_gallery_page(html, "https://hackharvard-2023.devpost.com/project-gallery?page=1")
    assert [e["url"] for e in entries] == ["https://devpost.com/software/telespeech", "https://devpost.com/software/hackanalyzer"]
    assert entries[0]["is_winner"] and not entries[1]["is_winner"] and entries[0]["title"] == "TeleSpeech"
    assert nxt == "https://hackharvard-2023.devpost.com/project-gallery?page=2"
    last = html.replace('class="next next_page"', 'class="next next_page unavailable"')
    assert parse_gallery_page(last, "https://x.devpost.com/project-gallery")[1] is None
