"""Single settings object for backend, ingest and scripts. Reads the repo-root .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
FIXTURES_DIR = BACKEND_DIR / "fixtures"
RUNS_DIR = BACKEND_DIR / "runs"
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Elastic
    es_url: str = ""
    es_api_key: str = ""
    kibana_url: str = ""
    es_embed_inference_id: str = ".jina-embeddings-v3"
    es_rerank_inference_id: str = ".jina-reranker-v3"
    es_index: str = "prior-art-v1"
    es_quarantine_index: str = "prior-art-quarantine"
    es_watches_index: str = "idea-watches-v1"
    es_alerts_index: str = "idea-alerts-v1"

    # LLM providers (OpenAI-compatible); router order is baseten -> openrouter
    baseten_api_key: str = ""
    baseten_base_url: str = "https://inference.baseten.co/v1"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_rpm_limit: int = 100
    llm_timeout_s: float = 25.0

    # GPTZero
    gptzero_api_key: str = ""
    gptzero_base_url: str = "https://api.gptzero.me"
    gptzero_mode: Literal["replay", "live"] = "replay"
    gptzero_interactive_word_cap: int = 120_000

    # Surprisal (a base model we deploy ourselves: shared Model APIs do not return prompt-token logprobs).
    # Powers retrieval-conditioned surprisal (AXIS 1, second instrument) and Fast-DetectGPT curvature (Voice).
    surprisal_base_url: str = ""
    surprisal_api_key: str = ""
    surprisal_model: str = "surprisal"
    surprisal_timeout_s: float = 20.0
    surprisal_max_chars: int = 6000  # pitch + neighbour context sent to the base model

    # Live sources
    github_token: str = ""
    exa_api_key: str = ""
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""

    # Actions
    slack_webhook_url: str = ""

    # App
    orchestrator: Literal["asyncio", "jiuwen"] = "asyncio"
    backend_port: int = 8000

    # Per-run budget (the conductor degrades visibly when exceeded)
    budget_max_calls: int = 70
    budget_max_tokens: int = 150_000
    budget_max_seconds: float = 180.0

    # Live-run admission: POST /api/runs is 429 while this many runs are still executing, and a finished run stays
    # in memory (re-scores, actions, late SSE clients) for this long before it is evicted and served from its JSONL.
    max_live_runs: int = 4
    run_retention_s: float = 600.0

    @property
    def has_elastic(self) -> bool:
        return bool(self.es_url and self.es_api_key)

    @property
    def has_browser(self) -> bool:
        return bool(self.browserbase_api_key)

    @property
    def has_web_search(self) -> bool:
        return bool(self.exa_api_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.baseten_api_key or self.openrouter_api_key)

    @property
    def has_surprisal(self) -> bool:
        return bool(self.surprisal_base_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
