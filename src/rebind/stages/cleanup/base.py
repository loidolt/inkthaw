"""Shared types for cleanup rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rebind.config import Config
from rebind.ir import BlockKind, BookIR


@dataclass(frozen=True)
class Change:
    rule: str
    action: str  # drop | merge | edit | split | link
    block_id: str
    page: int
    detail: str = ""


RuleFn = Callable[[BookIR, Config], tuple[BookIR, list[Change]]]


@dataclass(frozen=True)
class Rule:
    name: str
    fn: RuleFn
    enabled: Callable[[Config], bool]


TEXT_KINDS = frozenset(
    {
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.FOOTNOTE,
        BlockKind.CAPTION,
        BlockKind.OTHER,
    }
)
"""Kinds whose `text` is running prose that text rules may rewrite."""


def short(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"
