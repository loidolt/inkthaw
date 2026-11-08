"""Engine registry, backed by the `rebind.engines` entry-point group."""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

from rebind.engines.base import Capabilities, Engine, EngineContext
from rebind.errors import RebindError

GROUP = "rebind.engines"

__all__ = ["Capabilities", "Engine", "EngineContext", "get_engine", "list_engines"]


def _entry_points() -> dict[str, EntryPoint]:
    return {ep.name: ep for ep in entry_points(group=GROUP)}


def list_engines() -> dict[str, EntryPoint]:
    return _entry_points()


def get_engine(name: str) -> Engine:
    eps = _entry_points()
    if name not in eps:
        known = ", ".join(sorted(eps)) or "none"
        raise RebindError(f"Unknown engine '{name}'. Installed engines: {known}")
    try:
        cls = eps[name].load()
    except Exception as e:
        raise RebindError(f"Failed to load engine '{name}': {e}") from e
    engine = cls()
    ok, reason = engine.available()
    if not ok:
        raise RebindError(f"Engine '{name}' is not usable: {reason}")
    return engine
