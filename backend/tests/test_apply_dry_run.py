"""elastic/apply.py --dry-run: every templated artifact renders from settings, with no network and no credentials."""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.schemas.records import GPTZeroScan

REPO_ROOT = Path(__file__).resolve().parents[2]
ELASTIC = REPO_ROOT / "elastic"

_spec = importlib.util.spec_from_file_location("elastic_apply", ELASTIC / "apply.py")
apply = importlib.util.module_from_spec(_spec)
sys.modules["elastic_apply"] = apply
_spec.loader.exec_module(apply)


def settings(**kw) -> Settings:
    base = dict(es_url="", es_api_key="", kibana_url="", slack_webhook_url="", es_embed_inference_id="custom-embed",
                es_rerank_inference_id="custom-rerank", es_index="prior-art-v1", es_quarantine_index="prior-art-quarantine",
                es_watches_index="idea-watches-v1", es_alerts_index="idea-alerts-v1")
    base.update(kw)
    return Settings(_env_file=None, **base)


@pytest.fixture()
def plan():
    return apply.build_plan(settings())


def by_name(plan, name):
    return next(s for s in plan if s.name == name)


def test_plan_order_and_completeness(plan):
    kinds = [s.kind for s in plan]
    assert kinds == sorted(kinds, key=apply.ALL_KINDS.index)  # pipeline -> indices -> tools -> agents -> workflows
    assert kinds[0] == "pipeline"
    names = {s.name for s in plan}
    assert {"prior-art-clean", "prior-art-v1", "prior-art-quarantine", "idea-watches-v1", "idea-alerts-v1",
            "originality.hybrid_prior_art", "originality.semantic_prior_art", "originality.crowding_by_year",
            "originality.cliche_tags", "originality.combination_rarity", "originality.search_nl",
            "prior-art-analyst", "watch-analyst", "originality-arm-watch", "originality-watch-recheck"} <= names
    for s in plan:
        blob = s.body if isinstance(s.body, str) else json.dumps(s.body)
        assert not apply.PLACEHOLDER.search(blob), s.rel


def test_inference_ids_and_index_names_come_from_settings(plan):
    sem = by_name(plan, "prior-art-v1").body["mappings"]["properties"]["semantic_pitch"]
    assert sem == {"type": "semantic_text", "inference_id": "custom-embed",
                   "chunking_settings": {"strategy": "sentence", "max_chunk_size": 250, "sentence_overlap": 1}}
    q = by_name(plan, "originality.hybrid_prior_art").body["configuration"]["query"]
    assert '{"inference_id": "custom-rerank"}' in q and q.startswith("FROM prior-art-v1 METADATA")
    recheck = yaml.safe_load(by_name(plan, "originality-watch-recheck").body)  # parse: YAML quoting style is not a contract
    assert recheck["steps"][1]["steps"][0]["with"]["body"]["retriever"]["text_similarity_reranker"]["inference_id"] == "custom-rerank"
    other = apply.build_plan(settings(es_index="corpus-v7", es_quarantine_index="corpus-bad"))
    assert by_name(other, "corpus-v7").body["settings"]["index"]["default_pipeline"] == "prior-art-clean"
    assert by_name(other, "originality.crowding_by_year").body["configuration"]["query"].startswith("FROM corpus-v7 ")
    assert by_name(other, "prior-art-clean").body["on_failure"][0] == {"set": {"field": "_index", "value": "corpus-bad"}}
    assert by_name(other, "originality.search_nl").body["configuration"]["pattern"] == "corpus-v*"


def test_nothing_committed_hardcodes_an_inference_id_or_a_webhook():
    for path in [*ELASTIC.rglob("*.json"), *ELASTIC.rglob("*.yaml"), *ELASTIC.rglob("*.j2")]:
        text = path.read_text(encoding="utf-8")
        assert ".jina-" not in text and ".elser" not in text, path
        assert "hooks.slack.com" not in text, path


def test_index_pattern_never_matches_the_quarantine_index():
    assert apply.index_pattern("prior-art-v1") == "prior-art-v*"
    assert not re.fullmatch(apply.index_pattern("prior-art-v1").replace("*", ".*"), "prior-art-quarantine")
    assert apply.index_pattern("corpus") == "corpus"


