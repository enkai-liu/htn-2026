#!/usr/bin/env python
"""Idempotent applier for everything under elastic/ (run from the repo root).

    backend/.venv/bin/python elastic/apply.py --dry-run     # no network: render + print the plan
    backend/.venv/bin/python elastic/apply.py --check       # connectivity, inference ids, lang_ident, Kibana APIs
    backend/.venv/bin/python elastic/apply.py               # pipeline -> indices -> tools -> agents -> workflows
    backend/.venv/bin/python elastic/apply.py --only tools,agents --verbose

Rules: never deletes anything; every step prints OK / SKIP / FAIL; exit code is non-zero if any step FAILed.
Artifacts are templates: {{EMBED_ID}}, {{RERANK_ID}}, {{INDEX}}, ... are substituted from `app.config` settings
(.env), so inference endpoint ids and the Slack webhook are never hardcoded/committed. Only UPPER_CASE
placeholders without spaces are ours; ingest mustache ("{{{title}}}") and workflow templates
("{{ inputs.run_id }}") pass through untouched.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ELASTIC_DIR = Path(__file__).resolve().parent
REPO_ROOT = ELASTIC_DIR.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import Settings, get_settings  # noqa: E402

PIPELINE_NAME = "prior-art-clean"
PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
ALL_KINDS = ("pipeline", "indices", "tools", "agents", "workflows")
WORKFLOWS_HINT = "Workflows API not enabled — enable workflows:ui:enabled (Kibana > Advanced Settings), then re-run"


# --------------------------------------------------------------------------------------
# Rendering (pure; this is what --dry-run and the tests exercise)
# --------------------------------------------------------------------------------------
def index_pattern(index: str) -> str:
    """prior-art-v1 -> prior-art-v*  (NOT prior-art-*, which would also match prior-art-quarantine)."""
    m = re.match(r"^(.*-v)\d+$", index)
    return f"{m.group(1)}*" if m else index


def template_vars(settings: Settings, *, string_param_type: str = "keyword") -> dict[str, str]:
    return {
        "EMBED_ID": settings.es_embed_inference_id,
        "RERANK_ID": settings.es_rerank_inference_id,
        "INDEX": settings.es_index,
        "INDEX_PATTERN": index_pattern(settings.es_index),
        "QUARANTINE_INDEX": settings.es_quarantine_index,
        "WATCHES_INDEX": settings.es_watches_index,
        "ALERTS_INDEX": settings.es_alerts_index,
        "PIPELINE": PIPELINE_NAME,
        "SLACK_WEBHOOK_URL": settings.slack_webhook_url,
        "STRING_PARAM_TYPE": string_param_type,
    }


def render_text(text: str, variables: dict[str, str], *, source: str = "<text>") -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in variables:
            raise KeyError(f"{source}: unknown placeholder {{{{{key}}}}} (known: {sorted(variables)})")
        return variables[key]

    return PLACEHOLDER.sub(sub, text)


def render_json(path: Path, variables: dict[str, str]) -> dict[str, Any]:
    # Values are substituted inside JSON strings, so escape them as JSON string content.
    escaped = {k: json.dumps(v)[1:-1] for k, v in variables.items()}
    return json.loads(render_text(path.read_text(encoding="utf-8"), escaped, source=str(path.relative_to(REPO_ROOT))))


def _drop_step(steps: list[dict[str, Any]], name: str) -> bool:
    removed = False
    for step in list(steps):
        if step.get("name") == name:
            steps.remove(step)
            removed = True
        elif isinstance(step.get("steps"), list):
            removed = _drop_step(step["steps"], name) or removed
    return removed


def render_workflow(path: Path, variables: dict[str, str]) -> tuple[str, dict[str, Any], list[str]]:
    """-> (yaml text to deploy, parsed dict, notes). Comment lines are stripped so a rendered secret never
    lingers in a comment; without a Slack webhook the notify_slack step and the const are removed."""
    import yaml

    notes: list[str] = []
    raw = "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    text = render_text(raw, variables, source=str(path.relative_to(REPO_ROOT)))
    parsed = yaml.safe_load(text)
    uses_slack = "slack_webhook" in (parsed.get("consts") or {})
    if uses_slack and not variables.get("SLACK_WEBHOOK_URL"):
        _drop_step(parsed.get("steps", []), "notify_slack")
        parsed["consts"].pop("slack_webhook", None)
        if not parsed["consts"]:
            parsed.pop("consts")
        text = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True, width=1000)
        notes.append("SLACK_WEBHOOK_URL is empty: notify_slack step removed (alerts still land in the alerts index)")
    return text, parsed, notes


@dataclass
class Step:
    kind: str  # pipeline | indices | tools | agents | workflows
    name: str
    source: Path
    target: str  # "es" | "kibana"
    body: Any  # dict (JSON artifacts) or str (workflow YAML)
    notes: list[str] = field(default_factory=list)
    parsed: dict[str, Any] | None = None  # parsed workflow, for display/tests

    @property
    def rel(self) -> str:
        return str(self.source.relative_to(REPO_ROOT))


def build_plan(settings: Settings, *, string_param_type: str = "keyword", no_lang_ident: bool = False,
               only: tuple[str, ...] = ALL_KINDS) -> list[Step]:
    """Render every artifact in apply order. Pure: no network, works with empty settings."""
    v = template_vars(settings, string_param_type=string_param_type)
    plan: list[Step] = []

    pipeline_path = ELASTIC_DIR / "pipelines" / f"{PIPELINE_NAME}.json"
    pipeline = render_json(pipeline_path, v)
    step = Step("pipeline", PIPELINE_NAME, pipeline_path, "es", pipeline)
    if no_lang_ident:
        step.body = without_lang_ident(pipeline)
        step.notes.append("--no-lang-ident: inference processor removed; `lang` = client-side guess")
    plan.append(step)

    for file_name, index in (
        ("prior-art-v1.json", settings.es_index),
        ("prior-art-quarantine.json", settings.es_quarantine_index),
        ("idea-watches-v1.json", settings.es_watches_index),
        ("idea-alerts-v1.json", settings.es_alerts_index),
    ):
        path = ELASTIC_DIR / "mappings" / file_name
        plan.append(Step("indices", index, path, "es", render_json(path, v)))

    for path in sorted((ELASTIC_DIR / "agent-builder" / "tools").glob("*.json")):
        body = render_json(path, v)
        plan.append(Step("tools", body["id"], path, "kibana", body))
    for path in sorted((ELASTIC_DIR / "agent-builder" / "agents").glob("*.json")):
        body = render_json(path, v)
        plan.append(Step("agents", body["id"], path, "kibana", body))

    for path in sorted((ELASTIC_DIR / "workflows").glob("*.yaml")):
        text, parsed, notes = render_workflow(path, v)
        plan.append(Step("workflows", parsed["name"], path, "kibana", text, notes=notes, parsed=parsed))

    plan = [s for s in plan if s.kind in only]
    for s in plan:  # belt and braces: nothing templated may survive rendering
        blob = s.body if isinstance(s.body, str) else json.dumps(s.body)
        left = PLACEHOLDER.findall(blob)
        if left:
            raise ValueError(f"{s.rel}: unrendered placeholders {sorted(set(left))}")
    return plan


def without_lang_ident(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Pipeline variant for clusters without lang_ident_model_1: drop the inference processor; the script
    processor then keeps the language guessed client-side (ingest/parse_sections.guess_lang)."""
    out = copy.deepcopy(pipeline)
    out["processors"] = [p for p in out["processors"] if "inference" not in p]
    return out


