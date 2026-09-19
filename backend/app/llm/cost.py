"""USD per million tokens (input, output). From Baseten's pricing page on 2026-09-19; unknowns use DEFAULT.

Keys are the slug constants from `models.py`: a renamed model cannot silently fall back to the placeholder price.
"""
from __future__ import annotations

from .models import DS_FLASH, DS_FLASH_41, GLM, GLM_FLASH, KIMI

PRICES: dict[str, tuple[float, float]] = {
    GLM: (1.40, 4.40),
    GLM_FLASH: (0.15, 0.50),
    DS_FLASH_41: (0.30, 1.20),
    DS_FLASH: (0.13, 0.26),
    KIMI: (3.00, 15.00),
}
DEFAULT = (0.60, 2.40)  # placeholder for slugs we have no verified price for; marked estimated in the UI


def estimate(model: str, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
    """Returns (usd, is_estimated)."""
    pin, pout = PRICES.get(model, DEFAULT)
    return (tokens_in * pin + tokens_out * pout) / 1_000_000, model not in PRICES
