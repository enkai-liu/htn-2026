"""USD per million tokens (input, output). From Baseten's pricing page on 2026-09-19; unknowns use DEFAULT."""
from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "zai-org/GLM-5.3": (1.40, 4.40),
    "zai-org/GLM-5.3-Flash": (0.15, 0.50),
    "deepseek-ai/DeepSeek-V4.1-Flash": (0.30, 1.20),
    "deepseek-ai/DeepSeek-V4-Flash-0731": (0.13, 0.26),
    "moonshotai/Kimi-K3": (3.00, 15.00),
}
DEFAULT = (0.60, 2.40)  # placeholder for slugs we have no verified price for; marked estimated in the UI


def estimate(model: str, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
    """Returns (usd, is_estimated)."""
    pin, pout = PRICES.get(model, DEFAULT)
    return (tokens_in * pin + tokens_out * pout) / 1_000_000, model not in PRICES