def mask(text: str, settings: Settings) -> str:
    for secret in (settings.slack_webhook_url, settings.es_api_key):
        if secret:
            text = text.replace(secret, secret[:28] + "***" if secret.startswith("http") else "***")
    return text


# --------------------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------------------
class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, status: str, kind: str, name: str, detail: str = "") -> None:
        self.rows.append((status, kind, name, detail))
        print(f"  [{status:<4}] {kind:<9} {name}" + (f"  — {detail}" if detail else ""), flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r[0] == "FAIL")

    def finish(self) -> int:
        counts = {s: sum(1 for r in self.rows if r[0] == s) for s in ("OK", "SKIP", "WARN", "FAIL")}
        print("\nSummary: " + "  ".join(f"{k}={v}" for k, v in counts.items() if v or k in ("OK", "FAIL")))
        return 1 if self.failed else 0


def _short(resp: Any, limit: int = 300) -> str:
    try:
        data = resp.json()
        err = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(err, dict):
            reason = err.get("reason") or err.get("message") or (err.get("root_cause") or [{}])[0].get("reason") or json.dumps(err)
            cause = (err.get("caused_by") or {}).get("reason") if isinstance(err.get("caused_by"), dict) else None
            text = f"{err.get('type', '')} {reason}" + (f" <- {cause}" if cause else "")
        else:
            text = str(err)
        if isinstance(data, dict) and data.get("message") and data.get("message") not in text:
            text = f"{data['message']} {text}"
    except Exception:
        text = resp.text
    return f"HTTP {resp.status_code}: {' '.join(str(text).split())[:limit]}"


