"""Engine protocol. Engines turn page images into BookIR."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from rebind.config import Config
from rebind.ir import BookIR, Page


@dataclass(frozen=True)
class Capabilities:
    layout: bool = True
    tables: bool = False
    pictures: bool = False
    footnotes: bool = False
    page_furniture: bool = False
    """Engine labels running headers/footers itself."""
    confidence: bool = False
    devices: tuple[str, ...] = ("cpu",)


@dataclass
class EngineContext:
    job_root: Path
    """Page image paths are relative to this directory."""
    work_dir: Path
    """Engine may write here (per-page cache, extracted images)."""
    advance: Callable[[], None] = lambda: None
    warn: Callable[[str], None] = lambda _msg: None
    log: Callable[[str], None] = lambda _msg: None
    extras: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class Engine(Protocol):
    name: str

    @property
    def version(self) -> str: ...

    @property
    def capabilities(self) -> Capabilities: ...

    def available(self) -> tuple[bool, str]:
        """(usable, reason). Must not load heavy models."""
        ...

    def settings_key(self, cfg: Config) -> str:
        """String that changes whenever output-affecting settings change."""
        ...

    def convert(self, pages: list[Page], cfg: Config, ctx: EngineContext) -> BookIR:
        """OCR + layout for the given pages. Must call ctx.advance() once per page."""
        ...
