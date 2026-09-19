"""Role registry. Roles are created lazily per run, which is what makes dynamic team formation cheap."""
from __future__ import annotations

from collections.abc import Callable

from .host import Role

_FACTORIES: dict[str, Callable[[], Role]] = {}


def register(role_id: str) -> Callable[[Callable[[], Role]], Callable[[], Role]]:
    def deco(factory: Callable[[], Role]) -> Callable[[], Role]:
        _FACTORIES[role_id] = factory
        return factory

    return deco


def create(role_id: str) -> Role:
    if role_id not in _FACTORIES:
        raise KeyError(f"no role registered as {role_id!r}; known: {sorted(_FACTORIES)}")
    return _FACTORIES[role_id]()


def known_roles() -> list[str]:
    return sorted(_FACTORIES)