# --------------------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------------------
def describe(step: Step, settings: Settings, kibana_prefix: str) -> str:
    es = settings.es_url.rstrip("/") or "{ES_URL}"
    kb = (settings.kibana_url.rstrip("/") or "{KIBANA_URL}") + kibana_prefix
    if step.kind == "pipeline":
        return f"PUT  {es}/_ingest/pipeline/{step.name}   ({len(step.body['processors'])} processors, on_failure -> {settings.es_quarantine_index})"
    if step.kind == "indices":
        props = step.body.get("mappings", {}).get("properties", {})
        extra = ""
        sem = [f"{k} -> {p.get('inference_id')}" for k, p in props.items() if p.get("type") == "semantic_text"]
        if sem:
            extra = f", semantic_text: {', '.join(sem)}"
        return (f"PUT  {es}/{step.name}   (create if missing, else additive PUT _mapping; never deleted; "
                f"dynamic={step.body['mappings'].get('dynamic')}, {len(props)} fields{extra})")
    if step.kind == "tools":
        cfg = step.body.get("configuration", {})
        what = f"params={list(cfg.get('params', {}))}" if step.body["type"] == "esql" else f"pattern={cfg.get('pattern')}"
        return f"POST {kb}/api/agent_builder/tools   (PUT …/tools/{step.name} if it exists; type={step.body['type']}, {what})"
    if step.kind == "agents":
        ids = step.body["configuration"]["tools"][0]["tool_ids"]
        return f"POST {kb}/api/agent_builder/agents   (PUT …/agents/{step.name} if it exists; {len(ids)} tools)"
    steps = [s["name"] for s in (step.parsed or {}).get("steps", [])]
    triggers = [t["type"] for t in (step.parsed or {}).get("triggers", [])]
    return f"POST {kb}/api/workflows/workflow   body={{yaml}}  (PUT …/workflow/<id> if it exists; triggers={triggers}, steps={steps})"


def dry_run(settings: Settings, args: argparse.Namespace) -> int:
    plan = build_plan(settings, string_param_type=args.string_param_type, no_lang_ident=args.no_lang_ident, only=args.only)
    v = template_vars(settings, string_param_type=args.string_param_type)
    print("DRY RUN — nothing is sent. Settings in effect:")
    print(f"  ES_URL      = {settings.es_url or '(not set)'}")
    print(f"  KIBANA_URL  = {settings.kibana_url or '(not set)'}")
    print(f"  ES_API_KEY  = {'(set)' if settings.es_api_key else '(not set)'}")
    for key in ("EMBED_ID", "RERANK_ID", "INDEX", "INDEX_PATTERN", "QUARANTINE_INDEX", "WATCHES_INDEX", "ALERTS_INDEX", "PIPELINE"):
        print(f"  {{{{{key}}}}} -> {v[key]}")
    print(f"  {{{{SLACK_WEBHOOK_URL}}}} -> {'(set, masked)' if settings.slack_webhook_url else '(not set)'}")
    print(f"\nPlan ({len(plan)} steps, applied in this order):")
    for i, step in enumerate(plan, 1):
        print(f"{i:>3}. [{step.kind}] {step.name}   <- {step.rel}")
        print(f"       {describe(step, settings, args.kibana_prefix)}")
        for note in step.notes:
            print(f"       note: {note}")
        if args.verbose:
            body = step.body if isinstance(step.body, str) else json.dumps(step.body, indent=2, ensure_ascii=False)
            print("       " + mask(body, settings).replace("\n", "\n       "))
    if not settings.has_elastic:
        print("\nElastic credentials are not set: fill ES_URL / ES_API_KEY / KIBANA_URL in .env, then run --check and apply.")
    return 0


