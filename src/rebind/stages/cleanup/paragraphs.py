"""Rule: merge paragraphs split by a page (or column) break.

Two paragraphs on either side of a break are merged when the first cannot be a
paragraph end (no terminal punctuation) or the second starts in lowercase.
Footnotes, captions and images between them are skipped over and stay after
the merged paragraph.
"""

from __future__ import annotations

from rebind.config import Config
from rebind.ir import Block, BlockKind, BookIR
from rebind.stages.cleanup.base import Change, short
from rebind.stages.cleanup.hyphenation import join_split_word
from rebind.text import is_terminal, starts_lowercase

_TRANSPARENT = frozenset({BlockKind.FOOTNOTE, BlockKind.CAPTION, BlockKind.IMAGE})
COLUMN_JUMP_PX = 5.0


def _is_break(a: Block, b: Block) -> bool:
    if b.page != a.page:
        return True
    # Same page: a jump back up means a new column.
    return bool(a.bbox and b.bbox and b.bbox[1] < a.bbox[1] - COLUMN_JUMP_PX)


def should_merge(a: Block, b: Block) -> bool:
    if not (a.text.strip() and b.text.strip()):
        return False
    return not is_terminal(a.text) or starts_lowercase(b.text)


def merge_paragraphs(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    lang = cfg.metadata.language
    min_zipf = cfg.cleanup.hyphen_join_min_zipf
    out: list[Block] = []
    changes: list[Change] = []
    last: int | None = None  # index in `out` of the paragraph that may continue
    for b in ir.blocks:
        if b.kind == BlockKind.PARAGRAPH and last is not None:
            a = out[last]
            if _is_break(a, b) and should_merge(a, b):
                joined = join_split_word(a.text, b.text, lang, min_zipf)
                text = joined if joined is not None else f"{a.text.rstrip()} {b.text.lstrip()}"
                pages = sorted({*a.attrs.get("pages", [a.page]), b.page})
                merged_from = [*a.attrs.get("merged_from", []), b.id]
                out[last] = a.model_copy(
                    update={
                        "text": text,
                        "attrs": {**a.attrs, "pages": pages, "merged_from": merged_from},
                    }
                )
                changes.append(
                    Change(
                        "paragraphs",
                        "merge",
                        a.id,
                        b.page,
                        f"{short(a.text[-30:], 30)!r} + {short(b.text, 30)!r}",
                    )
                )
                continue
        out.append(b)
        if b.kind == BlockKind.PARAGRAPH:
            last = len(out) - 1
        elif b.kind not in _TRANSPARENT:
            last = None
    return ir.model_copy(update={"blocks": out}), changes
