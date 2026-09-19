"""Source-reliability priors used when sources disagree. Conflicts are resolved by these AND shown to the user."""
from __future__ import annotations

# How much we trust each source for each fused field (0..1).
PRIORS: dict[str, dict[str, float]] = {
    "status": {"github": 0.8, "yc": 0.9, "web": 0.85, "hn": 0.5, "devpost": 0.6, "arxiv": 0.5},
    "last_activity": {"github": 0.95, "hn": 0.8, "yc": 0.7, "devpost": 0.6, "web": 0.6, "arxiv": 0.7},
    "year": {"github": 0.9, "hn": 0.9, "arxiv": 0.9, "yc": 0.7, "devpost": 0.6, "web": 0.4},
    "tech": {"github": 0.9, "devpost": 0.8, "yc": 0.4, "hn": 0.3, "web": 0.4, "arxiv": 0.3},
}
RULES: dict[str, str] = {
    "status": "repository activity and YC status outrank self-reported Devpost copy",
    "last_activity": "github.pushed_at outranks everything else",
    "year": "first-party timestamps outrank hackathon year",
}


def reliability(field: str, source: str) -> float:
    return PRIORS.get(field, {}).get(source, 0.5)