# --------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------
class Clients:
    def __init__(self, settings: Settings, kibana_prefix: str = "") -> None:
        import httpx

        if not settings.has_elastic:
            raise SystemExit("Elastic is not configured: set ES_URL and ES_API_KEY (and KIBANA_URL) in the repo-root .env. "
                             "`--dry-run` works without credentials.")
        auth = {"Authorization": f"ApiKey {settings.es_api_key}"}
        self.es = httpx.Client(base_url=settings.es_url.rstrip("/"), headers={**auth, "Content-Type": "application/json"}, timeout=60)
        self.kb = None
        if settings.kibana_url:
            self.kb = httpx.Client(
                base_url=settings.kibana_url.rstrip("/") + kibana_prefix,
                headers={**auth, "kbn-xsrf": "true", "Content-Type": "application/json"}, timeout=60,
            )


def apply_pipeline(c: Clients, step: Step, rep: Report) -> None:
    r = c.es.put(f"/_ingest/pipeline/{step.name}", json=step.body)
    if r.status_code < 300:
        return rep.add("OK", step.kind, step.name, "; ".join(step.notes))
    msg = _short(r)
    if any("inference" in p for p in step.body["processors"]) and re.search(r"lang_ident|trained model|inference|model", msg, re.I):
        r2 = c.es.put(f"/_ingest/pipeline/{step.name}", json=without_lang_ident(step.body))
        if r2.status_code < 300:
            return rep.add("OK", step.kind, step.name, f"applied WITHOUT lang_ident_model_1 ({msg}); `lang` falls back to the client-side guess")
        msg = _short(r2)
    rep.add("FAIL", step.kind, step.name, msg)


def apply_index(c: Clients, step: Step, rep: Report) -> None:
    head = c.es.head(f"/{step.name}")
    if head.status_code == 200:
        r = c.es.put(f"/{step.name}/_mapping", json={"properties": step.body["mappings"].get("properties", {})})
        if r.status_code < 300:
            return rep.add("OK", step.kind, step.name, "exists; mapping merged (additive), nothing deleted")
        return rep.add("SKIP", step.kind, step.name, f"exists; existing mapping kept — merge rejected: {_short(r)}")
    if head.status_code not in (404,):
        return rep.add("FAIL", step.kind, step.name, f"HEAD returned HTTP {head.status_code}")
    r = c.es.put(f"/{step.name}", json=step.body)
    if r.status_code < 300:
        return rep.add("OK", step.kind, step.name, "created")
    msg = _short(r)
    settings_block = step.body.get("settings", {}).get("index", {})
    if "refresh_interval" in settings_block and re.search(r"setting|refresh_interval|serverless|not allowed", msg, re.I):
        body = copy.deepcopy(step.body)
        body["settings"]["index"].pop("refresh_interval", None)
        r2 = c.es.put(f"/{step.name}", json=body)
        if r2.status_code < 300:
            return rep.add("OK", step.kind, step.name, "created without refresh_interval (not allowed on this project)")
        msg = _short(r2)
    hint = ""
    if re.search(r"inference", msg, re.I):
        hint = "  HINT: run --check to list inference ids, then set ES_EMBED_INFERENCE_ID in .env"
    elif re.search(r"pipeline", msg, re.I):
        hint = "  HINT: the default pipeline must exist first (run without --only, or --only pipeline)"
    rep.add("FAIL", step.kind, step.name, msg + hint)


def _swap_string_type(body: dict[str, Any]) -> dict[str, Any] | None:
    params = body.get("configuration", {}).get("params") or {}
    if not any(p.get("type") in ("keyword", "text") for p in params.values()):
        return None
    out = copy.deepcopy(body)
    for p in out["configuration"]["params"].values():
        if p.get("type") in ("keyword", "text"):
            p["type"] = "text" if p["type"] == "keyword" else "keyword"
    return out


def _upsert(c: Clients, collection: str, body: dict[str, Any], immutable: tuple[str, ...]) -> Any:
    """PUT if it exists, else POST. The update API rejects immutable keys (id/type), so they are stripped."""
    exists = c.kb.get(f"/api/agent_builder/{collection}/{body['id']}")
    if exists.status_code == 200:
        return c.kb.put(f"/api/agent_builder/{collection}/{body['id']}", json={k: v for k, v in body.items() if k not in immutable}), "updated"
    return c.kb.post(f"/api/agent_builder/{collection}", json=body), "created"


