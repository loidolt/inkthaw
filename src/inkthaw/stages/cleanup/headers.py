"""Rule: running-header/footer heuristic (fallback when the engine misses furniture).

Candidates are the first two and last two text blocks on each page. A candidate
is dropped when its normalized text (case-folded, digits folded) repeats on
many pages: either globally (book title on every verso) or densely within its
own span (a chapter title running through one chapter). The first occurrence
of a repeated string is kept when it is a heading, since that is the real
chapter title. Bare page numbers at page edges are always dropped.
"""

from __future__ import annotations

from collections import defaultdict

from inkthaw.config import Config
from inkthaw.ir import BlockKind, BookIR
from inkthaw.stages.cleanup.base import Change, short
from inkthaw.text import is_page_number, normalize_furniture

MAX_HEADER_CHARS = 80
_EDGE_KINDS = frozenset({BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.OTHER})


def edge_candidates(ir: BookIR) -> dict[int, list[int]]:
    """Block indices at the top/bottom edges of each page."""
    by_page: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(ir.blocks):
        if b.kind in _EDGE_KINDS and b.text.strip():
            by_page[b.page].append(i)
    out: dict[int, list[int]] = {}
    for page, idxs in by_page.items():
        out[page] = sorted(set(idxs[:2] + idxs[-2:]))
    return out


def repeated_keys(ir: BookIR, cfg: Config) -> set[str]:
    c = cfg.cleanup
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for page, idxs in edge_candidates(ir).items():
        for i in idxs:
            text = ir.blocks[i].text
            if len(text) > MAX_HEADER_CHARS:
                continue
            key = normalize_furniture(text)
            if key and key != "#":
                pages_by_key[key].add(page)
    n_pages = max(len(ir.pages), len({b.page for b in ir.blocks}), 1)
    out = set()
    for key, pages in pages_by_key.items():
        if len(pages) < c.running_header_min_pages:
            continue
        span = max(pages) - min(pages) + 1
        if (
            len(pages) / n_pages > c.running_header_threshold
            or len(pages) / span >= c.running_header_local_density
        ):
            out.add(key)
    return out


def drop_running_headers(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    repeated = repeated_keys(ir, cfg)
    drop: dict[int, str] = {}
    seen: set[str] = set()
    candidates = sorted(i for idxs in edge_candidates(ir).values() for i in idxs)
    for i in candidates:
        b = ir.blocks[i]
        if b.kind != BlockKind.HEADING and is_page_number(b.text):
            drop[i] = "page number at page edge"
            continue
        if len(b.text) > MAX_HEADER_CHARS:
            continue
        key = normalize_furniture(b.text)
        if key not in repeated:
            continue
        first = key not in seen
        seen.add(key)
        if first and b.kind == BlockKind.HEADING:
            continue
        drop[i] = f"repeated header '{short(b.text, 40)}'"

    changes = [
        Change("headers", "drop", ir.blocks[i].id, ir.blocks[i].page, why)
        for i, why in sorted(drop.items())
    ]
    kept = [b for i, b in enumerate(ir.blocks) if i not in drop]
    return ir.model_copy(update={"blocks": kept}), changes