def test_prior_art_mapping_follows_the_python_schema(plan):
    m = by_name(plan, "prior-art-v1").body
    props = m["mappings"]["properties"]
    assert m["mappings"]["dynamic"] == "strict"
    assert set(props["gptzero"]["properties"]) == set(GPTZeroScan.model_fields)  # predicted_class, confidence_category, …
    assert "class" not in props["gptzero"]["properties"] and "confidence" not in props["gptzero"]["properties"]
    assert props["links"] == {"type": "keyword"}
    assert props["pitch"] == {"type": "text", "analyzer": "english"} and props["sections"] == {"type": "object", "enabled": False}
    assert props["traction"]["type"] == "flattened" and props["first_seen_at"]["type"] == "date"
    q = by_name(plan, "prior-art-quarantine").body
    assert q["mappings"]["dynamic"] is False and "settings" not in q  # lenient, and NO default pipeline (would loop)


def test_pipeline_processors(plan):
    p = by_name(plan, "prior-art-clean").body
    kinds = [next(iter(proc)) for proc in p["processors"]]
    assert kinds[0] == "html_strip" and "trim" in kinds and kinds.index("fingerprint") < kinds.index("inference") < kinds.index("script")
    assert {proc["html_strip"]["field"] for proc in p["processors"] if "html_strip" in proc} >= {"description", "pitch"}
    fp = next(proc["fingerprint"] for proc in p["processors"] if "fingerprint" in proc)
    assert fp["target_field"] == "dedupe_key" and fp["fields"][0] == "tmp_title_norm"
    inf = next(proc["inference"] for proc in p["processors"] if "inference" in proc)
    assert inf["model_id"] == "lang_ident_model_1" and inf["field_map"] == {"pitch": "text"}
    assert inf["on_failure"] == [{"set": {"field": "lang", "value": "und", "override": False}}]
    script = next(proc["script"]["source"] for proc in p["processors"] if "script" in proc)
    assert "'too_short'" in script and "250" in script and "'non_english'" in script and "ctx.lang = 'und'" in script
    assert p["processors"][-1] == {"set": {"field": "ingested_at", "value": "{{{_ingest.timestamp}}}"}}  # mustache untouched
    assert p["on_failure"][0] == {"set": {"field": "_index", "value": "prior-art-quarantine"}}
    assert p["on_failure"][1]["set"]["field"] == "ingest_error"
    tmp = {"tmp_title_norm", "tmp_tagline_norm", "tmp_lang"}  # temp fields must never reach the strict mapping
    removed = {f for proc in p["processors"] if "remove" in proc
               for f in ([proc["remove"]["field"]] if isinstance(proc["remove"]["field"], str) else proc["remove"]["field"])}
    assert tmp <= removed
    slim = apply.without_lang_ident(p)
    assert not any("inference" in proc for proc in slim["processors"]) and len(slim["processors"]) == len(p["processors"]) - 1
    assert by_name(apply.build_plan(settings(), no_lang_ident=True), "prior-art-clean").body == slim


def test_esql_tools(plan):
    tools = {s.name: s.body for s in plan if s.kind == "tools"}
    for tid, t in tools.items():
        assert t["id"] == tid and t["description"] and t["type"] in ("esql", "index_search")
        if t["type"] == "esql":
            used = set(re.findall(r"\?(\w+)", t["configuration"]["query"]))
            assert used == set(t["configuration"]["params"]), tid  # every ?param is declared and vice versa
    hybrid = tools["originality.hybrid_prior_art"]["configuration"]
    for kw in ("FORK", "FUSE", "RERANK ?q ON pitch", "MATCH(semantic_pitch, ?q)", "LIMIT ?k", "_index"):
        assert kw in hybrid["query"]
    # Agent Builder 9.6 accepts string|integer|float|boolean|date|array for esql params; 'keyword' is rejected.
    assert hybrid["params"]["k"]["type"] == "integer" and hybrid["params"]["q"]["type"] == "string"
    fallback = tools["originality.semantic_prior_art"]["configuration"]["query"]
    assert "FORK" not in fallback and "RERANK" not in fallback and "MATCH(semantic_pitch, ?q)" in fallback
    assert '{"operator": "AND"}' in tools["originality.combination_rarity"]["configuration"]["query"]
    assert tools["originality.search_nl"]["configuration"] == {"pattern": "prior-art-v*"}
    text = apply.build_plan(settings(), string_param_type="text")
    assert by_name(text, "originality.cliche_tags").body["configuration"]["params"]["keywords"]["type"] == "text"


