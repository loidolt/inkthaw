# Benchmarks

Accuracy is measured against public-domain ground truth listed in
[`tests/corpus/manifest.toml`](../tests/corpus/manifest.toml). Every scored
run is appended to `tests/corpus/results/<id>.json` with the git commit,
engine version and settings.

```bash
uv run python scripts/corpus.py all          # fetch, convert, score every book
uv run python scripts/corpus.py score jekyll-hyde --job path/to/job --label "what changed"
```

## Metrics

- **CER / WER**: character and word error rate of the EPUB text against the
  ground truth, after normalizing case, quote and dash styles, and spacing
  before punctuation. Text in the wrong order counts twice (deleted and
  inserted), so reading-order bugs show up clearly.
- **Paragraph F1**: precision/recall of paragraph starts, at positions where
  the two texts align.
- **Header leaks**: running headers or bare page numbers left in body text.

Implementation: word-level alignment with `difflib`, then exact Levenshtein
distance inside each mismatched segment. A 120-page book scores in about 6
seconds.

## Jekyll and Hyde (`jekyll-hyde`)

Scan: Internet Archive `strangecaseofd00stevuoft` (E. Nash & Grayson, Colinton
edition), pages 1–120. Ground truth: Project Gutenberg #43, a **different
edition**, so some punctuation and spelling differences (e.g. "countenance,
that" vs "countenance that") are counted as errors; the true error rate is
somewhat lower than shown. Docling 2.149.0, 300 dpi, Apple M-series (MPS),
2026-11-08.

| Run | CER | WER | Para F1 | Leaks | Flagged pages | Score |
|---|---|---|---|---|---|---|
| M1 pipeline (furniture drop only) | 11.3% | — | — | 0 | — | — |
| + M2 cleanup, Docling auto OCR (RapidOCR) | 1.77% | 2.69% | 0.954 | 0 | 38 / 120 | 90.2 |
| + RapidOCR `Det.unclip_ratio = 2.0` (rejected) | 3.09% | 4.38% | 0.948 | 0 | 22 / 120 | 94.5 |
| + RapidOCR `Det.box_thresh = 0.3` (default since M2) | 1.69% | 2.68% | 0.959 | 1 | 37 / 120 | 90.6 |
| **+ M3: repair quotes OCR'd as `66`/`99`** | **1.66%** | **2.63%** | **0.962** | 1 | 37 / 120 | 90.6 |
| (tried) split run-together words with wordfreq | 1.73% | 2.90% | 0.962 | 1 | — | — |

What moved the numbers:

- **Reading order (11.3% → 1.8%).** Docling sometimes put a page's middle
  paragraph after the bottom one when their boxes overlapped by a few pixels.
  The `reading_order` cleanup rule sorts single-column pages top to bottom.
- **Detector threshold.** With RapidOCR's default box threshold (0.5), the
  first line of every chapter, set beside a two-line drop cap, was not
  detected at all. At 0.3 all five lines come back (some with misreads, which
  the report flags).
- **Box expansion** fixed a few misread last lines but damaged more lines
  elsewhere, so it is not used.
- **unpaper's gray filter** (M1) garbled whole lines on gray-paper scans and
  is off by default.
- **Quote repair.** Old typefaces' curly quotes look like `66` and `99` and
  were read that way ("66 Did you ever remark that door?"). A narrow rule
  (a `66` before a word at a paragraph or clause start, a `99` right after
  punctuation that follows a word) restores them.
- **Splitting run-together words** ("doingwell") was tried and dropped:
  wordfreq does not know many rare real words ("untasted", "emulously") and
  scores fragments like "un" and "ly" as common, so it split more good words
  than bad ones.

The remaining errors are mostly single misread lines (e.g. `sneering. 'Set
your i ts l ss t il`): RapidOCR's recognizer fails on an occasional line it
detected correctly. Re-recognizing low-confidence lines is a candidate for
later work.

## Quality flags vs ground truth

To check that `report.html` points reviewers at the right pages, each page's
word error rate was measured against the ground truth (pages 15–118, the
Jekyll text) and compared with the flags, using the default settings above:

- 9 of the 10 worst pages are flagged, and 18 of the 20 worst.
- Flagged pages have a median word error rate of 4.9%; unflagged pages 1.0%.
- No flagged page has an error rate below 2% (no false alarms on clean pages).
- 37 pages are flagged in total, almost all for `garbled_text` (one misread
  line).
