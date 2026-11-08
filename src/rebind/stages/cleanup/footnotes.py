"""Rule: link footnote markers in the text to footnote blocks.

A footnote block starts with its marker ("1 ", "* ", "†", "¹"). The marker is
looked up in the prose blocks of the same page (including paragraphs merged
across pages). A match is stored as `attrs["noterefs"]` on the prose block
({start, end, note}); the build stage turns it into an EPUB 3 noteref and the
footnote into the note body. Unmatched footnotes stay as plain footnote text
and are reported. A footnote block without a marker continues the previous
footnote (a note running over a page break).
"""

from __future__ import annotations

import re
from typing import Any

from rebind.config import Config
from rebind.ir import Block, BlockKind, BookIR
from rebind.stages.cleanup.base import Change, short

SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_TO_SUPER = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_NOTE_START = re.compile(r"^\s*(\d{1,3}|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,3}|[*†‡§¶]{1,3})[.)]?\s*(?=\S)")
_PROSE = frozenset({BlockKind.PARAGRAPH, BlockKind.LIST_ITEM, BlockKind.CAPTION, BlockKind.OTHER})


def split_marker(text: str) -> tuple[str, str] | None:
    """('1', 'Note text') for '1. Note text'; None if no marker."""
    m = _NOTE_START.match(text)
    if not m:
        return None
    marker = m.group(1).translate(SUPERSCRIPTS)
    return marker, text[m.end() :]


def find_marker(text: str, marker: str, taken: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Locate a note reference in prose. Returns (start, end) or None."""
    if marker.isdigit():
        num = re.escape(marker)
        after = r"(?=[\s.,;:!?)]|$)"
        patterns = [
            re.escape(marker.translate(_TO_SUPER)),
            # digit glued to a word ("word2 ") or to punctuation after a word ("end.2")
            rf"(?<=[^\W\d_]){num}{after}",
            rf"(?<=[^\W\d_][.,;:!?”’\")\]]){num}{after}",
        ]
    else:
        patterns = [re.escape(marker)]
    for pat in patterns:
        for m in re.finditer(pat, text):
            span = (m.start(), m.end())
            if not any(s < span[1] and span[0] < e for s, e in taken):
                return span
    return None


def _on_page(b: Block, page: int) -> bool:
    return b.page == page or page in b.attrs.get("pages", ())


def link_footnotes(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    blocks = list(ir.blocks)
    refs: dict[int, list[dict[str, Any]]] = {}
    changes: list[Change] = []
    drop: set[int] = set()
    last_note: int | None = None

    for fi, f in enumerate(blocks):
        if f.kind != BlockKind.FOOTNOTE:
            continue
        parsed = split_marker(f.text)
        if parsed is None:
            if last_note is not None:
                prev = blocks[last_note]
                blocks[last_note] = prev.model_copy(
                    update={"text": f"{prev.text} {f.text.strip()}"}
                )
                drop.add(fi)
                changes.append(Change("footnotes", "merge", f.id, f.page, "note continues"))
            else:
                blocks[fi] = f.model_copy(update={"attrs": {**f.attrs, "unmatched": True}})
                changes.append(Change("footnotes", "unmatched", f.id, f.page, short(f.text, 40)))
            continue
        marker, body = parsed
        found = None
        for pi, p in enumerate(blocks):
            if p.kind not in _PROSE or not _on_page(p, f.page):
                continue
            taken = [(r["start"], r["end"]) for r in refs.get(pi, [])]
            span = find_marker(p.text, marker, taken)
            if span:
                found = (pi, span)
                break
        attrs = {**f.attrs, "marker": marker}
        if found:
            pi, (start, end) = found
            refs.setdefault(pi, []).append({"start": start, "end": end, "note": f.id})
            attrs["linked"] = True
            changes.append(Change("footnotes", "link", f.id, f.page, f"marker {marker}"))
        else:
            attrs["unmatched"] = True
            changes.append(Change("footnotes", "unmatched", f.id, f.page, f"marker {marker}"))
        blocks[fi] = f.model_copy(update={"text": body, "attrs": attrs})
        last_note = fi

    for pi, rs in refs.items():
        p = blocks[pi]
        blocks[pi] = p.model_copy(
            update={"attrs": {**p.attrs, "noterefs": sorted(rs, key=lambda r: r["start"])}}
        )
    kept = [b for i, b in enumerate(blocks) if i not in drop]
    return ir.model_copy(update={"blocks": kept}), changes