def apply_tool(c: Clients, step: Step, rep: Report, available: set[str]) -> None:
    r, verb = _upsert(c, "tools", step.body, ("id", "type"))
    if r.status_code >= 400 and r.status_code != 404:
        swapped = _swap_string_type(step.body)
        if swapped is not None and re.search(r"param|type|keyword|text|schema|valid", _short(r), re.I):
            r2, verb2 = _upsert(c, "tools", swapped, ("id", "type"))
            if r2.status_code < 300:
                available.add(step.name)
                return rep.add("OK", step.kind, step.name, f"{verb2} with the alternative string param type (pass --string-param-type to make it the default)")
    if r.status_code < 300:
        available.add(step.name)
        return rep.add("OK", step.kind, step.name, verb)
    detail = _short(r)
    if r.status_code == 404:
        detail += "  HINT: Agent Builder API not found — is KIBANA_URL right / Agent Builder enabled? (non-default space: --space NAME)"
    elif step.name.endswith("hybrid_prior_art"):
        detail += "  HINT: FORK/FUSE/RERANK may be unavailable here — originality.semantic_prior_art is the fallback tool"
    rep.add("FAIL", step.kind, step.name, detail)


def apply_agent(c: Clients, step: Step, rep: Report, available: set[str], planned_tools: set[str]) -> None:
    body = copy.deepcopy(step.body)
    ids = body["configuration"]["tools"][0]["tool_ids"]
    missing = [t for t in ids if t in planned_tools and t not in available]
    for t in [t for t in ids if t.startswith("originality.") and t not in planned_tools and t not in available]:
        if c.kb.get(f"/api/agent_builder/tools/{t}").status_code == 200:
            available.add(t)
        else:
            missing.append(t)
    body["configuration"]["tools"][0]["tool_ids"] = [t for t in ids if t not in missing]
    r, verb = _upsert(c, "agents", body, ("id",))
    if r.status_code >= 400 and re.search(r"tool", _short(r), re.I):  # a platform.* tool id this deployment lacks
        body["configuration"]["tools"][0]["tool_ids"] = [t for t in body["configuration"]["tools"][0]["tool_ids"] if not t.startswith("platform.")]
        r, verb = _upsert(c, "agents", body, ("id",))
        verb += " without platform.* tools"
    if r.status_code < 300:
        return rep.add("OK", step.kind, step.name, verb + (f"; tools not available and left out: {missing}" if missing else ""))
    rep.add("FAIL", step.kind, step.name, _short(r))


def _find_workflow_id(c: Clients, name: str) -> str | None:
    """Best effort: look an existing workflow up by name so a re-run updates instead of duplicating."""
    try:
        r = c.kb.post("/api/workflows/search", json={"query": name, "limit": 100, "page": 1})
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("results") or data.get("workflows") or data.get("items") or data.get("data") or []
        for item in items:
            if isinstance(item, dict) and item.get("name") == name and item.get("id"):
                return str(item["id"])
    except Exception:
        return None
    return None


def apply_workflow(c: Clients, step: Step, rep: Report) -> None:
    note = "; ".join(step.notes)
    existing = _find_workflow_id(c, step.name)
    if existing:
        r = c.kb.put(f"/api/workflows/workflow/{existing}", json={"yaml": step.body})
        if r.status_code < 300:
            return rep.add("OK", step.kind, step.name, f"updated ({existing})" + (f"; {note}" if note else ""))
    r = c.kb.post("/api/workflows/workflow", json={"yaml": step.body})
    if r.status_code == 404:
        return rep.add("SKIP", step.kind, step.name, WORKFLOWS_HINT)
    if r.status_code < 300:
        try:
            wid = r.json().get("id")
        except Exception:
            wid = None
        return rep.add("OK", step.kind, step.name, f"created ({wid})" + (f"; {note}" if note else ""))
    rep.add("FAIL", step.kind, step.name, _short(r, 500) + "  HINT: validate the YAML in the Kibana Workflows editor or POST /api/workflows/test")


