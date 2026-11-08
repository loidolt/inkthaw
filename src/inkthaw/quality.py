"""Per-page quality flags and an overall book score.

Character counts, dictionary checks and garble detection use the raw engine
output (what the OCR saw on that page, minus furniture). Leaks, footnotes and
bracket balance use the cleaned IR (what ends up in the EPUB).
"""

from __future__ import annotations

import itertools
import os
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from inkthaw.config import Config
from inkthaw.imaging import png_size
from inkthaw.ir import FURNITURE_KINDS, Block, BlockKind, BookIR
from inkthaw.text import (
    dictionary_available,
    is_page_number,
    normalize_furniture,
    starts_lowercase,
    zipf,
)

WEIGHTS: dict[str, float] = {
    "empty_page": 0.6,
    "low_dictionary_ratio": 0.5,
    "garbled_text": 0.3,
    "missing_start": 0.3,
    "low_confidence": 0.3,
    "low_char_count": 0.3,
    "high_char_count": 0.2,
    "leaked_furniture": 0.2,
    "unmatched_footnote": 0.1,
    "unbalanced_brackets": 0.1,
}

FLAG_HELP: dict[str, str] = {
    "empty_page": "No text found, but the page image is not blank",
    "low_dictionary_ratio": "Many words are not in the dictionary (garbled OCR)",
    "garbled_text": "A run of non-words, typically one misread line",
    "missing_start": "Text after a heading starts mid-sentence (lost first line, e.g. a drop cap)",
    "low_confidence": "The engine's own OCR confidence is low",
    "low_char_count": "Far less text than a typical page (missed text?)",
    "high_char_count": "Far more text than a typical page (duplicated text?)",
    "leaked_furniture": "A running header or page number survived cleanup",
    "unmatched_footnote": "Footnote without a marker in the text",
    "unbalanced_brackets": "Opening and closing brackets do not match",
}

_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
MIN_TOKENS = 30
GARBLE_WINDOW = 5
GARBLE_UNKNOWN = 3
BLANK_DENSITY_SHARE = 0.12
"""A page image compressing to < this share of a typical text page is blank."""
TEXT_PAGE_MIN_CHARS = 200


# One-letter words. wordfreq rates stray letters ("b", "s") as common tokens,
# so for languages listed here only these count; others need zipf >= 5.
SINGLE_LETTER_WORDS = {
    "en": {"a", "i", "o"},
    "fr": {"a", "à", "y", "ô"},
    "es": {"a", "e", "o", "u", "y"},
    "it": {"a", "e", "è", "i", "o"},
    "de": set(),
    "nl": set(),
}


def _known(tok: str, lang: str) -> bool:
    t = tok.lower()
    if len(t) == 1:
        base = lang.split("-")[0].lower()
        if base in SINGLE_LETTER_WORDS:
            return t in SINGLE_LETTER_WORDS[base]
        return zipf(t, lang) >= 5.0
    z = zipf(t, lang)
    if len(t) == 2:
        return z >= 4.5  # two-letter tokens must be very common words ("of", "he")
    if len(t) == 3:
        return z >= 2.5
    return z >= 1.0


def _known_at(text: str, m: re.Match[str], lang: str) -> bool:
    # "M.D.", "J. G. Utterson", "W.C.": short tokens followed by a period are initials.
    if len(m.group()) <= 3 and text[m.end() : m.end() + 1] == ".":
        return True
    return _known(m.group(), lang)


def garbled_runs(text: str, lang: str) -> list[str]:
    """Substrings of `text` where most of a few consecutive tokens are non-words."""
    toks = list(_TOKEN.finditer(text))
    runs = []
    i = 0
    while i + GARBLE_WINDOW <= len(toks):
        window = toks[i : i + GARBLE_WINDOW]
        if sum(not _known_at(text, m, lang) for m in window) >= GARBLE_UNKNOWN:
            runs.append(text[window[0].start() : window[-1].end()])
            i += GARBLE_WINDOW
        else:
            i += 1
    return runs


def dictionary_ratio(text: str, lang: str) -> tuple[float | None, int]:
    toks = _TOKEN.findall(text)
    if len(toks) < MIN_TOKENS:
        return None, len(toks)
    return sum(_known(t, lang) for t in toks) / len(toks), len(toks)


@dataclass
class Flag:
    code: str
    detail: str = ""


@dataclass
class PageQuality:
    index: int
    source_page: int | None
    image: str
    chars: int
    confidence: float | None
    dictionary_ratio: float | None
    ink_density: float
    flags: list[Flag] = field(default_factory=list)

    @property
    def score(self) -> float:
        return max(0.0, 1.0 - sum(WEIGHTS.get(f.code, 0.1) for f in self.flags))


def _page_text(blocks: list[Block]) -> str:
    return "\n".join(b.text for b in blocks if b.text)


def _balance(text: str, open_ch: str, close_ch: str) -> int:
    return text.count(open_ch) - text.count(close_ch)


