"""Per-run budget. When it runs low the conductor degrades visibly (skips round 2, fewer mutations)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Budget:
    max_calls: int = 70
    max_tokens: int = 150_000
    max_seconds: float = 90.0
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    started: float = field(default_factory=time.monotonic)
    degraded: bool = False

    def charge(self, *, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0) -> None:
        self.calls += 1
        self.tokens += tokens_in + tokens_out
        self.cost_usd += cost_usd

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def fraction_used(self) -> float:
        return max(self.calls / self.max_calls, self.tokens / self.max_tokens, self.elapsed / self.max_seconds)

    def low(self, threshold: float = 0.75) -> bool:
        return self.fraction_used() >= threshold

    def exhausted(self) -> bool:
        return self.fraction_used() >= 1.0

    def snapshot(self) -> dict:
        return {"calls": self.calls, "tokens": self.tokens, "cost_usd": round(self.cost_usd, 5),
                "elapsed_s": round(self.elapsed, 1), "degraded": self.degraded}
