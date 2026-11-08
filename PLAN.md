# rebind — Project Plan

Turn scanned PDFs into clean, reflowable EPUBs. Fully open source, free, self-hostable.

Repo name: `rebind` (a scanned book, taken apart and rebound as an ebook).

## 1. Goals and non-goals

### Goals

- One command takes a scanned PDF and produces a valid EPUB 3, plus a quality report flagging the pages that need human review.
- Runs anywhere: CPU-only Linux, NVIDIA GPU, and Apple Silicon (native, outside Docker).
- Every stage is resumable and inspectable, and intermediate files are kept.
- The OCR/layout engine is pluggable. The default engine has a permissive license.
- Quality is measured, not guessed: regression tests against public-domain ground truth.

### Non-goals (for now)

- Web UI and job queue (planned for v1, see §10).
- DRM, ebook stores, or anything aimed at copyrighted material the user doesn't own.
- Perfect output on every book with no review. The aim is to make review fast.

## 2. Licensing rules

- Project license: Apache-2.0.
- Bundled engines must be permissively licensed. Default engine: Docling (MIT). Planned optional engine: olmOCR (Apache-2.0).
- marker (GPL code, model weights with restrictions) and MinerU (verify current license) are never bundled. They may be supported later as separately installed plugins only.
- Keep `THIRD_PARTY_LICENSES.md` up to date for every bundled dependency and model.
- Test fixtures come only from public-domain sources (Internet Archive scans, Project Gutenberg texts).

## 3. Architecture

```
PDF ─► ingest ─► preprocess ─► ocr (engine) ─► cleanup ─► build ─► validate ─► EPUB + report
                     │              │              │          │
                  page PNGs     BookIR JSON    BookIR JSON  Markdown/XHTML
```

### Job directory (one per book)

```
jobs/<slug>/
  manifest.json        # input hash, config snapshot, stage status + timings, tool versions
  00_source/input.pdf
  10_pages/            # rasterized page images
  20_clean/            # preprocessed page images
  30_ir/raw.json       # BookIR straight from the engine
  40_ir/clean.json     # BookIR after cleanup
  50_build/book.md, book.epub
  60_report/report.json, report.html
```

- Each stage reads the previous stage's output and writes only its own folder.
- `rebind run <pdf> --from <stage>` re-runs from any stage. A stage is skipped if its inputs and config hash are unchanged.

### BookIR (the key abstraction)

An engine-neutral intermediate representation. Cleanup and build work only on BookIR, never on engine-specific output.

```python
Block:
  id: str
  kind: heading | paragraph | footnote | caption | table | image | list_item | page_header | page_footer | page_number | other
  level: int | None            # heading level
  text: str
  page: int                    # source page index
  bbox: (x0, y0, x1, y1) | None
  confidence: float | None     # when the engine exposes it
  attrs: dict                  # engine extras (table cells, image path, footnote ref)
BookIR:
  meta: {title, authors, language, isbn, ...}
  pages: [{index, width, height, image_path}]
  blocks: [Block]              # reading order
```

Define it with Pydantic v2 and version the schema (`ir_version`).

## 4. Stages in detail

### 4.1 ingest

