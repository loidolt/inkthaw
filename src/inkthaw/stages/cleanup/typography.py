"""Rule: whitespace and typography normalization.

All languages: Unicode NFC, ligatures (ﬁ -> fi), invisible characters,
whitespace runs, ellipses, doubled-hyphen dashes.

English only: curly quotes and apostrophes, and the old typesetting habit of
spacing before ; : ! ? and inside quotation marks ("quaintly : " I let" ->
"quaintly: “I let"). Other languages keep their own quotation conventions and
spacing (French « guillemets » and spaced punctuation stay as printed).
"""

from __future__ import annotations

import re
import unicodedata

from inkthaw.config import Config
from inkthaw.ir import BookIR
from inkthaw.stages.cleanup.base import TEXT_KINDS, Change, short
from inkthaw.text import base_language

LIGATURES = str.maketrans(
    {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
)
_INVISIBLE = re.compile("[​‌‍⁠﻿]|­(?!\\s)")
# Collapse ordinary whitespace; keep no-break spaces (French typography uses them).
_SPACES = re.compile("[ \t\r\n - 　]+")
_ELLIPSIS = re.compile(r"\.\s?\.\s?\.")

_CLOSE_PREV = set(".,;:!?…—–)]’”")
_CLOSE_NEXT = set(".,;:!?)]—–")
_OPEN_PREV = set("([{—–‘“")


def normalize_common(text: str) -> str:
    t = unicodedata.normalize("NFC", text).translate(LIGATURES)
    t = _INVISIBLE.sub("", t)
    t = _SPACES.sub(" ", t).strip()
    t = _ELLIPSIS.sub("…", t)
    t = t.replace("---", "—").replace("--", "—")
    return t


def _curl_double(t: str) -> str:
    t = re.sub(r'"{2,}', '"', t)
    out: list[str] = []
    inside = False
    n = len(t)
    for i, ch in enumerate(t):
        if ch != '"':
            out.append(ch)
            continue
        prev = t[i - 1] if i > 0 else " "
        nxt = t[i + 1] if i + 1 < n else " "
        if (prev.isalnum() or prev in _CLOSE_PREV) and (nxt.isspace() or nxt in _CLOSE_NEXT):
            closing = True
        elif (prev.isspace() or prev in _OPEN_PREV) and (nxt.isalnum() or nxt in "'‘…—"):
            closing = False
        else:  # ambiguous, e.g. spaced on both sides: follow the open/close state
            closing = inside
        out.append("”" if closing else "“")
        inside = not closing
    s = "".join(out)
    s = re.sub(r"“\s+", "“", s)
    s = re.sub(r"\s+”", "”", s)
    s = re.sub(r"”(?=[^\W\d_])", "” ", s)
    s = re.sub(r"(?<=[^\W\d_])“", " “", s)
    return s


def _curl_single(s: str) -> str:
    s = re.sub(r"(?<=[^\W_])'(?=[^\W_])", "’", s)  # don't, o'clock
    s = re.sub(r"(^|[\s(\[“—–])'(?=[^\W_])", r"\1‘", s)  # opening quote
    return s.replace("'", "’")


# Old typefaces' curly quotes look like 66 and 99, and OCR reads them so:
# '66 Did you ever...', 'added he, 66 with a very odd story.’ 99'.
_QUOTE_66 = re.compile(r"(^|(?<=[,:;—]\s))66\s?(?=[^\W\d_])")
# a closing 99 follows a word plus punctuation ("story. 99"), or a closing single quote
_QUOTE_99_AFTER_WORD = re.compile(r"(?<=[^\W\d_][.,!?;:—])\s?99(?=\s|$)")
_QUOTE_99_AFTER_QUOTE = re.compile(r"(?<=[\u2019'])\s?99(?=\s|$)")


def fix_figure_quotes(text: str) -> str:
    t = _QUOTE_66.sub(r'\1"', text)
    t = _QUOTE_99_AFTER_WORD.sub('"', t)
    return _QUOTE_99_AFTER_QUOTE.sub('"', t)


def normalize_english(text: str) -> str:
    t = fix_figure_quotes(text)
    t = re.sub(r"(?<=\S)\s+([;:!?,])(?=\s|$|[\"'”’)\]])", r"\1", t)
    t = _curl_double(t)
    t = _curl_single(t)
    return t


def normalize(text: str, lang: str | None) -> str:
    t = normalize_common(text)
    if base_language(lang) == "en":
        t = normalize_english(t)
    return t


def normalize_typography(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change]]:
    lang = cfg.metadata.language
    blocks = []
    changes: list[Change] = []
    for b in ir.blocks:
        if b.kind in TEXT_KINDS and b.text:
            text = normalize(b.text, lang)
            if text != b.text:
                changes.append(Change("typography", "edit", b.id, b.page, short(text, 50)))
                b = b.model_copy(update={"text": text})
        blocks.append(b)
    return ir.model_copy(update={"blocks": blocks}), changes