def test_agents_only_reference_tools_we_ship_or_platform_tools(plan):
    ours = {s.name for s in plan if s.kind == "tools"}
    for agent in (s.body for s in plan if s.kind == "agents"):
        ids = agent["configuration"]["tools"][0]["tool_ids"]
        assert ids and all(t in ours or t.startswith("platform.core.") for t in ids), agent["id"]
        assert agent["configuration"]["instructions"]
    assert ours <= set(by_name(plan, "prior-art-analyst").body["configuration"]["tools"][0]["tool_ids"])


def _step_names(steps):
    for s in steps:
        yield s["name"]
        yield from _step_names(s.get("steps", []))


def test_workflows_without_slack_drop_the_notify_step(plan):
    arm = yaml.safe_load(by_name(plan, "originality-arm-watch").body)
    assert arm["triggers"] == [{"type": "manual"}] and [i["name"] for i in arm["inputs"]] == ["run_id", "idea_text", "facets_query", "threshold"]
    store = arm["steps"][0]["with"]
    assert store["index"] == "idea-watches-v1" and store["id"] == "{{ inputs.run_id }}"  # workflow templates untouched
    step = by_name(plan, "originality-watch-recheck")
    wf = yaml.safe_load(step.body)
    names = list(_step_names(wf["steps"]))
    assert names == ["find_watches", "each_watch", "search_new", "has_new", "triage", "record_alert", "advance_cursor"]
    assert "consts" not in wf and "slack" not in step.body and step.notes
    assert {t["type"] for t in wf["triggers"]} == {"scheduled", "manual"}
    search = wf["steps"][1]["steps"][0]["with"]
    assert search["index"] == "prior-art-v1"
    rr = search["body"]["retriever"]["text_similarity_reranker"]
    assert rr["inference_id"] == "custom-rerank" and rr["retriever"]["rrf"]["filter"] == {
        "range": {"first_seen_at": {"gt": "{{ foreach.item._source.last_checked_at }}"}}}


def test_workflows_with_slack_substitute_the_webhook_from_settings():
    hook = "https://hooks.slack.com/services/T000/B000/XXXX"
    step = by_name(apply.build_plan(settings(slack_webhook_url=hook)), "originality-watch-recheck")
    wf = yaml.safe_load(step.body)
    assert wf["consts"] == {"slack_webhook": hook} and "notify_slack" in list(_step_names(wf["steps"]))
    assert not any(ln.lstrip().startswith("#") for ln in step.body.splitlines())  # comments (and secrets in them) stripped
    assert hook not in apply.mask(step.body, settings(slack_webhook_url=hook))


def test_unknown_placeholder_is_an_error():
    with pytest.raises(KeyError, match="NOPE"):
        apply.render_text("x {{NOPE}} y", {"INDEX": "i"})
    assert apply.render_text("{{{title}}} {{ inputs.run_id }} {{INDEX}}", {"INDEX": "i"}) == "{{{title}}} {{ inputs.run_id }} i"


def test_dry_run_cli_needs_no_credentials_and_no_network(monkeypatch, capsys):
    import httpx

    def boom(*a, **k):
        raise AssertionError("--dry-run must not open a connection")

    monkeypatch.setattr(httpx, "Client", boom)
    assert apply.main(["--dry-run"], settings=settings()) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "custom-embed" in out and "originality.hybrid_prior_art" in out and "(not set)" in out
    assert apply.main(["--dry-run", "--verbose", "--only", "workflows"], settings=settings(es_api_key="SECRETKEY", es_url="https://x")) == 0
    assert "SECRETKEY" not in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[], ["--check"]])
def test_network_modes_fail_clearly_without_credentials(argv):
    with pytest.raises(SystemExit, match="Elastic is not configured"):
        apply.main(argv, settings=settings())


def test_closest_ids_suggests_jina_endpoints_of_the_right_task():
    eps = [{"inference_id": ".jina-embeddings-v5-text-small", "task_type": "text_embedding"},
           {"inference_id": ".jina-reranker-v2-base-multilingual", "task_type": "rerank"},
           {"inference_id": ".elser-2-elastic", "task_type": "sparse_embedding"},
           {"inference_id": ".multilingual-e5-small", "task_type": "text_embedding"}]
    assert apply.closest_ids(".jina-embeddings-v3", eps, "text_embedding") == [".jina-embeddings-v5-text-small"]
    assert apply.closest_ids(".jina-reranker-v3", eps, "rerank") == [".jina-reranker-v2-base-multilingual"]
