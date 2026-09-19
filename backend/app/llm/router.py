"""LLM router: Baseten first, OpenRouter as automatic fallback. Every call reports who served it and what it cost.

- OpenAI-compatible on both sides, so one client class.
- Global token bucket under the provider RPM limit.
- `x-session-affinity` keeps a role's calls on one replica (better KV-cache hits on Baseten).
- Shared instructions go FIRST in the prompt so automatic prefix caching can reuse them.
- Structured output degrades per provider: json_schema -> json_object -> plain prompt. Not every model behind
  either provider accepts `json_schema`, and a 400 for that must not burn the provider.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from json_repair import repair_json
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.core.budget import Budget

from . import cost
from .models import model_for, openrouter_model

T = TypeVar("T", bound=BaseModel)

RETRY_BACKOFF_S = 0.6
_FORMAT_REJECTED = re.compile(r"response_format|json_schema|json_object|structured output|schema|format", re.I)


def _degrade_format(fmt: dict | None) -> dict | None:
    """json_schema -> json_object -> None. `structured()` already asks for a bare JSON object in the prompt."""
    if fmt is None:
        return None
    return {"type": "json_object"} if fmt.get("type") == "json_schema" else None


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cost_estimated: bool = False
    raw: Any = None

    def meta(self) -> dict:
        """Keyword args for ctx.emit(...)."""
        return {"model": self.model, "provider": self.provider, "latency_ms": self.latency_ms,
                "tokens": {"in": self.tokens_in, "out": self.tokens_out}, "cost_usd": round(self.cost_usd, 6)}


class TokenBucket:
    def __init__(self, per_minute: int) -> None:
        self.capacity = max(per_minute, 1)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 60.0
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class LLMRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self.providers: list[tuple[str, AsyncOpenAI]] = []
        if s.baseten_api_key:
            self.providers.append(("baseten", AsyncOpenAI(api_key=s.baseten_api_key, base_url=s.baseten_base_url,
                                                          timeout=s.llm_timeout_s, max_retries=0)))
        if s.openrouter_api_key:
            self.providers.append(("openrouter", AsyncOpenAI(api_key=s.openrouter_api_key, base_url=s.openrouter_base_url,
                                                             timeout=s.llm_timeout_s, max_retries=0)))
        self.bucket = TokenBucket(s.llm_rpm_limit)

    @property
    def available(self) -> bool:
        return bool(self.providers)

    async def chat(self, *, role: str, messages: list[dict], model: str | None = None, temperature: float = 0.2,
                   max_tokens: int = 1500, response_format: dict | None = None, tools: list[dict] | None = None,
                   session: str | None = None, budget: Budget | None = None) -> LLMResult:
        if not self.providers:
            raise LLMUnavailable("no LLM provider configured: set BASETEN_API_KEY or OPENROUTER_API_KEY in .env")
        wanted = model or model_for(role)
        failures: list[str] = []
        for name, client in self.providers:
            slug = wanted if name == "baseten" else openrouter_model(wanted)
            headers = {"x-session-affinity": session} if (session and name == "baseten") else None
            fmt = response_format
            attempt = 0
            while attempt < 2:  # one retry per provider on 429 / 5xx / timeout, then fall through to the next
                await self.bucket.take()
                started = time.monotonic()
                kwargs: dict[str, Any] = {"model": slug, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
                if fmt:
                    kwargs["response_format"] = fmt
                if tools:
                    kwargs["tools"] = tools
                try:
                    resp = await client.chat.completions.create(**kwargs, extra_headers=headers)
                except (APITimeoutError, APIConnectionError) as exc:
                    failures.append(f"{name}: {type(exc).__name__}")
                except APIStatusError as exc:
                    failures.append(f"{name}: HTTP {exc.status_code} {str(exc)[:120]}")
                    if fmt and exc.status_code == 400 and _FORMAT_REJECTED.search(str(exc)):
                        fmt = _degrade_format(fmt)  # same provider, weaker format; not counted as an attempt
                        continue
                    if exc.status_code not in (408, 409, 429) and exc.status_code < 500:
                        break  # 4xx that a retry won't fix: go to the next provider
                else:
                    usage = resp.usage
                    tin, tout = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
                    usd, estimated = cost.estimate(slug, tin, tout)
                    if budget is not None:
                        budget.charge(tokens_in=tin, tokens_out=tout, cost_usd=usd)
                    return LLMResult(text=resp.choices[0].message.content or "", model=slug, provider=name,
                                     latency_ms=int((time.monotonic() - started) * 1000), tokens_in=tin,
                                     tokens_out=tout, cost_usd=usd, cost_estimated=estimated, raw=resp)
                attempt += 1
                if attempt < 2:
                    await asyncio.sleep(RETRY_BACKOFF_S * attempt)
        raise LLMUnavailable(f"all providers failed for {wanted}: " + "; ".join(failures))

    async def structured(self, *, role: str, system: str, user: str, schema: type[T], model: str | None = None,
                         temperature: float = 0.2, max_tokens: int = 2000, session: str | None = None,
                         budget: Budget | None = None) -> tuple[T, LLMResult]:
        """JSON-schema constrained call -> validated pydantic object. Repairs, then re-asks once with the error."""
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": False}}
        messages = [{"role": "system", "content": system + "\nReply with a single JSON object and nothing else."},
                    {"role": "user", "content": user}]
        problem = ""
        for _ in range(2):
            res = await self.chat(role=role, messages=messages, model=model, temperature=temperature,
                                  max_tokens=max_tokens, response_format=fmt, session=session, budget=budget)
            try:
                return schema.model_validate(_loads(res.text)), res
            except (ValidationError, ValueError) as exc:
                problem = str(exc)[:600]
                messages = messages + [{"role": "assistant", "content": res.text[:4000]},
                                       {"role": "user", "content": f"That did not validate: {problem}\nReturn corrected JSON only."}]
        raise LLMUnavailable(f"{role}: model could not produce valid {schema.__name__}: {problem}")


def _loads(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("\n") + 1:] if "\n" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fixed = repair_json(text, return_objects=True)
        if fixed in ("", None):
            raise ValueError("no JSON found in model output") from None
        return fixed


_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
