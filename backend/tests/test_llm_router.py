"""The router's first contact with real providers: fallback, structured-output degradation, repair, cost attribution.

Drives `LLMRouter.chat` / `structured` with a scripted OpenAI-compatible client so the code between a provider
error and a validated pydantic object actually runs (the pipeline tests replace `structured` wholesale).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, APITimeoutError
from pydantic import BaseModel

from app.config import Settings
from app.llm import router as router_mod
from app.llm.models import GLM_FLASH, GPT_OSS
from app.llm.router import LLMRouter, LLMUnavailable
from app.roles.judge import Ballot

JSON_SCHEMA_FMT = {"type": "json_schema", "json_schema": {"name": "X", "schema": {"type": "object"}, "strict": False}}


class _Completions:
    def __init__(self, script: list) -> None:
        self.script, self.calls = list(script), []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    """Each entry in `script` is returned (or raised) by successive `chat.completions.create` calls."""

    def __init__(self, *script) -> None:
        self.chat = SimpleNamespace(completions=_Completions(list(script)))

    @property
    def calls(self) -> list[dict]:
        return self.chat.completions.calls


def reply(text: str, *, tokens=(10, 5)):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                           usage=SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1]))


def status(code: int, message: str = "boom") -> APIStatusError:
    req = httpx.Request("POST", "https://provider.test/v1/chat/completions")
    return APIStatusError(message, response=httpx.Response(code, request=req), body=None)


def timeout() -> APITimeoutError:
    return APITimeoutError(request=httpx.Request("POST", "https://provider.test/v1/chat/completions"))


@pytest.fixture
def make_router(monkeypatch):
    monkeypatch.setattr(router_mod, "RETRY_BACKOFF_S", 0)

    def build(baseten: FakeClient | None, openrouter: FakeClient | None) -> LLMRouter:
        r = LLMRouter(Settings(_env_file=None, baseten_api_key="b", openrouter_api_key="o", llm_rpm_limit=10_000))
        r.providers = [(n, c) for n, c in (("baseten", baseten), ("openrouter", openrouter)) if c is not None]
        return r

    return build


class Answer(BaseModel):
    verdict: str
    score: float


# -- fallback ------------------------------------------------------------------------------------------------------

async def test_429_is_retried_once_then_falls_through_to_the_next_provider(make_router):
    bt, orr = FakeClient(status(429), status(429)), FakeClient(reply("ok"))
    res = await make_router(bt, orr).chat(role="critic", messages=[{"role": "user", "content": "hi"}])
    assert (res.provider, res.text) == ("openrouter", "ok")
    assert len(bt.calls) == 2 and len(orr.calls) == 1


async def test_timeout_counts_as_a_retryable_failure(make_router):
    bt = FakeClient(timeout(), reply("second time lucky"))
    res = await make_router(bt, None).chat(role="critic", messages=[])
    assert (res.provider, res.text) == ("baseten", "second time lucky")


async def test_unfixable_4xx_switches_provider_without_a_retry(make_router):
    bt, orr = FakeClient(status(404, "model not found")), FakeClient(reply("ok"))
    res = await make_router(bt, orr).chat(role="critic", messages=[])
    assert res.provider == "openrouter"
    assert len(bt.calls) == 1


async def test_every_provider_failing_names_each_failure(make_router):
    with pytest.raises(LLMUnavailable, match=r"baseten: HTTP 429.*openrouter: APITimeoutError"):
        await make_router(FakeClient(status(429), status(429)), FakeClient(timeout(), timeout())).chat(role="critic", messages=[])


async def test_fallback_slug_is_priced_as_served_not_as_requested(make_router):
    """GLM-Flash has a price; the OpenRouter fallback serves gpt-oss instead, which does not -> estimated."""
    res = await make_router(FakeClient(status(503), status(503)), FakeClient(reply("ok"))).chat(role="critic", messages=[], model=GLM_FLASH)
    assert (res.model, res.provider) == (GPT_OSS, "openrouter")
    assert res.cost_estimated is True


# -- response_format degradation -------------------------------------------------------------------------------------

async def test_rejected_json_schema_degrades_to_json_object_then_plain_on_the_same_provider(make_router):
    bt = FakeClient(status(400, "response_format json_schema is not supported by this model"),
                    status(400, "response_format.type must be text"),
                    reply('{"a": 1}'))
    res = await make_router(bt, FakeClient(reply("never"))).chat(role="critic", messages=[], response_format=JSON_SCHEMA_FMT)
    assert res.provider == "baseten"
    assert [c.get("response_format") for c in bt.calls] == [JSON_SCHEMA_FMT, {"type": "json_object"}, None]


async def test_a_400_unrelated_to_the_format_does_not_burn_extra_calls(make_router):
    bt, orr = FakeClient(status(400, "context length exceeded")), FakeClient(reply("ok"))
    await make_router(bt, orr).chat(role="critic", messages=[], response_format=JSON_SCHEMA_FMT)
    assert len(bt.calls) == 1


# -- structured() ----------------------------------------------------------------------------------------------------

async def test_structured_accepts_fenced_json(make_router):
    bt = FakeClient(reply('```json\n{"verdict": "same", "score": 0.9}\n```'))
    obj, res = await make_router(bt, None).structured(role="resolver", system="s", user="u", schema=Answer)
    assert (obj.verdict, obj.score) == ("same", 0.9)
    assert len(bt.calls) == 1


async def test_structured_reasks_once_with_the_validation_error(make_router):
    bt = FakeClient(reply('{"verdict": "same"}'), reply('{"verdict": "same", "score": 0.4}'))
    obj, _ = await make_router(bt, None).structured(role="resolver", system="s", user="u", schema=Answer)
    assert obj.score == 0.4
    followup = bt.calls[1]["messages"]
    assert followup[-2]["role"] == "assistant" and "did not validate" in followup[-1]["content"] and "score" in followup[-1]["content"]


async def test_structured_gives_up_after_the_reask(make_router):
    bt = FakeClient(reply("not json at all"), reply("still not json"))
    with pytest.raises(LLMUnavailable, match="could not produce valid Answer"):
        await make_router(bt, None).structured(role="resolver", system="s", user="u", schema=Answer)


async def test_long_free_text_is_clipped_not_rejected(make_router):
    """A chatty juror used to be a ValidationError, a re-ask and then a dropped vote. Now it is one call and a trimmed `why`."""
    ballot = {"overlaps": [{"entity": 0, "purpose": 0.7, "mechanism": 0.2, "why": "because " * 100}]}
    bt = FakeClient(reply(json.dumps(ballot)))
    obj, _ = await make_router(bt, None).structured(role="judge", system="s", user="u", schema=Ballot)
    assert len(obj.overlaps[0].why) == 200 and obj.overlaps[0].purpose == 0.7
    assert len(bt.calls) == 1