- Copy the PDF into the job folder, hash it, and record the page count and embedded image DPI.
- Detect whether the PDF already has a usable text layer (warn the user, don't bail).

### 4.2 preprocess

- Rasterize with `pdftoppm` at 300 dpi by default (configurable), or extract the native images with `pdfimages` when they are already at book resolution.
- Spread detection: if a page's aspect ratio is about 2× portrait, split it into two pages.
- unpaper: deskew, remove dark scan borders, despeckle, normalize margins.
- Optional binarization/contrast step (off by default; some engines prefer grayscale).
- Design this as a sub-pipeline of small ops, so a ScanTailor-fork CLI can be added later as an alternate backend.

### 4.3 ocr (engine plugin)

- `Engine` protocol: `name`, `version`, `capabilities`, and `convert(pages: list[Path], cfg) -> BookIR`.
- Register engines via Python entry points (`rebind.engines`) so third-party plugins can be installed separately.
- Docling engine (default): map Docling's document labels straight onto BookIR kinds. Docling's page-header and page-footer labels give header removal for free; heuristics in 4.4 are the fallback.
- Choose the device automatically (CUDA → MPS → CPU), overridable in config.
- Cache model weights in a mounted volume, never re-downloading on each run.

### 4.4 cleanup (where most of the value is)

Each rule is a separate, unit-tested function `IR -> IR` that can be switched on or off per profile and records what it changed (for the report).

1. Drop furniture: remove `page_header`, `page_footer` and `page_number` blocks.
2. Running-header heuristic (fallback): take the first and last lines on each page, normalize digits and case, and drop strings that repeat on more than ~30% of pages.
3. Hyphenation join: a line ending in `-` followed by a lowercase start. Join them if the combined word is in the dictionary (`wordfreq` or hunspell). Keep the hyphen if the hyphenated form is more common (real compounds).
4. Cross-page paragraph merge: if a page's last paragraph ends without terminal punctuation and the next page's first paragraph starts in lowercase, merge them.
5. Whitespace and typography: normalize whitespace, ligatures (ﬁ → fi), curly quotes, em dashes, and ellipses. Keep the original language's conventions.
6. Footnotes: link footnote markers to footnote blocks and render them as EPUB 3 footnotes (`epub:type="noteref"` / `"footnote"`). Unmatched markers go in the report.
7. Chapters: split on top-level headings. Fall back to a regex for "Chapter N", "CHAPTER IV", and so on.
8. Front matter: detect the title page, copyright page and table of contents. The scanned TOC is dropped by default because the EPUB has its own.

### 4.5 build

- Render BookIR to Pandoc Markdown (or HTML for tables and footnotes where Markdown is lossy).
- Run `pandoc` with EPUB 3 output, a metadata YAML file, a cover (user-supplied, or the first page image), the bundled CSS, and a TOC depth from config.
- Optional: run Calibre's `ebook-convert` to produce AZW3 (an extra, not bundled in the slim image).

### 4.6 validate and report

- Run `epubcheck`. Errors fail the job; warnings go in the report.
- Quality flags for each page:
  - Low mean OCR confidence (when available).
  - Character count far off the book median (missed or duplicated text).
  - Low dictionary-word ratio (garbled OCR).
  - Empty page that isn't intentionally blank.
  - Leaked header/footer candidates, unmatched footnotes, unbalanced quotes or brackets.
- Output `report.json` (machine-readable) and `report.html` (thumbnail of each flagged page next to its extracted text).
- Give the book an overall score so regressions are easy to spot.

## 5. Config and profiles

- A single `rebind.toml`, overridable by CLI flags. Validated with Pydantic.
- Profiles are presets that change preprocessing and cleanup settings:
  - `novel`: single column, minimal footnotes.
  - `nonfiction`: footnotes, a figure here and there.
  - `academic`: footnotes, tables, equations.
  - `two-column`.
- Example:

```toml
profile = "novel"
dpi = 300
engine = "docling"
device = "auto"
[metadata]
title = "..."
authors = ["..."]
language = "en"
[cleanup]
hyphenation = true
running_header_threshold = 0.3
```

## 6. CLI

```
rebind run book.pdf [--profile novel] [--title ... --author ...] [--from cleanup] [--out ./out]
rebind watch ./inbox --out ./outbox        # watch-folder mode for Docker
rebind report jobs/<slug>                  # rebuild/open the HTML report
rebind engines                             # list installed engines + devices
rebind doctor                              # check external tools (pandoc, unpaper, epubcheck, poppler)
```

## 7. Tech stack

- Python 3.12, `uv` for env and deps, `typer` (CLI), `pydantic` v2, `rich` (progress output).
- External tools: poppler-utils, unpaper, pandoc, epubcheck (needs a Java runtime).
- Docling (default engine). `wordfreq` for the dictionary checks.
- Quality tooling: `ruff`, `pyright`, `pytest`, `pytest-cov`.

## 8. Repo layout

```
rebind/
  README.md  LICENSE  THIRD_PARTY_LICENSES.md  PLAN.md  CONTRIBUTING.md
  pyproject.toml  uv.lock  rebind.example.toml
  src/rebind/
    cli.py  config.py  manifest.py  ir.py
    stages/ ingest.py preprocess.py ocr.py cleanup/ build.py validate.py report.py
    stages/cleanup/ furniture.py headers.py hyphenation.py paragraphs.py typography.py footnotes.py chapters.py
    engines/ base.py docling_engine.py
    assets/ epub.css report.html.j2
  tests/
    unit/                      # cleanup rules on synthetic IR
    integration/               # tiny 5-page PDF end-to-end
    corpus/                    # manifest of public-domain books + ground-truth sources (not the files)
  docker/
    Dockerfile.cpu  Dockerfile.cuda  compose.yml
  docs/  profiles.md  engines.md  writing-an-engine.md
  .github/workflows/  ci.yml  release.yml  corpus.yml
```

## 9. Docker, CI and quality measurement

### Docker

- `Dockerfile.cpu`: `python:3.12-slim` plus poppler-utils, unpaper, pandoc and a headless JRE (for epubcheck). Multi-arch (amd64 and arm64).
- `Dockerfile.cuda`: NVIDIA CUDA runtime base, same tools.
- `compose.yml`: one `rebind watch` service with `inbox/`, `outbox/`, `jobs/` and `models/` volumes, plus a GPU profile.
- Publish to GHCR on tagged releases.

### CI (GitHub Actions)

- On every PR: ruff, pyright, unit tests, and the integration test on a tiny public-domain PDF (CPU).
- On tags: build and push the images, then create a GitHub release.
- Weekly / manual (`corpus.yml`): run the full corpus benchmark and post scores as an artifact.

### Ground-truth benchmark

- Pair Internet Archive scans of public-domain books with the matching Project Gutenberg text, ideally the same edition.
- Metrics: character error rate (CER) and word error rate (WER) after normalization, header-leak count, and paragraph-break F1.
- Corpus targets: a plain novel, a footnote-heavy nonfiction book, a book with tables, a two-column book, and one poor-quality scan.
- The corpus manifest stores source URLs and checksums only. A script downloads the files, so no large binaries go in git.

## 10. Milestones

### M0 — Scaffold

- Repo, license, `pyproject`, CLI skeleton, config loading, BookIR models, manifest, `rebind doctor`.
- Done when: `uv run rebind doctor` reports tool status and CI is green.

### M1 — End-to-end happy path

- ingest → preprocess (pdftoppm + unpaper) → Docling → furniture drop → Pandoc → epubcheck.
- Done when: a public-domain novel scan produces an EPUB that passes epubcheck and opens in Calibre and Apple Books.

### M2 — Cleanup and report

- All cleanup rules in §4.4 with unit tests, the quality flags, and the HTML report.
- Done when: CER on the novel test book is measured and recorded, and flagged pages match spot checks.

### M3 — Packaging

- CPU and CUDA images, compose file, watch mode, the corpus benchmark workflow, and the README with before-and-after samples.
- Done when: `docker compose up` plus dropping a PDF in `inbox/` produces an EPUB on a clean machine.

### M4 — v0.1 release

- Profiles, docs, CONTRIBUTING guide, THIRD_PARTY_LICENSES, and a tagged release.

### Later

- v1: FastAPI backend, Redis + RQ job queue, web UI with upload, progress, and a review screen (page image beside editable text, rebuild on save).
- v2: olmOCR engine, ISBN metadata lookup (Open Library), OPDS feed and Calibre library output, optional LLM cleanup pass against any OpenAI-compatible endpoint (local or remote), and plugin docs for third-party engines.

## 11. Open questions

- Default DPI and binarization: tune these against the corpus in M2.
- Equations: keep as images, or convert to MathML when the engine gives LaTeX?
- Non-English books: language detection for hyphenation dictionaries and typography rules.
- Apple Silicon: confirm Docling's MPS support performs well enough natively.

## 12. Implementation notes and decisions

Decisions made while building, recorded so the plan stays the source of truth.

- **rasterize is its own stage.** §3/§4.2 put rasterizing inside preprocess, but
  "one folder per stage" and `--from` work better split: `rasterize` writes
  `10_pages/`, `preprocess` writes `20_clean/`. Re-tuning unpaper no longer
  re-renders the PDF. Stage order: ingest, rasterize, preprocess, ocr, cleanup,
  build, validate.
- **Stage skipping** uses a chained key: hash(stage name, stage version,
  relevant config sections, stage-specific extras such as tool/engine versions,
  upstream stage key). Any re-run stage forces everything downstream.
- **Engine signature** is `convert(pages: list[Page], cfg, ctx) -> BookIR`
  (Page carries the image path plus size and source page; ctx gives a work dir
  for caches and a progress callback). The Docling engine caches each page's
  result, so an interrupted OCR run resumes page by page.
- **unpaper's gray filter is off by default** (`unpaper_args =
  ["--no-grayfilter"]`). On gray-paper scans it whitened patches between text
  lines and garbled OCR of whole lines.
- **No imaging dependency in the core.** unpaper writes only PNM; a small
  stdlib PNM→PNG converter (`imaging.py`) avoids adding Pillow.
- **Linux dev/CI uses CPU-only torch wheels** via `[tool.uv.sources]`; the CUDA
  image (M3) installs CUDA wheels itself.
- **Known Docling limitation (fixture page 1):** the first line next to a
  large drop cap is dropped entirely. M2's character-count flag should catch
  this class of loss.

### M2 decisions

- **Extra cleanup rule: `reading_order`** (runs right after furniture). On pages
  where no two blocks sit side by side, blocks are sorted top-to-bottom.
  Docling occasionally emitted a middle paragraph after the bottom one when
  their boxes overlapped by a few pixels; on the Jekyll benchmark this one rule
  took CER from 11.3% to 1.8% (moved text counts as deleted plus inserted).
- **Rule order:** furniture, reading_order, headers, typography, hyphenation,
  paragraphs, footnotes, chapters, front_matter. Text rules run before the
  cross-page merge; footnotes link on final text because they store offsets.
- **Paragraph merge** fires when the first paragraph has no terminal
  punctuation *or* the next one starts lowercase (§4.4 says "and"). On the
  benchmark scan many page breaks end in a comma or mid-clause and continue
  with a capitalised name or a quotation mark.
- **Hyphenation** joins a split word only if the joined form has wordfreq Zipf
  ≥ 2.0; otherwise it keeps the hyphen. wordfreq cannot score hyphenated forms
  directly, so "more common hyphenated form" (§4.4) is approximated this way.
- **Typography** curls quotes and removes spacing before `; : ! ?` for English
  only; other languages keep their printed conventions. Pandoc's `smart`
  extension is turned off so it cannot re-interpret quotes.
- **Report template uses `string.Template`**, not Jinja2 (§8 names
  `report.html.j2`): Jinja2 is not in §7, and the page is simple.
- **Quality flags** beyond §4.6: `garbled_text` (a run of non-words, usually one
  misread line; whole-page dictionary ratio barely moves for a single bad line)
  and `missing_start` (a paragraph right after a heading starting lowercase: the
  drop-cap line was lost). Single letters only count as words if they are real
  one-letter words in that language; wordfreq rates stray letters as common.
- **Benchmark:** `scripts/corpus.py` + `tests/corpus/manifest.toml`. CER uses a
  word-level difflib alignment with exact Levenshtein inside mismatched
  segments, so a whole book scores in seconds. Results are appended to
  `tests/corpus/results/<id>.json`; see `docs/benchmarks.md`.
- **Default OCR is pinned to RapidOCR (torch) with `Det.box_thresh = 0.3`**
  instead of Docling's "auto": same output on every platform, and the lower
  detector threshold recovers lines beside drop caps (all five chapter
  openings in the benchmark were lost at the default 0.5). Measured in
  `docs/benchmarks.md`; `Det.unclip_ratio = 2.0` was tried and rejected.
- **M2 done-criteria:** CER on the novel test book is 1.69% (recorded in
  `tests/corpus/results/jekyll-hyde.json`); flagged pages were checked against
  per-page error rates from the ground truth (9/10 worst pages flagged, no
  flagged page under 2% error) and by viewing flagged page images.
