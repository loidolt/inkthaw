"""Rule: drop page furniture (running headers, footers, page numbers)."""

from __future__ import annotations

from inkthaw.config import Config
from inkthaw.ir import FURNITURE_KINDS, BookIR
from inkthaw.stages.cleanup.base import Change


def drop_furniture(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    kept = []
    changes: list[Change] = []
    for b in ir.blocks:
        if b.kind in FURNITURE_KINDS:
            changes.append(Change("furniture", "drop", b.id, b.page, f"{b.kind}: {b.text[:60]}"))
        else:
            kept.append(b)
    return ir.model_copy(update={"blocks": kept}), changes
