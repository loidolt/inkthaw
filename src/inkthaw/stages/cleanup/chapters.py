"""Rule: make headings describe the book's real chapter structure.

1. Promote short "Chapter 4" / "CHAPTER IV." / "BOOK TWO" paragraphs to headings.
2. Demote headings that are really prose the layout model over-labelled:
   letter salutations and sign-offs ('"Your friend,', 'HASTIE LANYON.'),
   anything long or ending in , ; or a sentence period.
3. Merge runs of headings on one page (a title split over lines). When the
   run is followed by body text, its last heading stays separate: that is the
   chapter title under a book or part title.
4. Shift heading levels so the top level is 1 (the EPUB splits chapters there).
"""

from __future__ import annotations

import re

from inkthaw.config import Config
from inkthaw.ir import Block, BlockKind, BookIR
from inkthaw.stages.cleanup.base import Change, short
from inkthaw.text import CHAPTER_RE

MAX_HEADING_CHARS = 120
_BARE_NUMBER = re.compile(r"^\s*([ivxlcdm]+|\d+)\.?\s*$", re.IGNORECASE)
_QUOTE_START = tuple("\"'“‘«„(")
CONNECTOR_MAX_WORDS = 3


def is_chapter_label(text: str) -> bool:
    return bool(CHAPTER_RE.match(text) or _BARE_NUMBER.match(text))


def looks_like_prose(text: str) -> bool:
    t = text.strip()
    if is_chapter_label(t):
        return False
    return (
        len(t) > MAX_HEADING_CHARS
        or t.startswith(_QUOTE_START)
        or t.endswith((",", ";"))
        or (t.endswith(".") and not t.endswith(("..", "…")))
    )


def _promote_and_demote(blocks: list[Block], changes: list[Change]) -> list[Block]:
    top = min((b.level or 1 for b in blocks if b.kind == BlockKind.HEADING), default=1)
    out = []
    for b in blocks:
        if (
            b.kind in (BlockKind.PARAGRAPH, BlockKind.OTHER)
            and len(b.text) <= 80
            and (CHAPTER_RE.match(b.text))
        ):
            b = b.model_copy(
                update={
                    "kind": BlockKind.HEADING,
                    "level": top,
                    "attrs": {**b.attrs, "promoted": True},
                }
            )
            changes.append(Change("chapters", "promote", b.id, b.page, short(b.text, 40)))
        elif b.kind == BlockKind.HEADING and looks_like_prose(b.text):
            b = b.model_copy(
                update={
                    "kind": BlockKind.PARAGRAPH,
                    "level": None,
                    "attrs": {**b.attrs, "demoted_heading": True},
                }
            )
            changes.append(Change("chapters", "demote", b.id, b.page, short(b.text, 40)))
        out.append(b)
    return out


def _is_connector(b: Block) -> bool:
    return (
        b.kind in (BlockKind.PARAGRAPH, BlockKind.OTHER)
        and 0 < len(b.text.split()) <= CONNECTOR_MAX_WORDS
        and not b.text.rstrip().endswith((".", "!", "?"))
    )


def _merge_heading_runs(blocks: list[Block], changes: list[Change]) -> list[Block]:
    out: list[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind != BlockKind.HEADING:
            out.append(b)
            i += 1
            continue
        # Collect a run: headings on one page, optionally joined by short connectors.
        run = [i]
        j = i + 1
        while j < len(blocks) and blocks[j].page == b.page:
            nb = blocks[j]
            if nb.kind == BlockKind.HEADING or (
                _is_connector(nb)
                and j + 1 < len(blocks)
                and blocks[j + 1].kind == BlockKind.HEADING
                and blocks[j + 1].page == b.page
            ):
                run.append(j)
                j += 1
            else:
                break
        headings = [k for k in run if blocks[k].kind == BlockKind.HEADING]
        if len(headings) < 2:
            out.extend(blocks[k] for k in run)
            i = j
            continue
        followed_by_body = j < len(blocks) and blocks[j].kind == BlockKind.PARAGRAPH
        tail = [run[-1]] if followed_by_body else []
        head = [k for k in run if k not in tail]
        if len([k for k in head if blocks[k].kind == BlockKind.HEADING]) >= 1 and len(head) > 1:
            first = blocks[head[0]]
            text = " ".join(blocks[k].text.strip() for k in head)
            level = min(blocks[k].level or 1 for k in head if blocks[k].kind == BlockKind.HEADING)
            merged = first.model_copy(
                update={
                    "kind": BlockKind.HEADING,
                    "level": level,
                    "text": text,
                    "attrs": {**first.attrs, "merged_from": [blocks[k].id for k in head[1:]]},
                }
            )
            changes.append(Change("chapters", "merge", first.id, first.page, short(text, 50)))
            out.append(merged)
        else:
            out.extend(blocks[k] for k in head)
        out.extend(blocks[k] for k in tail)
        i = j
    return out


def _normalize_levels(blocks: list[Block], changes: list[Change]) -> list[Block]:
    levels = [b.level or 1 for b in blocks if b.kind == BlockKind.HEADING]
    if not levels or min(levels) == 1:
        return blocks
    shift = min(levels) - 1
    changes.append(Change("chapters", "edit", "*", -1, f"heading levels shifted up by {shift}"))
    return [
        b.model_copy(update={"level": (b.level or 1) - shift}) if b.kind == BlockKind.HEADING else b
        for b in blocks
    ]


def structure_chapters(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    changes: list[Change] = []
    blocks = _promote_and_demote(list(ir.blocks), changes)
    blocks = _merge_heading_runs(blocks, changes)
    blocks = _normalize_levels(blocks, changes)
    return ir.model_copy(update={"blocks": blocks}), changes