def assess(raw: BookIR, clean: BookIR, cfg: Config, job_root: Path) -> dict[str, Any]:
    q = cfg.quality
    lang = cfg.metadata.language
    use_dict = dictionary_available(lang)

    raw_by_page: dict[int, list[Block]] = {p.index: [] for p in raw.pages}
    furniture_keys: set[str] = set()
    for b in raw.blocks:
        if b.kind in FURNITURE_KINDS:
            key = normalize_furniture(b.text)
            if key and key != "#":
                furniture_keys.add(key)
        else:
            raw_by_page.setdefault(b.page, []).append(b)

    clean_by_page: dict[int, list[Block]] = {}
    for b in clean.blocks:
        clean_by_page.setdefault(b.page, []).append(b)
    heading_pages = {b.page for b in clean.blocks if b.kind == BlockKind.HEADING}
    front_pages = {b.page for b in clean.blocks if b.attrs.get("role")}
    pages_with_clean_text = {
        p for b in clean.blocks if b.text for p in (b.page, *b.attrs.get("pages", ()))
    }
    dropped_pages = (
        {p.index for p in raw.pages}
        - pages_with_clean_text
        - {p for p, bs in raw_by_page.items() if not any(b.text for b in bs)}
    )

    pages: list[PageQuality] = []
    for p in raw.pages:
        blocks = raw_by_page.get(p.index, [])
        text = _page_text(blocks)
        img_path = job_root / p.image_path
        try:
            w, h = png_size(img_path)
            density = os.path.getsize(img_path) / max(1, w * h)
        except (OSError, ValueError):
            density = 0.0
        ratio, _ = dictionary_ratio(text, lang) if use_dict else (None, 0)
        pages.append(
            PageQuality(
                index=p.index,
                source_page=p.source_page,
                image=p.image_path,
                chars=sum(len(b.text) for b in blocks),
                confidence=p.confidence,
                dictionary_ratio=round(ratio, 4) if ratio is not None else None,
                ink_density=round(density, 5),
            )
        )

    text_pages = [pq for pq in pages if pq.chars >= TEXT_PAGE_MIN_CHARS]
    median_chars = statistics.median(pq.chars for pq in text_pages) if text_pages else 0
    median_density = statistics.median(pq.ink_density for pq in text_pages) if text_pages else 0.0
    last_text_page = max((pq.index for pq in text_pages), default=-1)

    for pq in pages:
        i = pq.index
        raw_blocks = raw_by_page.get(i, [])
        has_image = any(b.kind == BlockKind.IMAGE for b in raw_blocks)
        exempt = i in front_pages or i in dropped_pages

        inked = median_density and pq.ink_density >= BLANK_DENSITY_SHARE * median_density
        if pq.chars == 0 and not has_image and inked:
            pq.flags.append(Flag("empty_page", f"ink density {pq.ink_density:.4f}"))
        if pq.confidence is not None and pq.chars and pq.confidence < q.low_confidence:
            pq.flags.append(Flag("low_confidence", f"{pq.confidence:.2f}"))
        if median_chars and pq.chars and not exempt:
            chapter_edge = i in heading_pages or (i + 1) in heading_pages or i == last_text_page
            if pq.chars < q.char_count_low * median_chars and not chapter_edge:
                pq.flags.append(Flag("low_char_count", f"{pq.chars} vs median {median_chars:.0f}"))
            if pq.chars > q.char_count_high * median_chars:
                pq.flags.append(Flag("high_char_count", f"{pq.chars} vs median {median_chars:.0f}"))
        if use_dict and not exempt:
            if pq.dictionary_ratio is not None and pq.dictionary_ratio < q.min_dictionary_ratio:
                pq.flags.append(Flag("low_dictionary_ratio", f"{pq.dictionary_ratio:.2f}"))
            runs = [
                r
                for b in raw_blocks
                if b.kind != BlockKind.TABLE
                for r in garbled_runs(b.text, lang)
            ]
            if runs:
                pq.flags.append(Flag("garbled_text", " | ".join(runs[:3])))

        cblocks = clean_by_page.get(i, [])
        for a, b in itertools.pairwise(cblocks):
            if (
                a.kind == BlockKind.HEADING
                and b.kind == BlockKind.PARAGRAPH
                and starts_lowercase(b.text)
            ):
                pq.flags.append(Flag("missing_start", f"after {a.text[:40]!r}: {b.text[:30]!r}"))
        prose = [b for b in cblocks if b.kind not in (BlockKind.IMAGE, BlockKind.TABLE)]
        edges = prose[:2] + prose[-2:] if prose else []
        leaks = {
            b.text
            for b in edges
            if b.kind != BlockKind.HEADING
            and len(b.text) <= 80
            and (is_page_number(b.text) or normalize_furniture(b.text) in furniture_keys)
        }
        if leaks:
            pq.flags.append(Flag("leaked_furniture", " | ".join(sorted(leaks))[:120]))
        unmatched = [
            b for b in cblocks if b.kind == BlockKind.FOOTNOTE and b.attrs.get("unmatched")
        ]
        if unmatched:
            pq.flags.append(Flag("unmatched_footnote", f"{len(unmatched)} note(s)"))
        ctext = _page_text([b for b in cblocks if b.page == i])
        diffs = {pair: _balance(ctext, *pair) for pair in ("()", "[]")}
        bad = {k: v for k, v in diffs.items() if abs(v) > q.unbalanced_tolerance}
        if bad:
            pq.flags.append(
                Flag("unbalanced_brackets", ", ".join(f"{k} {v:+d}" for k, v in bad.items()))
            )

    flagged = [pq for pq in pages if pq.flags]
    counts: dict[str, int] = {}
    for pq in flagged:
        for f in pq.flags:
            counts[f.code] = counts.get(f.code, 0) + 1
    score = round(100 * sum(pq.score for pq in pages) / len(pages), 1) if pages else 0.0
    return {
        "score": score,
        "pages": len(pages),
        "flagged_pages": len(flagged),
        "flag_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "median_chars": median_chars,
        "dictionary_checks": use_dict,
        "page_details": [{**asdict(pq), "score": round(pq.score, 3)} for pq in pages],
    }
