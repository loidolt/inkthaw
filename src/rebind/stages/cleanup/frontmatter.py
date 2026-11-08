"""Rule: front matter (title page, copyright page, scanned table of contents).

The body starts at the first "substantive" heading: one followed by real prose
before the next heading. Everything before it, within the first pages of the
book, is front matter: its headings are demoted (so title-page lines do not
become EPUB chapters) and blocks are tagged `front_matter` / `copyright`.
Scanned contents pages are dropped by default: the EPUB has its own TOC.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from rebind.config import Config
from rebind.ir import Block, BlockKind, BookIR
from rebind.stages.cleanup.base import Change, short

SUBSTANTIVE_CHARS = 400
PROSE_LINE_CHARS = 80
"""Only paragraphs at least this long count as prose (TOC entries are short)."""
_CONTENTS_RE = re.compile(
    r"^\s*(table\s+of\s+)?contents\.?\s*$|^\s*(inhalt|inhaltsverzeichnis|sommaire|"
    r"table\s+des\s+mati[eè]res|índice|indice|inhoud)\.?\s*$",
    re.IGNORECASE,
)
_ENDS_WITH_PAGE = re.compile(r"(\s|\.)(\d{1,4}|[ivxlcdm]{1,6})\s*$", re.IGNORECASE)
_COPYRIGHT_RE = re.compile(
    r"©|\(c\)\s*\d{4}|\bcopyright\b|all rights reserved|printed in|first published|"
    r"\bisbn\b|library of congress",
    re.IGNORECASE,
)


def body_start(blocks: list[Block], skip_pages: set[int] | None = None) -> int | None:
    """Index of the first heading followed by substantial prose."""
    skip_pages = skip_pages or set()
    for i, b in enumerate(blocks):
        if b.kind != BlockKind.HEADING or b.page in skip_pages:
            continue
        chars = 0
        for nb in blocks[i + 1 :]:
            if nb.kind == BlockKind.HEADING:
                break
            if nb.kind == BlockKind.PARAGRAPH and len(nb.text) >= PROSE_LINE_CHARS:
                chars += len(nb.text)
                if chars >= SUBSTANTIVE_CHARS:
                    return i
    return None


def toc_pages(blocks: list[Block], limit_page: int) -> set[int]:
    by_page: dict[int, list[Block]] = defaultdict(list)
    for b in blocks:
        if b.page < limit_page:
            by_page[b.page].append(b)

    def numbered_lines(page: int) -> bool:
        texts = [b for b in by_page.get(page, []) if b.text.strip()]
        if any(b.attrs.get("label") == "document_index" for b in by_page.get(page, [])):
            return True
        if len(texts) < 3:
            return False
        hits = sum(
            1 for b in texts if _ENDS_WITH_PAGE.search(" " + b.text) or b.text.strip() == "PAGE"
        )
        return hits / len(texts) >= 0.5

    pages: set[int] = set()
    for page in sorted(by_page):
        has_title = any(_CONTENTS_RE.match(b.text) for b in by_page[page])
        if (
            has_title
            or (pages and page - 1 in pages and numbered_lines(page))
            or any(b.attrs.get("label") == "document_index" for b in by_page[page])
        ):
            pages.add(page)
    return pages


def mark_front_matter(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    c = cfg.cleanup
    n_pages = max(len(ir.pages), (max((b.page for b in ir.blocks), default=0) + 1))
    limit = max(4, min(c.front_matter_max_pages, math.ceil(c.front_matter_max_fraction * n_pages)))
    blocks = list(ir.blocks)
    changes: list[Change] = []

    contents = toc_pages(blocks, limit)
    start = body_start(blocks, contents)
    if start is not None and blocks[start].page >= limit:
        start = None  # body starts too late to trust; only handle TOC pages

    drop_pages = contents if c.drop_scanned_toc else set()
    out: list[Block] = []
    for i, b in enumerate(blocks):
        in_front = start is not None and i < start
        if b.page in drop_pages and (start is None or i < start):
            changes.append(
                Change("front_matter", "drop", b.id, b.page, f"contents: {short(b.text, 40)}")
            )
            continue
        if in_front:
            role = "copyright" if _COPYRIGHT_RE.search(b.text) else "front_matter"
            update: dict = {"attrs": {**b.attrs, "role": role}}
            if b.kind == BlockKind.HEADING:
                update.update(kind=BlockKind.PARAGRAPH, level=None)
                changes.append(Change("front_matter", "demote", b.id, b.page, short(b.text, 40)))
            b = b.model_copy(update=update)
        out.append(b)
    return ir.model_copy(update={"blocks": out}), changes