def apply_all(settings: Settings, args: argparse.Namespace) -> int:
    plan = build_plan(settings, string_param_type=args.string_param_type, no_lang_ident=args.no_lang_ident, only=args.only)
    c = Clients(settings, args.kibana_prefix)
    rep = Report()
    available: set[str] = set()
    planned_tools = {s.name for s in plan if s.kind == "tools"}
    print(f"Applying {len(plan)} artifacts to {settings.es_url}" + (f" and {settings.kibana_url}" if settings.kibana_url else ""))
    for step in plan:
        try:
            if step.target == "kibana" and c.kb is None:
                rep.add("SKIP", step.kind, step.name, "KIBANA_URL is not set")
            elif step.kind == "pipeline":
                apply_pipeline(c, step, rep)
            elif step.kind == "indices":
                apply_index(c, step, rep)
            elif step.kind == "tools":
                apply_tool(c, step, rep, available)
            elif step.kind == "agents":
                apply_agent(c, step, rep, available, planned_tools)
            else:
                apply_workflow(c, step, rep)
        except Exception as exc:  # network errors etc.: report and carry on with the next artifact
            rep.add("FAIL", step.kind, step.name, f"{type(exc).__name__}: {exc}")
    return rep.finish()


# --------------------------------------------------------------------------------------
# --check
# --------------------------------------------------------------------------------------
def closest_ids(wanted: str, endpoints: list[dict[str, Any]], task_type: str) -> list[str]:
    """Closest Jina inference ids of the right task type (falls back to any id of that task type)."""
    same_task = [e["inference_id"] for e in endpoints if e.get("task_type") == task_type]
    jina = [i for i in same_task if "jina" in i.lower()]
    pool = jina or same_task
    ranked = difflib.get_close_matches(wanted, pool, n=3, cutoff=0.0)
    return ranked or pool[:3]


