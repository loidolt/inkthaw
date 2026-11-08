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

## M5: no poppler, no unpaper

M5 replaced poppler with PDFium (`pypdfium2`) and unpaper with a built-in
preprocess backend (numpy + Pillow). Same book, settings and machine as above
(Docling 2.149.0, MPS), 2026-11-08. "Raster" is what turns PDF pages into
300 dpi images; "preprocess" is what cleans them. Rows marked (variant) swapped
the page images in a copy of a finished job and re-ran from OCR.

| Raster | Preprocess | CER | WER | Para F1 | Leaks | Flagged | Score |
|---|---|---|---|---|---|---|---|
| poppler | unpaper (baseline re-run before M5) | 1.66% | 2.63% | 0.962 | 1 | 37 | 90.6 |
| PDFium | unpaper (variant) | 1.89% | 2.90% | 0.961 | 0 | 36 | 91.0 |
| PDFium | none (variant) | 2.33% | 3.40% | 0.893 | 2 | 37 | 90.6 |
| PDFium | builtin v1: borders, despeckle, deskew (despeckle ate thin strokes) | 2.70% | 3.81% | 0.879 | 2 | 43 | 89.1 |
| PDFium | builtin v2: despeckle fixed | 2.55% | 3.59% | 0.887 | 2 | 37 | 90.6 |
| poppler | builtin v2 (variant) | 2.67% | 3.84% | 0.881 | 3 | 53 | 86.7 |
| PDFium | builtin v3: + mask and centre the text area | 2.31% | 3.32% | 0.971 | 1 | 38 | 90.5 |
| PDFium | v3 + half-pixel bicubic resample (variant) | 1.96% | 3.02% | 0.967 | 0 | 37 | 90.8 |
| **PDFium** | **v3 + quarter-pixel resample (`soften`, M5 default)** | **1.82%** | **2.80%** | **0.966** | **0** | **31** | **92.2** |
| PDFium at 600 dpi, box-downsampled to 300 | M5 default (variant) | 1.95% | 3.06% | 0.958 | — | — | — |
| PDFium, darkened (gamma 1.6) | M5 default (variant, not adopted) | 1.75% | 2.68% | 0.958 | — | — | — |

What moved the numbers:

- **Centring the text area fixes paragraphs.** Without it Docling split the
  last line of many paragraphs into a block of its own (paragraph precision
  0.82 instead of 0.94). unpaper's mask detection wipes everything outside the
  text area and centres it on the page; `mask_content` does the same.
- **Slightly soft glyph edges help RapidOCR.** unpaper resampled 95 of the 120
  pages while deskewing by tiny angles, which anti-aliases the hard edges of
  this bitonal (JBIG2) scan. The recognizer garbles fewer lines on such images:
  a bicubic quarter-pixel resample (`soften`) took CER from 2.31% to 1.82%;
  a half-pixel one, which softens more, gave 1.96%.
- **Despeckle must only touch isolated dots.** The first version removed dark
  pixels with few dark neighbours, which ate thin serifs and hairlines across
  every page. It now also requires a ring of clean paper around a speck.
- **Rasterizer.** With unpaper, PDFium pages scored 1.89% against poppler's
  1.66%; with the builtin v2 backend PDFium was the better of the two (2.55%
  vs 2.67%). PDFium draws strokes a little thinner than poppler's Splash
  renderer. Darkening PDFium's pages to mimic heavier strokes gave 1.75%, but
  paragraph F1 fell to 0.958 and the gain is about two lines, so it is not the
  default until a second corpus book confirms it. Supersampling (600 dpi, box
  filter down to 300) was worse (1.95%).

The M5 default is 0.16 points of CER behind the poppler + unpaper baseline and
0.07 points ahead of unpaper on the same PDFium pages, with better paragraph
F1, no header leaks and fewer flagged pages. Differences of this size come
from a handful of lines the recognizer garbles or not (each such line costs
about 0.04 points), so a second corpus book is needed before reading more into
them.

## Quality flags vs ground truth

To check that `report.html` points reviewers at the right pages, each page's
word error rate was measured against the ground truth (pages 15–118, the
Jekyll text) and compared with the flags, using the default settings above:

- 9 of the 10 worst pages are flagged, and 18 of the 20 worst.
- Flagged pages have a median word error rate of 4.9%; unflagged pages 1.0%.
- No flagged page has an error rate below 2% (no false alarms on clean pages).
- 37 pages are flagged in total, almost all for `garbled_text` (one misread
  line).
