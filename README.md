# rebind

Turn scanned PDFs into clean, reflowable EPUBs. Open source (Apache-2.0),
free, self-hostable.

```
PDF ─► ingest ─► rasterize ─► preprocess ─► ocr ─► cleanup ─► build ─► validate ─► EPUB + report
```

Every stage writes its own folder inside `jobs/<slug>/`, so runs are
resumable and every intermediate file can be inspected. See [PLAN.md](PLAN.md)
for the design and roadmap.

> **Status: early development (M2).** Scan in, valid EPUB 3 out, with
> cleanup rules and a quality report that points at the pages worth checking.
> Docker images and watch mode are milestone M3.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- External tools: poppler-utils, unpaper, pandoc (≥ 3.0), epubcheck, and a
  Java runtime

macOS (Homebrew):

```bash
brew install poppler unpaper pandoc epubcheck
```

Debian / Ubuntu:

```bash
sudo apt install poppler-utils unpaper pandoc epubcheck default-jre-headless
```

## Install and check

```bash
uv sync --extra docling
```

```bash
uv run rebind doctor
```

`doctor` lists each external tool with its version and says what is missing.
`rebind engines` lists OCR engines and the devices they can use (CUDA, MPS,
CPU).

## Convert a book

```bash
uv run rebind run book.pdf --title "The Book" --author "Jane Author"
```

The EPUB is copied to `out/<slug>.epub`. The job folder keeps everything:

```
jobs/<slug>/
  manifest.json        input hash, config snapshot, stage status, timings, tool versions
  00_source/           input.pdf, info.json (page geometry, scan DPI, text-layer check)
  10_pages/            rendered page images (spreads split), cover.png
  20_clean/            unpaper-cleaned page images
  30_ir/raw.json       BookIR straight from the engine (+ per-page cache)
  40_ir/clean.json     BookIR after cleanup (+ changes.json)
  50_build/            book.md, metadata.yaml, book.epub
  60_report/           report.json, report.html, epubcheck.json
```

Running the same command again skips stages whose inputs and settings did not
change. To redo part of the pipeline (for example after editing
`40_ir/clean.json` by hand):

```bash
uv run rebind run book.pdf --from build
```

An interrupted OCR run resumes page by page. `rebind report jobs/<slug>` shows
each stage's status.

## What cleanup does

Each rule can be switched off in `[cleanup]` and records its edits in
`40_ir/changes.json`:

- drops running headers, footers and page numbers (engine labels first, then a
  repetition heuristic)
- repairs reading order on single-column pages
- typography: ligatures, whitespace, ellipses, dashes; for English also curly
  quotes and old-style spacing before `; : ! ?`
- joins words hyphenated across lines when the joined word is in the dictionary
- merges paragraphs split by page or column breaks
- links footnote markers to notes (EPUB 3 pop-up footnotes)
- fixes the heading structure (promotes "Chapter IV", demotes letter
  sign-offs, merges titles split over several lines)
- tags front matter and drops the scanned table of contents

## Quality report

`60_report/report.html` shows every flagged page's scan next to the text that
was read from it, with the reason: garbled lines, a lost first line after a
chapter heading, low OCR confidence, far too little or too much text, empty
pages that aren't blank, leftover headers, unmatched footnotes, unbalanced
brackets. The book also gets a 0–100 score.

```bash
uv run rebind report jobs/<slug> --open
```

## Configuration

Settings come from, in increasing priority: built-in defaults, the profile
preset (`novel`, `nonfiction`, `academic`, `two-column`), `rebind.toml` in the
current directory (or `--config`), and CLI flags. See
[rebind.example.toml](rebind.example.toml) for every option.

## Development

```bash
uv sync --all-extras
```

```bash
uv run pytest -m "not integration"
```

```bash
uv run pytest -m integration
```

The integration test converts a 5-page public-domain scan
(`tests/fixtures/jekyll-5p.pdf`) end to end. Lint and types:
`uv run ruff check . && uv run pyright`.

Accuracy is measured against public-domain ground truth (see
[docs/benchmarks.md](docs/benchmarks.md)):

```bash
uv run python scripts/corpus.py all
```

## Licensing

Apache-2.0. Bundled engines must be permissively licensed; see
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Use rebind for books you
own or that are in the public domain.