def check(settings: Settings, args: argparse.Namespace) -> int:
    c = Clients(settings, args.kibana_prefix)
    rep = Report()
    print(f"Checking {settings.es_url}")
    try:
        r = c.es.get("/")
        if r.status_code == 200:
            ver = r.json().get("version", {})
            rep.add("OK", "connect", "elasticsearch", f"version={ver.get('number')} build_flavor={ver.get('build_flavor')}")
        else:
            rep.add("FAIL", "connect", "elasticsearch", _short(r))
            return rep.finish()
    except Exception as exc:
        rep.add("FAIL", "connect", "elasticsearch", f"{type(exc).__name__}: {exc}")
        return rep.finish()

    r = c.es.get("/_inference/_all")
    endpoints: list[dict[str, Any]] = r.json().get("endpoints", []) if r.status_code == 200 else []
    if r.status_code != 200:
        rep.add("FAIL", "inference", "_inference/_all", _short(r))
    else:
        print("\n  task_type          inference_id                                 service")
        for e in sorted(endpoints, key=lambda e: (e.get("task_type", ""), e.get("inference_id", ""))):
            print(f"  {e.get('task_type', ''):<18} {e.get('inference_id', ''):<44} {e.get('service', '')}")
        print()
        for label, wanted, task in (("embed", settings.es_embed_inference_id, "text_embedding"),
                                    ("rerank", settings.es_rerank_inference_id, "rerank")):
            hit = next((e for e in endpoints if e.get("inference_id") == wanted), None)
            if hit and hit.get("task_type") == task:
                rep.add("OK", "inference", f"{label}: {wanted}", f"task_type={task}")
            elif hit:
                rep.add("FAIL", "inference", f"{label}: {wanted}", f"exists but task_type={hit.get('task_type')} (need {task}); closest: {closest_ids(wanted, endpoints, task)}")
            else:
                env = "ES_EMBED_INFERENCE_ID" if label == "embed" else "ES_RERANK_INFERENCE_ID"
                rep.add("FAIL", "inference", f"{label}: {wanted}", f"NOT FOUND — set {env} in .env to one of: {closest_ids(wanted, endpoints, task)}")

    sim = {
        "pipeline": {"processors": [{"inference": {"model_id": "lang_ident_model_1", "target_field": "tmp_lang", "field_map": {"pitch": "text"}}}]},
        "docs": [{"_source": {"pitch": "This extension summarizes the whole web page into a single paragraph and answers questions about it."}},
                 {"_source": {"pitch": "Nuestra aplicación ayuda a los estudiantes a encontrar grupos de estudio cerca de su universidad."}}],
    }
    r = c.es.post("/_ingest/pipeline/_simulate", json=sim)
    if r.status_code == 200:
        langs = []
        for d in r.json().get("docs", []):
            if "error" in d:
                langs.append("ERROR:" + str(d["error"].get("reason", ""))[:120])
            else:
                langs.append(str(d.get("doc", {}).get("_source", {}).get("tmp_lang", {}).get("predicted_value")))
        if langs[:2] == ["en", "es"]:
            rep.add("OK", "lang", "lang_ident_model_1", f"predicted {langs}")
        else:
            rep.add("WARN", "lang", "lang_ident_model_1", f"unexpected result {langs} — apply with --no-lang-ident to rely on the client-side guess")
    else:
        rep.add("WARN", "lang", "lang_ident_model_1", f"not usable here ({_short(r)}) — apply.py will fall back to the pipeline without it")

    r = c.es.get(f"/_ingest/pipeline/{PIPELINE_NAME}")
    rep.add("OK" if r.status_code == 200 else "WARN", "pipeline", PIPELINE_NAME, "present" if r.status_code == 200 else "not applied yet")
    for index in (settings.es_index, settings.es_quarantine_index, settings.es_watches_index, settings.es_alerts_index):
        r = c.es.get(f"/{index}/_count")
        if r.status_code == 200:
            rep.add("OK", "index", index, f"{r.json().get('count')} docs")
        else:
            rep.add("WARN", "index", index, "missing (run apply)" if r.status_code == 404 else _short(r))

    if c.kb is None:
        rep.add("WARN", "kibana", "KIBANA_URL", "not set — Agent Builder tools/agents and Workflows cannot be applied")
        return rep.finish()
    try:
        r = c.kb.get("/api/agent_builder/tools")
        if r.status_code == 200:
            data = r.json()
            tools = data.get("results", data if isinstance(data, list) else [])
            ours = sorted(t.get("id") for t in tools if isinstance(t, dict) and str(t.get("id", "")).startswith("originality."))
            rep.add("OK", "kibana", "agent_builder/tools", f"{len(tools)} tools visible; ours: {ours or 'none yet'}")
        else:
            rep.add("FAIL", "kibana", "agent_builder/tools", _short(r))
        r = c.kb.post("/api/workflows/search", json={"limit": 1, "page": 1})
        if r.status_code == 200:
            rep.add("OK", "kibana", "workflows API", "reachable")
        elif r.status_code == 404:
            rep.add("WARN", "kibana", "workflows API", WORKFLOWS_HINT)
        else:
            rep.add("WARN", "kibana", "workflows API", f"search probe answered {_short(r)} (creation may still work)")
    except Exception as exc:
        rep.add("FAIL", "kibana", "connect", f"{type(exc).__name__}: {exc}")
    return rep.finish()


# --------------------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="connectivity + inference ids + lang_ident + Kibana APIs; changes nothing")
    mode.add_argument("--dry-run", action="store_true", help="no network: render every templated artifact and print the plan")
    ap.add_argument("--only", default=",".join(ALL_KINDS), help=f"comma list from: {', '.join(ALL_KINDS)}")
    ap.add_argument("--verbose", "-v", action="store_true", help="dry-run: also print every rendered body (secrets masked)")
    ap.add_argument("--string-param-type", choices=("keyword", "text"), default="keyword",
                    help="Agent Builder ES|QL string param type (the other one is retried automatically on a 400)")
    ap.add_argument("--no-lang-ident", action="store_true", help="apply the pipeline without the lang_ident_model_1 inference processor")
    ap.add_argument("--space", default="", help="Kibana space name for non-default spaces (adds the /s/<space> prefix)")
    args = ap.parse_args(argv)
    args.only = tuple(k.strip() for k in args.only.split(",") if k.strip())
    unknown = [k for k in args.only if k not in ALL_KINDS]
    if unknown:
        ap.error(f"--only: unknown kind(s) {unknown}; choose from {ALL_KINDS}")
    args.kibana_prefix = f"/s/{args.space}" if args.space else ""
    return args


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = parse_args(argv)
    settings = settings or get_settings()
    if args.dry_run:
        return dry_run(settings, args)
    if args.check:
        return check(settings, args)
    return apply_all(settings, args)


if __name__ == "__main__":
    sys.exit(main())
