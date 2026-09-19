"""Which model serves which role. Starting points only: baseten/bakeoff.py decides, then edit this table.

Right-sizing is part of the Baseten story: cheap fast models for high-volume roles, strong ones where
judgement matters, and different model FAMILIES for critic vs advocate vs jurors so they don't share blind spots.
"""
from __future__ import annotations

GLM = "zai-org/GLM-5.3"
GLM_FLASH = "zai-org/GLM-5.3-Flash"
DS_PRO = "deepseek-ai/DeepSeek-V4-Pro"
DS_FLASH = "deepseek-ai/DeepSeek-V4-Flash-0731"
DS_FLASH_41 = "deepseek-ai/DeepSeek-V4.1-Flash"
KIMI = "moonshotai/Kimi-K2.6"
GPT_OSS = "openai/gpt-oss-120b"

ROLE_MODELS: dict[str, str] = {
    "conductor": GLM_FLASH,
    "scout": DS_FLASH,
    "resolver": DS_FLASH,
    # DS_PRO ignores json_schema on Baseten (returns a different shape even with strict=true); Kimi honours it and is
    # still a different family from the advocate (GLM).
    "critic": KIMI,
    "advocate": GLM,
    "synthesizer": GLM,
    "mutator": KIMI,
    "actuator": GLM_FLASH,
}

# Jury and LLM-predictability sample across families; `n` is capped at 1 on Baseten so these are separate requests.
# DS_FLASH_41 ignores json_schema on Baseten like DS_PRO, so it was dropped from every jury; DS_FLASH keeps DeepSeek on it.
JURY_MODELS: list[str] = [GLM_FLASH, DS_FLASH, GPT_OSS]
PRIOR_MODELS: list[str] = [GLM_FLASH, DS_FLASH, GPT_OSS, KIMI]

# OpenRouter fallback. gpt-oss-120b has the same slug on both providers; everything else maps to it until the
# team confirms real OpenRouter slugs (scripts/smoke_baseten.sh prints what the key can see).
OPENROUTER_EQUIVALENT: dict[str, str] = {GPT_OSS: GPT_OSS}
OPENROUTER_DEFAULT = GPT_OSS


def model_for(role_id: str) -> str:
    base = role_id.split(".")[0]
    return ROLE_MODELS.get(role_id) or ROLE_MODELS.get(base) or GLM_FLASH


def openrouter_model(baseten_slug: str) -> str:
    return OPENROUTER_EQUIVALENT.get(baseten_slug, OPENROUTER_DEFAULT)
