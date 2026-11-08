"""Render BookIR to Pandoc Markdown.

All OCR text is escaped so it can never be read as Markdown syntax.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from inkthaw.ir import Block, BlockKind, BookIR

# Pandoc allows backslash-escaping any ASCII punctuation; escape everything that
# could start inline syntax.
_INLINE_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#|~^$@&])")

# Line-start constructs: lists ("1.", "a)", "(iv)", "#."), blockquote,
# definition-list markers, title block, horizontal rules.
_LIST_START = re.compile(r"^(\(?)(\d+|[a-zA-Z]|[ivxlcdmIVXLCDM]+|#)([.)])(\s|$)")
_BULLET_START = re.compile(r"^([-+*:%=])(\s|$)")
_WS = re.compile(r"\s+")


def escape_inline(text: str) -> str:
    """Escape Markdown syntax without touching whitespace."""
    return _INLINE_SPECIAL.sub(r"\\\1", text)


def _fix_line_start(text: str) -> str:
    if m := _LIST_START.match(text):
        paren, marker, punct, rest = m.groups()
        text = (r"\(" if paren else "") + marker + "\\" + punct + rest + text[m.end() :]
    elif _BULLET_START.match(text):
        text = "\\" + text
    return text


def escape(text: str) -> str:
    return _fix_line_start(escape_inline(_WS.sub(" ", text).strip()))


def note_label(block_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", block_id)


def prose(block: Block) -> str:
    """Escaped block text with linked footnote references inserted."""
    refs = block.attrs.get("noterefs") or []
    if not refs:
        return escape(block.text)
    text, out, pos = block.text, [], 0
    for r in sorted(refs, key=lambda r: r["start"]):
        out.append(escape_inline(text[pos : r["start"]]))
        out.append(f"[^{note_label(r['note'])}]")
        pos = r["end"]
    out.append(escape_inline(text[pos:]))
    return _fix_line_start(_WS.sub(" ", "".join(out)).strip())


def _table(block: Block) -> str:
    rows: list[list[str]] = block.attrs.get("rows") or []
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return escape(block.text) if block.text else ""
    width = max(len(r) for r in rows)

    def cell(text: str) -> str:
        return escape(text) or " "  # escape() already handles "|"

    lines = []
    header = rows[0] + [""] * (width - len(rows[0]))
    lines.append("| " + " | ".join(cell(c) for c in header) + " |")
    lines.append("|" + "|".join(["---"] * width) + "|")
    for r in rows[1:]:
        r = r + [""] * (width - len(r))
        lines.append("| " + " | ".join(cell(c) for c in r) + " |")
    out = "\n".join(lines)
    if caption := block.attrs.get("caption"):
        out += f"\n\n: {escape(caption)}"
    return out


def render(ir: BookIR, image_href: Callable[[str], str] | None = None) -> str:
    """Render blocks in reading order. image_href maps an IR image path to an href."""
    parts: list[str] = []
    list_buf: list[str] = []
    in_front = False

    def flush_list() -> None:
        if list_buf:
            parts.append("\n".join(list_buf))
            list_buf.clear()

    for b in ir.blocks:
        front = b.attrs.get("role") in ("front_matter", "copyright")
        if front != in_front:
            flush_list()
            parts.append("::: front-matter" if front else ":::")
            in_front = front
        if b.kind == BlockKind.LIST_ITEM:
            text = prose(b)
            # Docling keeps the bullet/number glyph in the text; strip a leading one.
            text = re.sub(r"^(\\[-+*]|[•·▪◦–—]|\d+\\[.)])\s*", "", text)
            marker = "1." if b.attrs.get("enumerated") else "-"
            list_buf.append(f"{marker} {text}")
            continue
        flush_list()

        if b.kind == BlockKind.HEADING:
            level = min(max(b.level or 1, 1), 6)
            parts.append("#" * level + " " + escape(b.text))
        elif b.kind == BlockKind.TABLE:
            if rendered := _table(b):
                parts.append(rendered)
        elif b.kind == BlockKind.IMAGE:
            path = b.attrs.get("image_path")
            if path:
                href = image_href(path) if image_href else path
                alt = escape(b.attrs.get("caption") or b.text or "")
                parts.append(f"![{alt}]({href})")
            elif b.text:
                parts.append(escape(b.text))
        elif b.kind == BlockKind.FOOTNOTE:
            if b.attrs.get("linked"):
                parts.append(f"[^{note_label(b.id)}]: {escape(b.text)}")
            else:
                parts.append("::: footnote-text\n" + escape(b.text) + "\n:::")
        elif b.kind == BlockKind.CAPTION:
            parts.append("::: caption\n" + prose(b) + "\n:::")
        elif b.text:
            # paragraph, other, and any furniture a profile chose to keep
            parts.append(prose(b))
    flush_list()
    if in_front:
        parts.append(":::")
    return "\n\n".join(parts) + "\n"
