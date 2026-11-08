"""Rule: repair reading order on single-column pages.

Layout models sometimes emit a page's paragraphs out of order (seen with
Docling when two paragraph boxes overlap slightly). On a page where no two
blocks sit side by side, top-to-bottom order is the reading order, so blocks
are sorted by their top edge. Pages with side-by-side blocks (columns, a
figure beside its caption) keep the engine's order. Pages where any block
lacks a bounding box are left alone.
"""

from __future__ import annotations

from itertools import groupby

from inkthaw.config import Config
from inkthaw.ir import Block, BookIR
from inkthaw.stages.cleanup.base import Change, short

SIDE_BY_SIDE_OVERLAP = 0.5
"""Two blocks are side by side if their vertical extents overlap by more than
this share of the shorter one and their horizontal extents do not overlap."""


def _side_by_side(a: Block, b: Block) -> bool:
    assert a.bbox and b.bbox
    ax0, ay0, ax1, ay1 = a.bbox
    bx0, by0, bx1, by1 = b.bbox
    v_overlap = min(ay1, by1) - max(ay0, by0)
    shorter = max(1.0, min(ay1 - ay0, by1 - by0))
    h_overlap = min(ax1, bx1) - max(ax0, bx0)
    return v_overlap / shorter > SIDE_BY_SIDE_OVERLAP and h_overlap <= 0


def is_single_column(blocks: list[Block]) -> bool:
    return not any(_side_by_side(a, b) for i, a in enumerate(blocks) for b in blocks[i + 1 :])


def fix_reading_order(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    out: list[Block] = []
    changes: list[Change] = []
    for page, group_iter in groupby(ir.blocks, key=lambda b: b.page):
        group = list(group_iter)
        if len(group) < 2 or any(b.bbox is None for b in group) or not is_single_column(group):
            out.extend(group)
            continue
        ordered = sorted(group, key=lambda b: (b.bbox[1], b.bbox[0]))  # type: ignore[index]
        if [b.id for b in ordered] != [b.id for b in group]:
            moved = next(b for b, o in zip(group, ordered, strict=True) if b.id != o.id)
            changes.append(
                Change(
                    "reading_order",
                    "edit",
                    moved.id,
                    page,
                    f"reordered page top-to-bottom ({short(moved.text, 30)!r} moved)",
                )
            )
        out.extend(ordered)
    return ir.model_copy(update={"blocks": out}), changes
