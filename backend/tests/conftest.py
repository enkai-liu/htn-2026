"""A developer's .env carries real keys. No test may reach a model because of them: a test that wants a model installs a fake router."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.llm import router as router_mod


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "baseten_api_key", "")
    monkeypatch.setattr(s, "openrouter_api_key", "")
    monkeypatch.setattr(router_mod, "_router", None)
