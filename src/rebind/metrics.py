"""Ground-truth metrics: CER, WER, paragraph-break F1, header leaks.

Exact edit distance over a whole book is quadratic, so alignment is done in two
steps: difflib aligns the word sequences, then exact Levenshtein distance is
computed inside each mismatched segment. Segments too large for the exact
computation fall back to max(len) (an upper bound).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

MAX_CELLS = 4_000_000

_QUOTES = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "—": "-",
        "–": "-",
        "‐": "-",
        "‑": "-",
        "−": "-",
    }
)


def normalize(text: str) -> str:
    """Comparable form: NFKC, case-folded, unified quotes/dashes, no space before punctuation."""
    t = unicodedata.normalize("NFKC", text).translate(_QUOTES).casefold()
    t = t.replace("…", "...").replace("_", "")
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def tokenize(text: str) -> list[str]:
    """Words for WER: normalized, punctuation stripped."""
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", normalize(text))


def levenshtein(a: str | list[str], b: str | list[str]) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    if len(a) * len(b) > MAX_CELLS:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _opcodes(a: Sequence[str], b: Sequence[str]) -> Sequence[tuple[str, int, int, int, int]]:
    return SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def cer(hyp: str, ref: str) -> float:
    """Character error rate of hyp against ref (both normalized first)."""
    h, r = normalize(hyp).split(" "), normalize(ref).split(" ")
    ref_chars = len(" ".join(r))
    if ref_chars == 0:
        return 0.0 if not "".join(h) else 1.0
    dist = 0
    for tag, i1, i2, j1, j2 in _opcodes(h, r):
        if tag != "equal":
            dist += levenshtein(" ".join(h[i1:i2]), " ".join(r[j1:j2]))
    return dist / ref_chars


def wer(hyp: str, ref: str) -> float:
    h, r = tokenize(hyp), tokenize(ref)
    if not r:
        return 0.0 if not h else 1.0
    dist = sum(
        levenshtein(h[i1:i2], r[j1:j2]) for tag, i1, i2, j1, j2 in _opcodes(h, r) if tag != "equal"
    )
    return dist / len(r)


def _break_positions(paragraphs: list[str]) -> tuple[list[str], set[int]]:
    words: list[str] = []
    starts: set[int] = set()
    for p in paragraphs:
        toks = tokenize(p)
        if toks:
            starts.add(len(words))
            words.extend(toks)
    return words, starts


def paragraph_f1(hyp_paras: list[str], ref_paras: list[str]) -> dict[str, float]:
    """Precision/recall/F1 of paragraph starts, over word positions the alignment can map."""
    hw, hs = _break_positions(hyp_paras)
    rw, rs = _break_positions(ref_paras)
    h2r: dict[int, int] = {}
    mappable_ref: set[int] = set()
    for tag, i1, i2, j1, j2 in _opcodes(hw, rw):
        if tag == "equal":
            for k in range(i2 - i1):
                h2r[i1 + k] = j1 + k
            mappable_ref.update(range(j1, j2))
    hyp_breaks = {h2r[i] for i in hs if i in h2r}
    ref_breaks = rs & mappable_ref
    tp = len(hyp_breaks & ref_breaks)
    precision = tp / len(hyp_breaks) if hyp_breaks else 0.0
    recall = tp / len(ref_breaks) if ref_breaks else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def header_leaks(paragraphs: list[str], running_headers: list[str]) -> int:
    """Running-header strings or bare page numbers left in body paragraphs."""
    from rebind.text import is_page_number

    count = 0
    for p in paragraphs:
        if is_page_number(p):
            count += 1
            continue
        for h in running_headers:
            count += p.count(h)
    return count


@dataclass
class Scores:
    cer: float
    wer: float
    paragraph_precision: float
    paragraph_recall: float
    paragraph_f1: float
    header_leaks: int
    hyp_chars: int
    ref_chars: int

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()}


def score(hyp_paras: list[str], ref_paras: list[str], running_headers: list[str]) -> Scores:
    hyp, ref = "\n".join(hyp_paras), "\n".join(ref_paras)
    pf = paragraph_f1(hyp_paras, ref_paras)
    return Scores(
        cer=cer(hyp, ref),
        wer=wer(hyp, ref),
        paragraph_precision=pf["precision"],
        paragraph_recall=pf["recall"],
        paragraph_f1=pf["f1"],
        header_leaks=header_leaks(hyp_paras, running_headers),
        hyp_chars=len(normalize(hyp)),
        ref_chars=len(normalize(ref)),
    )
