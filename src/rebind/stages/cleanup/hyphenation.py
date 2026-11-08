"""Rule: join words split by end-of-line hyphenation.

"enter- prises" (hyphen, whitespace, lowercase continuation) becomes
"enterprises" when the joined word is a common dictionary word; otherwise the
hyphen is kept and the space removed ("good- nature" -> "good-nature"), because
the split word was a real compound. Cross-page splits are handled by the
paragraph-merge rule, which calls `join_split_word`.
"""

from __future__ import annotations

import re

from rebind.config import Config
from rebind.ir import BlockKind, BookIR
from rebind.stages.cleanup.base import TEXT_KINDS, Change
from rebind.text import zipf

# word, hyphen (or soft hyphen / not-sign used by some OCR), whitespace, lowercase word
_SPLIT_RE = re.compile(r"([^\W\d_]+)[-­¬]\s+([^\W\d_A-Z][^\W\d_]*)")
_TRAILING_RE = re.compile(r"([^\W\d_]+)[-­¬]$")
_LEADING_RE = re.compile(r"^([^\W\d_A-Z][^\W\d_]*)")


def resolve(left: str, right: str, lang: str, min_zipf: float) -> str:
    joined = left + right
    if zipf(joined.lower(), lang) >= min_zipf:
        return joined
    return f"{left}-{right}"


def join_split_word(a: str, b: str, lang: str, min_zipf: float) -> str | None:
    """If `a` ends with a hyphenated fragment continued at the start of `b`,
    return the joined text; else None."""
    a = a.rstrip()
    b = b.lstrip()
    ma, mb = _TRAILING_RE.search(a), _LEADING_RE.match(b)
    if not (ma and mb):
        return None
    word = resolve(ma.group(1), mb.group(1), lang, min_zipf)
    return a[: ma.start()] + word + b[mb.end() :]


def join_hyphenation(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    lang = cfg.metadata.language
    min_zipf = cfg.cleanup.hyphen_join_min_zipf
    changes: list[Change] = []
    blocks = []
    for b in ir.blocks:
        if b.kind not in TEXT_KINDS or b.kind == BlockKind.HEADING:
            blocks.append(b)
            continue
        fixes: list[str] = []

        def repl(m: re.Match[str], fixes: list[str] = fixes) -> str:
            word = resolve(m.group(1), m.group(2), lang, min_zipf)
            fixes.append(f"{m.group(0)!r} -> {word!r}")
            return word

        text = _SPLIT_RE.sub(repl, b.text)
        text = text.replace("­", "")
        if text != b.text:
            changes.extend(Change("hyphenation", "edit", b.id, b.page, f) for f in fixes)
            b = b.model_copy(update={"text": text})
        blocks.append(b)
    return ir.model_copy(update={"blocks": blocks}), changes
