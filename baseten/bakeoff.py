"""Baseten bake-off: right-size a model per agent role with measurements instead of vibes.

    backend/.venv/bin/python baseten/bakeoff.py                       # default candidates, 8 prompts per task
    backend/.venv/bin/python baseten/bakeoff.py -n 12 --concurrency 4 --rpm 100
    backend/.venv/bin/python baseten/bakeoff.py --models openai/gpt-oss-120b zai-org/GLM-5.3-Flash
    backend/.venv/bin/python baseten/bakeoff.py --extra '{"reasoning_effort": "low"}' --tag low-reasoning

For every candidate slug, over N prompts per task, it measures:
  latency            p50 / p95 wall-clock per successful request (non-streaming)
  JSON-schema        share of `response_format: {type: json_schema}` answers that parse AND validate (facet extraction)
  tool calling       share of one-tool tasks answered with a well-formed call to that tool
  tokens             mean prompt / completion / reasoning tokens, completion tokens per second, estimated cost
  reasoning default  whether the model reasons without being asked (reasoning tokens or `reasoning_content` present)
                     -- those models can blow the 90-second run budget, so they need a switch or a different role
Writes a markdown table to docs/sponsors/baseten-bakeoff.md and raw JSON to baseten/results/.

Notes: Baseten caps `n` at 1, so every sample is its own request. Unverified accounts get 15 RPM (verified: 120):
pass --rpm 15 if the account is not verified yet. The shared system prompt comes first so prefix caching can kick in.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

import httpx  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from app.config import get_settings  # noqa: E402

# Starting assignment from docs/design-full.md section 2.5; this script is what confirms or changes it.
DEFAULT_MODELS = [
    "zai-org/GLM-5.3-Flash",  # conductor, actuator, juror
    "deepseek-ai/DeepSeek-V4-Flash-0731",  # scouts, resolver
    "deepseek-ai/DeepSeek-V4.1-Flash",  # juror
    "openai/gpt-oss-120b",  # juror
    "moonshotai/Kimi-K2.6",  # mutator, juror
    "zai-org/GLM-5.3",  # advocate, synthesizer
    "deepseek-ai/DeepSeek-V4-Pro",  # critic
]
# USD per 1M tokens (input, output), from docs/research/02-gptzero-baseten.md B3. Unknown slugs get no cost estimate.
PRICES = {
    "zai-org/GLM-5.3": (1.40, 4.40), "zai-org/GLM-5.3-Flash": (0.15, 0.50), "deepseek-ai/DeepSeek-V4.1-Flash": (0.30, 1.20),
    "deepseek-ai/DeepSeek-V4-Flash-0731": (0.13, 0.26), "moonshotai/Kimi-K3": (3.00, 15.00),
}
MD_PATH = REPO_ROOT / "docs" / "sponsors" / "baseten-bakeoff.md"
RESULTS_DIR = REPO_ROOT / "baseten" / "results"

SYSTEM = ("You are a component of Whitespace, a system that scores how original a hackathon or startup idea is. "
          "Be precise and terse. Follow the requested output format exactly.")
IDEAS = [
    "An AI study buddy that turns your lecture notes into flashcards and quizzes you with spaced repetition.",
    "Point your phone at the fridge and get recipes for what is inside, ranked by what expires first.",
    "A journaling app with an AI therapist that spots mood patterns and suggests coping exercises.",
    "Webcam sign-language-to-text for video calls, running fully in the browser.",
    "A tool that checks whether your hackathon idea already exists on Devpost before you start building.",
    "A CI scheduler that delays non-urgent builds until the grid's carbon intensity is low.",
    "A murder-mystery party game generated from your team's git blame history.",
    "A shape-changing tactile display that lets blind users feel the uncertainty in a weather forecast.",
    "Uber for dog walking, with live GPS tracking and automatic poop-bag restocking.",
    "A browser extension that rewrites clickbait headlines into plain factual ones.",
    "Smart compost bin that identifies what you throw in and coaches your household toward zero food waste.",
    "A marketplace where students rent out unused dorm-room gear by the hour.",
]
FACET_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["purpose", "mechanism", "audience", "data", "twist", "domain", "keywords"],
    "properties": {
        "purpose": {"type": "string"}, "mechanism": {"type": "string"}, "audience": {"type": "string"},
        "data": {"type": "string"}, "twist": {"type": "string"}, "domain": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
}
TOOL = {"type": "function", "function": {
    "name": "search_prior_art",
    "description": "Search an index of past hackathon projects and startups for prior art.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["query", "source"], "properties": {
        "query": {"type": "string", "description": "3-8 keywords describing the idea"},
        "source": {"type": "string", "enum": ["devpost", "yc", "github", "hn"]}}}}}
SOURCES = ("devpost", "yc", "github", "hn")


class FacetsOut(BaseModel):
    purpose: str
    mechanism: str
    audience: str
    data: str
    twist: str
    domain: str
    keywords: list[str]


@dataclass
class Call:
    model: str
    task: str
    ok: bool = False
    status: int | None = None
    error: str | None = None
    latency_s: float | None = None
    retries: int = 0
    rate_limited: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    reasoned: bool = False
    passed: bool | None = None  # task-specific success (schema-valid JSON / well-formed tool call)
    repairable: bool | None = None
    note: str = ""


class RateLimiter:
    """Evenly spaced request starts: at most `rpm` per minute across the whole bake-off."""

    def __init__(self, rpm: float) -> None:
        self.interval = 60.0 / max(1.0, rpm)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if delay:
            await asyncio.sleep(delay)


def body_for(task: str, model: str, idea: str, max_tokens: int, extra: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": 0.2}
    if task == "json":
        body["messages"] = [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": f"Extract the facets of this idea as JSON.\n\nIdea: {idea}"}]
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "facets", "strict": True, "schema": FACET_SCHEMA}}
    elif task == "tool":
        body["messages"] = [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": "Find prior art for this idea. You must call the search tool exactly "
                                                        f"once and say nothing else.\n\nIdea: {idea}"}]
        body["tools"] = [TOOL]
        body["tool_choice"] = "auto"
    else:
        raise ValueError(task)
    body.update(extra)
    return body


def grade(task: str, message: dict[str, Any]) -> tuple[bool, bool | None, str]:
    """(passed, repairable, note)."""
    if task == "json":
        content = message.get("content") or ""
        try:
            FacetsOut.model_validate(json.loads(content))
            return True, None, ""
        except (ValueError, ValidationError) as exc:
            try:
                from json_repair import repair_json

                FacetsOut.model_validate(json.loads(repair_json(content)))
                return False, True, f"needed json_repair: {str(exc)[:80]}"
            except Exception:  # noqa: BLE001
                return False, False, f"invalid: {str(exc)[:80]}" if content else "empty content (token budget spent on reasoning?)"
    calls = message.get("tool_calls") or []
    if len(calls) != 1:
        return False, None, f"{len(calls)} tool calls"
    fn = calls[0].get("function") or {}
    if fn.get("name") != TOOL["function"]["name"]:
        return False, None, f"wrong tool {fn.get('name')!r}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except ValueError:
        return False, None, "arguments are not JSON"
    if not isinstance(args.get("query"), str) or not args["query"].strip() or args.get("source") not in SOURCES:
        return False, None, f"bad arguments {str(args)[:80]}"
    return True, None, ""


def reasoning_signals(message: dict[str, Any], usage: dict[str, Any]) -> tuple[bool, int]:
    details = usage.get("completion_tokens_details") or {}
    tokens = int(details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0)
    text = message.get("reasoning_content") or message.get("reasoning") or ""
    content = message.get("content") or ""
    return bool(tokens or (isinstance(text, str) and text.strip()) or "<think>" in content), tokens


async def one_call(client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any], task: str,
                   sem: asyncio.Semaphore, limiter: RateLimiter, max_retries: int = 2) -> Call:
    call = Call(model=body["model"], task=task)
    async with sem:
        for attempt in range(max_retries + 1):
            await limiter.wait()
            started = time.monotonic()
            try:
                resp = await client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                call.error = f"{type(exc).__name__}"
                if attempt < max_retries:
                    call.retries += 1
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return call
            call.status = resp.status_code
            if resp.status_code == 429 or resp.status_code >= 500:
                call.rate_limited += resp.status_code == 429
                call.error = f"HTTP {resp.status_code}"
                if attempt < max_retries:
                    call.retries += 1
                    await asyncio.sleep(2.0 * 2 ** attempt)
                    continue
                return call
            if resp.status_code != 200:
                call.error = f"HTTP {resp.status_code}: {resp.text[:160]}"
                return call
            call.latency_s = time.monotonic() - started
            try:
                data = resp.json()
                message = data["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError):
                call.error = "malformed completion payload"
                return call
            usage = data.get("usage") or {}
            call.ok, call.error = True, None
            call.prompt_tokens = int(usage.get("prompt_tokens") or 0)
            call.completion_tokens = int(usage.get("completion_tokens") or 0)
            call.reasoned, call.reasoning_tokens = reasoning_signals(message, usage)
            call.passed, call.repairable, call.note = grade(task, message)
            return call
    return call


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def summarise(model: str, calls: list[Call]) -> dict[str, Any]:
    ok = [c for c in calls if c.ok]
    lat = [c.latency_s for c in ok if c.latency_s is not None]

    def rate(task: str) -> float | None:
        graded = [c for c in calls if c.task == task]  # a failed request counts as a failed task: that is what a role sees
        return round(sum(1 for c in graded if c.passed) / len(graded), 3) if graded else None

    def mean(attr: str) -> float | None:
        return round(statistics.fmean(getattr(c, attr) for c in ok), 1) if ok else None

    out_tokens = sum(c.completion_tokens for c in ok)
    price = PRICES.get(model)
    cost = None
    if price and ok:
        cost = round(statistics.fmean(c.prompt_tokens * price[0] / 1e6 + c.completion_tokens * price[1] / 1e6 for c in ok) * 1000, 4)
    reasoned = sum(1 for c in ok if c.reasoned)
    errors: dict[str, int] = {}
    for c in calls:
        if not c.ok:
            key = (c.error or "error").split(":")[0]
            errors[key] = errors.get(key, 0) + 1
    return {
        "model": model, "requests": len(calls), "ok": len(ok), "errors": errors,
        "rate_limited": sum(c.rate_limited for c in calls), "retries": sum(c.retries for c in calls),
        "latency_p50_s": None if not lat else round(pct(lat, 0.5), 2), "latency_p95_s": None if not lat else round(pct(lat, 0.95), 2),
        "json_schema_valid": rate("json"),
        "json_repairable": sum(1 for c in calls if c.task == "json" and c.repairable),
        "tool_call_success": rate("tool"),
        "prompt_tokens_mean": mean("prompt_tokens"), "completion_tokens_mean": mean("completion_tokens"),
        "reasoning_tokens_mean": mean("reasoning_tokens"),
        "reasoning_by_default": None if not ok else reasoned / len(ok) >= 0.5,
        "reasoning_share": None if not ok else round(reasoned / len(ok), 2),
        "completion_tokens_per_s": round(out_tokens / sum(lat), 1) if lat and sum(lat) > 0 else None,
        "est_usd_per_1k_calls": cost,
        "notes": sorted({c.note for c in calls if c.note})[:4],
    }


def picks(rows: list[dict[str, Any]]) -> list[str]:
    usable = [r for r in rows if r["latency_p50_s"] is not None]
    out = []
    structured = [r for r in usable if (r["json_schema_valid"] or 0) >= 0.95]
    tools = [r for r in usable if (r["tool_call_success"] or 0) >= 0.9]
    if structured:
        best = min(structured, key=lambda r: r["latency_p50_s"])
        out.append(f"**Structured-output roles** (conductor, resolver, judge): `{best['model']}` is the fastest model with "
                   f">= 95% schema-valid JSON (p50 {best['latency_p50_s']} s).")
        priced = [r for r in structured if r["est_usd_per_1k_calls"] is not None]
        if priced:
            cheap = min(priced, key=lambda r: r["est_usd_per_1k_calls"])
            out.append(f"**Cheapest reliable JSON**: `{cheap['model']}` at about ${cheap['est_usd_per_1k_calls']} per 1,000 calls.")
    if tools:
        best = min(tools, key=lambda r: r["latency_p50_s"])
        out.append(f"**Tool-calling roles** (scouts over MCP, critic re-queries): `{best['model']}` is the fastest model with "
                   f">= 90% well-formed tool calls (p50 {best['latency_p50_s']} s).")
    slow = [r["model"] for r in usable if r["reasoning_by_default"]]
    if slow:
        out.append("**Reasoning on by default**: " + ", ".join(f"`{m}`" for m in slow) + ". Keep them off the latency-critical "
                   "path (or re-run with `--extra` to test a low-reasoning switch) so a run stays inside its 90 s budget.")
    return out


def fmt(v: Any, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and suffix == "%":
        return f"{v:.0%}"
    return f"{v}{suffix}"


def render_markdown(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [
        "# Baseten bake-off", "",
        f"Generated {meta['generated_at']} by `baseten/bakeoff.py` against `{meta['base_url']}`. "
        f"{meta['n']} prompts per task per model, concurrency {meta['concurrency']}, temperature 0.2, max_tokens {meta['max_tokens']}"
        + (f", extra body `{json.dumps(meta['extra'])}`" if meta["extra"] else "") + ".", "",
        "Two tasks taken from the product: **facet extraction** under `response_format: json_schema` (what the conductor and "
        "judge do) and a **one-tool prior-art search** (what scouts and the critic do). A failed request counts as a failed task.", "",
        "| Model | OK | p50 s | p95 s | JSON-schema valid | Tool call OK | Reasons by default | Tokens in / out (reasoning) | Out tok/s | $ / 1k calls | 429s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (r["latency_p50_s"] is None, r["latency_p50_s"] or 0)):
        tokens = f"{fmt(r['prompt_tokens_mean'])} / {fmt(r['completion_tokens_mean'])} ({fmt(r['reasoning_tokens_mean'])})"
        lines.append(
            f"| `{r['model']}` | {r['ok']}/{r['requests']} | {fmt(r['latency_p50_s'])} | {fmt(r['latency_p95_s'])} | "
            f"{fmt(r['json_schema_valid'], '%')} | {fmt(r['tool_call_success'], '%')} | {fmt(r['reasoning_by_default'])} | {tokens} | "
            f"{fmt(r['completion_tokens_per_s'])} | {fmt(r['est_usd_per_1k_calls'])} | {r['rate_limited']} |")
    chosen = picks(rows)
    if chosen:
        lines += ["", "## What the table says", ""] + [f"- {p}" for p in chosen]
    problems = [(r["model"], r["errors"], r["notes"]) for r in rows if r["errors"] or r["notes"]]
    if problems:
        lines += ["", "## Failures and notes", ""]
        for model, errors, notes in problems:
            bits = [f"{k} x{v}" for k, v in errors.items()] + notes
            lines.append(f"- `{model}`: " + "; ".join(bits))
    lines += ["", "## Method", "",
              "- Latency is wall-clock for the whole non-streaming request, successful calls only; retries (429 / 5xx, up to 2) are not included in it.",
              "- JSON-schema valid = the content parses with `json.loads` and validates against the facet schema without repair.",
              "- Tool call OK = exactly one call to `search_prior_art` whose arguments parse and satisfy the schema.",
              "- Reasons by default = at least half of the answers carried reasoning tokens, `reasoning_content`, or a `<think>` block although none was requested.",
              "- Cost uses Baseten's published per-token prices where we have them; cached-prefix discounts are not modelled.",
              "- `n` is capped at 1 on Baseten Model APIs, so every sample is a separate request.", ""]
    return "\n".join(lines)


async def catalog(client: httpx.AsyncClient, base_url: str, headers: dict[str, str]) -> set[str] | None:
    try:
        resp = await client.get(f"{base_url}/models", headers=headers)
        if resp.status_code == 401:
            raise SystemExit("ERROR: Baseten rejected the API key (401). It must be sent as a bearer token; check BASETEN_API_KEY.")
        if resp.status_code == 402:
            raise SystemExit("ERROR: Baseten returned 402 payment required: redeem the event credits (Billing and usage -> Redeem promo credits).")
        if resp.status_code != 200:
            return None
        return {m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)}
    except (httpx.HTTPError, ValueError):
        return None


async def run_bakeoff(models: list[str], *, base_url: str, api_key: str, n: int, concurrency: int, rpm: float, max_tokens: int,
                      timeout_s: float, tasks: list[str], extra: dict[str, Any], client: httpx.AsyncClient | None = None,
                      check_catalog: bool = True) -> tuple[list[dict[str, Any]], list[Call]]:
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout_s)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/chat/completions"
    try:
        skipped: list[str] = []
        if check_catalog:
            available = await catalog(client, base_url.rstrip("/"), headers)
            if available:
                skipped = [m for m in models if m not in available]
                models = [m for m in models if m in available]
                for m in skipped:
                    print(f"  skip {m}: not in the live catalog (GET /models)")
                if not models:
                    raise SystemExit("ERROR: none of the requested slugs are in the catalog. Available: " + ", ".join(sorted(available)))
        sem = asyncio.Semaphore(max(1, concurrency))
        limiter = RateLimiter(rpm)
        jobs = []
        for model in models:
            for task in tasks:
                for i in range(n):
                    body = body_for(task, model, IDEAS[i % len(IDEAS)], max_tokens, extra)
                    # one affinity key per model+task keeps related requests on one replica (better KV-cache hits)
                    jobs.append(one_call(client, url, {**headers, "x-session-affinity": f"bakeoff:{model}:{task}"}, body, task, sem, limiter))
        print(f"running {len(jobs)} requests ({len(models)} models x {len(tasks)} tasks x {n}) at <= {rpm:g} RPM, concurrency {concurrency}")
        calls: list[Call] = list(await asyncio.gather(*jobs))
    finally:
        if own:
            await client.aclose()
    rows = [summarise(m, [c for c in calls if c.model == m]) for m in models]
    rows += [{**summarise(m, []), "errors": {"not in catalog": 1}} for m in skipped]
    return rows, calls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS, help="candidate slugs (default: the design doc's role table)")
    ap.add_argument("-n", type=int, default=8, help="prompts per task per model")
    ap.add_argument("--tasks", nargs="+", default=["json", "tool"], choices=["json", "tool"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rpm", type=float, default=None, help="request rate cap (default LLM_RPM_LIMIT; unverified accounts: 15)")
    ap.add_argument("--max-tokens", type=int, default=700, help="generous on purpose: reasoning models spend tokens before answering")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--extra", default="{}", help="JSON merged into every request body, e.g. '{\"reasoning_effort\": \"low\"}'")
    ap.add_argument("--tag", default="", help="suffix for the output files, e.g. low-reasoning")
    ap.add_argument("--no-catalog-check", action="store_true")
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args(argv)

    settings = get_settings()
    if not settings.baseten_api_key:
        print("ERROR: BASETEN_API_KEY is empty. Put it in the repo-root .env (see .env.example), then re-run.\n"
              "       Key: https://app.baseten.co/settings/api_keys   Credits: Billing and usage -> Redeem promo credits.\n"
              "       Nothing was called.", file=sys.stderr)
        return 2
    try:
        extra = json.loads(args.extra)
        if not isinstance(extra, dict):
            raise ValueError("must be a JSON object")
    except ValueError as exc:
        print(f"ERROR: --extra is not a JSON object: {exc}", file=sys.stderr)
        return 2

    rpm = args.rpm or float(settings.llm_rpm_limit)
    rows, calls = asyncio.run(run_bakeoff(
        list(dict.fromkeys(args.models)), base_url=settings.baseten_base_url, api_key=settings.baseten_api_key, n=args.n,
        concurrency=args.concurrency, rpm=rpm, max_tokens=args.max_tokens, timeout_s=args.timeout, tasks=args.tasks, extra=extra,
        check_catalog=not args.no_catalog_check))

    now = dt.datetime.now(dt.timezone.utc)
    meta = {"generated_at": now.isoformat(timespec="seconds"), "base_url": settings.baseten_base_url, "n": args.n,
            "concurrency": args.concurrency, "rpm": rpm, "max_tokens": args.max_tokens, "tasks": args.tasks, "extra": extra}
    suffix = f"-{args.tag}" if args.tag else ""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "models": rows, "calls": [c.__dict__ for c in calls]}
    stamped = RESULTS_DIR / f"bakeoff-{now.strftime('%Y%m%dT%H%M%SZ')}{suffix}.json"
    stamped.write_text(json.dumps(payload, indent=2) + "\n")
    (RESULTS_DIR / f"latest{suffix}.json").write_text(json.dumps(payload, indent=2) + "\n")
    md_path = Path(args.out_md) if args.out_md else MD_PATH.with_name(f"baseten-bakeoff{suffix}.md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md = render_markdown(rows, meta)
    md_path.write_text(md)
    print("\n" + md)
    print(f"wrote {md_path}\nwrote {stamped}")
    return 0 if any(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
