# inkthaw — Project Plan

Turn scanned PDFs into clean, reflowable EPUBs. Fully open source, free, self-hostable.

Repo name: `inkthaw` (a scanned book, taken apart and rebound as an ebook).

## 1. Goals and non-goals

### Goals

- One command takes a scanned PDF and produces a valid EPUB 3, plus a quality report flagging the pages that need human review.
- Runs anywhere: CPU-only Linux, NVIDIA GPU, and Apple Silicon (native, outside Docker).
- Every stage is resumable and inspectable, and intermediate files are kept.
- The OCR/layout engine is pluggable. The default engine has a permissive license.
- Quality is measured, not guessed: regression tests against public-domain ground truth.
- Usable without knowing Docker or a terminal: native desktop apps (macOS, then Windows) that use the
  machine's own hardware, and mobile companion apps (iOS, then Android). See §10.

### Non-goals (for now)

- A hosted conversion service. inkthaw stays self-hosted: books never leave the user's own machines.
- Running the OCR pipeline on phones. Mobile apps are clients of the user's own inkthaw server (§10.5).
- DRM, ebook stores, or anything aimed at copyrighted material the user doesn't own.
- Perfect output on every book with no review. The aim is to make review fast.

## 2. Licensing rules

- Project license: Apache-2.0.
- Bundled engines must be permissively licensed. Default engine: Docling (MIT). Planned optional engine: olmOCR (Apache-2.0).
- marker (GPL code, model weights with restrictions) and MinerU (verify current license) are never bundled. They may be supported later as separately installed plugins only.
- Nothing GPL ships inside the desktop or mobile app bundles. GPL terms conflict with App Store
  distribution, and every bundled GPL binary carries a source-offer obligation. GPL tools may still be
  used when the user installs them separately (as Calibre is today).
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
- `inkthaw run <pdf> --from <stage>` re-runs from any stage. A stage is skipped if its inputs and config hash are unchanged.

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

- Rasterize with PDFium (`pypdfium2`) at 300 dpi by default (configurable), or extract the native images when they are already at book resolution. (Poppler's `pdftoppm`/`pdfimages` until M5.)
- Spread detection: if a page's aspect ratio is about 2× portrait, split it into two pages.
- Clean-up: deskew, remove dark scan borders, despeckle. Built in (numpy + Pillow) since M5; unpaper remains an optional backend.
- Optional binarization/contrast step (off by default; some engines prefer grayscale).
- Design this as a sub-pipeline of small ops, so a ScanTailor-fork CLI can be added later as an alternate backend.

### 4.3 ocr (engine plugin)

- `Engine` protocol: `name`, `version`, `capabilities`, and `convert(pages: list[Path], cfg) -> BookIR`.
- Register engines via Python entry points (`inkthaw.engines`) so third-party plugins can be installed separately.
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

- Write EPUB 3 directly from BookIR (`inkthaw.epub`, native writer since the M5 follow-up; §13): XHTML
  chapters split at a heading level, `nav.xhtml` + `toc.ncx` to a TOC depth from config, OPF metadata,
  a cover (user-supplied, or the first page image), the bundled CSS, EPUB 3 footnotes.
- Optional backend (`build.backend = "pandoc"`): render BookIR to Pandoc Markdown and run `pandoc`
  with EPUB 3 output and a metadata YAML file. Never used by the apps (GPL, §2).
- Optional: run Calibre's `ebook-convert` to produce AZW3 (an extra, not bundled in the slim image).

### 4.6 validate and report

- Run `epubcheck` when it and Java are installed (skipped with a note in the report otherwise, M5). Errors fail the job; warnings go in the report.
- Quality flags for each page:
  - Low mean OCR confidence (when available).
  - Character count far off the book median (missed or duplicated text).
  - Low dictionary-word ratio (garbled OCR).
  - Empty page that isn't intentionally blank.
  - Leaked header/footer candidates, unmatched footnotes, unbalanced quotes or brackets.
- Output `report.json` (machine-readable) and `report.html` (thumbnail of each flagged page next to its extracted text).
- Give the book an overall score so regressions are easy to spot.

## 5. Config and profiles

- A single `inkthaw.toml`, overridable by CLI flags. Validated with Pydantic.
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
inkthaw run book.pdf [--profile novel] [--title ... --author ...] [--from cleanup] [--out ./out]
inkthaw watch ./inbox --out ./outbox        # watch-folder mode for Docker
inkthaw report jobs/<slug>                  # rebuild/open the HTML report
inkthaw engines                             # list installed engines + devices
inkthaw doctor                              # check libraries and external tools (all optional: epubcheck, unpaper, pandoc)
inkthaw serve [--host ...] [--port ...]     # HTTP API + web UI (M6/M7)
```

## 7. Tech stack

- Python 3.12, `uv` for env and deps, `typer` (CLI), `pydantic` v2, `rich` (progress output).
- PDF and images in-process: `pypdfium2` (PDFium), Pillow, numpy (M5).
- External tools: none required. Optional: epubcheck with a Java runtime, unpaper, pandoc.
- Docling (default engine). `wordfreq` for the dictionary checks.
- Quality tooling: `ruff`, `pyright`, `pytest`, `pytest-cov`.
- Server (M6): FastAPI, SQLite for the job queue and state.
- UI (M7 on): SvelteKit (static build) on [loidolt-theme](https://theme.loidolt.space)
  (`@loidolt/theme-svelte`); Tauri 2 for desktop, Capacitor for mobile (§10).

## 8. Repo layout

```
inkthaw/
  README.md  LICENSE  THIRD_PARTY_LICENSES.md  PLAN.md  CONTRIBUTING.md
  pyproject.toml  uv.lock  inkthaw.example.toml
  src/inkthaw/
    cli.py  config.py  manifest.py  ir.py
    stages/ ingest.py preprocess.py ocr.py cleanup/ build.py validate.py report.py
    stages/cleanup/ furniture.py headers.py hyphenation.py paragraphs.py typography.py footnotes.py chapters.py
    engines/ base.py docling_engine.py
    server/                    # FastAPI app, job queue, pairing (M6, M8)
    assets/ epub.css report.html.j2
  app/                         # SvelteKit UI (M7)
    src-tauri/                 # desktop shell + Python sidecar config (M8)
    ios/  android/             # Capacitor projects (M9, M10)
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

- `Dockerfile.cpu`: `python:3.12-slim` plus a headless JRE with epubcheck (poppler and unpaper dropped in M5, pandoc after the native EPUB writer). Multi-arch (amd64 and arm64).
- `Dockerfile.cuda`: NVIDIA CUDA runtime base, same tools.
- `compose.yml`: one `inkthaw watch` service with `inbox/`, `outbox/`, `jobs/` and `models/` volumes, plus a GPU profile.
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

## 10. Distribution and apps

### 10.1 Why native apps

Docker asks users to understand containers, volumes and UIDs, and on macOS it costs speed: Docker
Desktop runs a Linux VM with no Metal access, so Docling falls back to CPU. Natively on an Apple
M-series Mac a page takes about 3 seconds; in a 2-CPU container about 6 (`docs/engines.md`). Native
also opens up Apple Vision OCR (`ocrmac`, already an option) on the Neural Engine. On Windows, Docker
Desktop with WSL2 does pass CUDA through, so a native Windows app is about ease of install more than
speed.

### 10.2 Ways to run inkthaw

| Surface | For | Backend | Ships |
|---|---|---|---|
| CLI (`uvx inkthaw`, `pipx`, Homebrew) | technical users, scripts | local Python | M5 |
| Docker (watch folder, `inkthaw serve`) | NAS and server self-hosters | container | M3, web UI from M7 |
| Desktop app (macOS, then Windows) | everyone else | bundled Python sidecar | M8, M10 |
| Mobile app (iOS, then Android) | capture and review on the go | the user's desktop app or Docker server | M9, M10 |

Docker stays: it is the right fit for always-on home servers. The apps do not replace it.

### 10.3 One UI, one API

```
SvelteKit static build (@loidolt/theme-svelte)
  ├── browser                       ── served by inkthaw serve (CLI / Docker) ──┐
  ├── Tauri 2 (macOS / Windows)     ── local Python sidecar ───────────────────┼──► FastAPI /api/v1
  └── Capacitor (iOS / Android)     ── paired server over LAN / Tailscale ─────┘
```

- The versioned HTTP API (`/api/v1`, OpenAPI) is the contract. The web UI, desktop app and mobile app
  all speak it the same way; the CLI keeps calling the pipeline directly.
- Single-user, local-first: an in-process job queue on SQLite instead of the Redis + RQ queue the plan
  used to call for. A separate queue can come later if multi-worker servers need it.
- Token auth from the start, because mobile clients connect over the network.

### 10.4 Shells and the theme

- **UI kit:** [loidolt-theme](https://theme.loidolt.space) (MIT; fonts Jost and Archivo, OFL). Its
  inspector layout, lightbox and drawer suit the review screen (page image beside editable text).
- **Mobile shell: Capacitor.** `@loidolt/theme-capacitor` already handles system bars, the Android back
  button, keyboard, haptics, safe areas and deep links.
- **Desktop shell: Tauri 2.** Capacitor has no first-party desktop target. Tauri gives small binaries,
  a sidecar for the frozen Python backend, and an updater. Tauri's mobile targets are not used: the
  theme's Capacitor work already covers mobile.
- **New theme package `@loidolt/theme-tauri`**, built in the loidolt-theme repo alongside M8, on the
  same pattern as the Capacitor one (plugins passed in, inert in a browser, no inkthaw-specific code):
  overlay title bar clear of the macOS window buttons (via the `--ldt-safe-*` knobs) and drag regions
  on `Topbar`; window background and appearance following the system theme (no white flash); native
  menu bar wired to app commands and shortcuts; native file dialogs and file drop onto the window; OS
  notifications; single instance, deep links, and an optional tray icon for watch mode.
- **Stays in inkthaw, not the theme:** the document-scanner plugin (VisionKit on iOS, ML Kit on
  Android), device pairing (QR code with a token, mDNS discovery), and the API client. Generic native
  pieces (share sheet, file picker) go to the theme.

### 10.5 Mobile: what was considered

- **Companion client (chosen).** The phone captures pages, uploads them to the user's own server,
  shows progress, supports review, and sends the EPUB to Books or Play Books. Reuses the UI and API.
- **On-device "lite" pipeline (maybe later).** Native OCR (Apple Vision, ML Kit) plus a port of cleanup
  and EPUB build. Docling, the quality advantage, is Python + torch and has no iOS or Android build,
  so this means a second implementation of the pipeline. Phones also kill long background jobs; a
  300-page book at about 3 s/page is around 15 minutes.
- **Hosted cloud (rejected).** Server costs, and users uploading copyrighted books to our servers would
  make us a host with takedown and liability exposure. Self-hosting avoids that.

Camera capture (VisionKit / ML Kit document scanner producing a PDF) lets people without a scanner
inkthaw a book they own. It is likely the main reason to have a mobile app.

## 11. Milestones

### M0 — Scaffold

- Repo, license, `pyproject`, CLI skeleton, config loading, BookIR models, manifest, `inkthaw doctor`.
- Done when: `uv run inkthaw doctor` reports tool status and CI is green.

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

### M5 — Fewer external tools, easy install

Status: done except publishing (draft PyPI job and Homebrew formula; see the
M5 decisions in §13).

- Replace poppler (`pdfinfo`, `pdfimages`, `pdftoppm`) with `pypdfium2` (Apache-2.0/BSD-3, wheels for
  every platform).
- Replace unpaper with in-process deskew, border removal and despeckle (OpenCV or equivalent,
  permissive license); keep unpaper as an optional backend for users who install it. This revisits
  the "no imaging dependency in the core" decision (§13).
- pandoc: bundle the static binary in app builds only if a native EPUB writer is not simpler (open
  question, §12). pandoc is GPL, so it cannot go in the iOS build either way. *Done after M5: native
  EPUB writer, pandoc optional (§13).*
- epubcheck becomes optional: run when Java + EPUBCheck are found, otherwise skip with a note in the
  report. App builds may bundle a trimmed `jlink` runtime later.
- Publish to PyPI (`uvx inkthaw`, `pipx install inkthaw`) and add a Homebrew formula.
- Done when: `uvx --from 'inkthaw[docling]' inkthaw run book.pdf` works on a clean Mac with nothing from
  Homebrew, uses MPS, and the corpus CER does not get worse.

### M6 — Server and API

- `inkthaw serve`: FastAPI with a versioned OpenAPI contract (`/api/v1`), token auth, upload, per-job
  progress events (SSE), job artifacts (EPUB, report, page images, IR), and rebuild after edits.
- In-process job queue on SQLite; the watch folder feeds the same queue.
- Done when: a job submitted over the API produces the same job folder as `inkthaw run`, and API
  contract tests run in CI.

### M7 — Web UI

- SvelteKit static build on `@loidolt/theme-svelte`, served by `inkthaw serve` and in the Docker images:
  upload, queue and progress, the quality report, and a review screen (page image beside editable text,
  rebuild on save).
- Add the theme and its fonts to `THIRD_PARTY_LICENSES.md`.
- Done when: a book can be converted, reviewed, fixed and rebuilt entirely in the browser, and the
  axe accessibility checks pass.

### M8 — macOS app

- Tauri 2 shell around the M7 UI, with the Python backend frozen as a sidecar. Apple Silicon (arm64)
  only; signed, notarized DMG; auto-updates; model weights downloaded on first launch.
- Acts as the home server for phones: listens on the LAN, mDNS discovery, QR-code pairing.
- `@loidolt/theme-tauri` built in the loidolt-theme repo alongside (§10.4).
- Done when: on a clean Mac with no Homebrew or Python, dragging a PDF onto the window produces an
  EPUB using MPS, and a second device can pair.

### M9 — iOS companion

- Capacitor app on the M7 UI with `@loidolt/theme-capacitor`. Pairs with the desktop app or a Docker
  server; camera capture with VisionKit into a PDF; upload, progress, review; share the EPUB to Books.
- Done when: a TestFlight build converts a phone-captured chapter through a paired Mac.

### M10 — Windows and Android

- Windows Tauri build (ML runtime per §12) and an Android Capacitor build with the ML Kit document
  scanner. Mostly packaging once the shells exist.

### Later

- On-device "lite" pipeline for phones, only if users ask for it (§10.5).
- olmOCR engine, ISBN metadata lookup (Open Library), OPDS feed and Calibre library output, optional
  LLM cleanup pass against any OpenAI-compatible endpoint (local or remote), and plugin docs for
  third-party engines.

## 12. Open questions

- Default DPI and binarization: tune these against the corpus in M2.
- Equations: keep as images, or convert to MathML when the engine gives LaTeX?
- Non-English books: language detection for hyphenation dictionaries and typography rules.
- Apple Silicon: MPS works natively at about 3 s/page (`docs/engines.md`). Still open: does Apple
  Vision OCR (`ocrmac`) beat pinned RapidOCR on the corpus, and is it worth giving up identical output
  across platforms on Macs?
- ~~unpaper replacement: can in-process preprocessing match unpaper's CER on the corpus?~~ Settled in M5 (§13).
- ~~pandoc: bundle the binary, or write EPUB 3 directly from BookIR?~~ Settled in M5: write EPUB 3
  directly, before M8 (§13). Implemented: the native writer is the default.
- Python sidecar freezer: PyInstaller or Briefcase? Watch bundle size (torch alone is about 400 MB on
  macOS arm64) and signing/notarization of the bundled native libraries.
- Windows ML runtime: CPU torch with an optional CUDA download (the CUDA build is about 2.5 GB), or
  move inference to ONNX Runtime (DirectML covers AMD and Intel GPUs too)?
- LAN pairing and TLS: self-signed certificate pinned at pairing time, or plain HTTP limited to the
  local network plus token? iOS needs the local-network permission prompt either way.
- Signing costs and accounts: Apple Developer Program, and a Windows code-signing route (Azure
  Trusted Signing is the cheap option).

## 13. Implementation notes and decisions

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
  stdlib PNM→PNG converter (`imaging.py`) avoids adding Pillow. *(Superseded in
  M5: Pillow and numpy are core dependencies now; see M5 decisions.)*
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

### M3 decisions

- **`compose.yml` lives at the repository root** (not `docker/`), so the
  done-criterion command is literally `docker compose up`. Dockerfiles are in
  `docker/`.
- **Model weights:** with `models_dir` (or `INKTHAW_MODELS_DIR`, set to
  `/models` in the images) the Docling engine downloads exactly the weights it
  needs (layout, TableFormer, RapidOCR for the configured languages) once and
  then runs offline via Docling's `artifacts_path`. `inkthaw models` prefetches;
  `inkthaw watch` prefetches at start-up. Images can bake weights in with
  `--build-arg BAKE_MODELS=1`.
- **Watch mode polls** (no new dependency such as watchdog): a PDF is taken
  once its size and mtime are unchanged between two polls. Per-book settings
  come from a sidecar `<name>.toml`. SIGTERM stops between stages; jobs resume.
- **Debian's EPUBCheck is 4.2.6** and is installed as a bare `.jar` symlink;
  tools that resolve to a `.jar` are run with `java -jar`. (Homebrew ships
  5.x; both validate EPUB 3.)
- **CUDA image** swaps the lock file's CPU torch for the CUDA 12.8 build of
  the same version. It was linted but not built or run here (no NVIDIA GPU on
  the development machine); the release workflow builds it.
- **Image size:** about 2.6 GB uncompressed for the CPU image, mostly torch
  (690 MB), transformers, scipy and the JRE.

### M4 decisions

- **Profiles** now differ in more than one switch: `novel` has a chapters-only
  TOC; `nonfiction`, `academic` and `two-column` turn on footnote linking and
  tables; `academic` relaxes the dictionary-based flags; `two-column` relaxes
  the "too much text" flag. `inkthaw profiles` lists them and `inkthaw config`
  prints the merged settings as TOML (round-trip tested).
- **Footnotes on real data:** a 12-page Gibbon excerpt (numbered notes plus
  editor's `*` notes) linked 27 of 36 notes after two fixes: references right
  after a closing quote or spaced off by OCR are found, and paragraphs merged
  across pages record `page_offsets`, so a note looks for its marker on its
  own page first. The remaining 9 have OCR-damaged markers and are reported.
- **License guard:** `scripts/check_licenses.py` runs in CI against the
  installed packages and inside the CPU image.
- **Removed** the unused `ocr.page_batch` option.
- **Release:** version 0.1.0, tag `v0.1.0`. Pushing the tag runs
  `release.yml` (GHCR images and a GitHub release).

### M5 decisions

- **PDF access: pypdfium2 (PDFium).** Apache-2.0 / BSD-3-Clause, wheels for
  Linux, macOS, Windows, iOS and Android builds exist, and its bundled
  libraries are all permissive. It replaces `pdfinfo`, `pdfimages`,
  `pdftotext` and `pdftoppm` (and `pdfseparate`/`pdfunite` in the corpus
  script). PDFium is not thread-safe, so calls hold one process-wide lock;
  rendering is ~40 ms a page, PNG encoding runs outside the lock. PDFium
  reports page sizes after `/Rotate`; `pdf.inspect` swaps them back so
  `info.json` keeps poppler's meaning. PDFium's default rendering options
  are used.
- **Preprocessing: numpy + Pillow, not OpenCV.** This revisits "no imaging
  dependency in the core": Pillow (MIT-CMU) and numpy (BSD) are now core
  dependencies (~35 MB of wheels), and Docling already pulls both. OpenCV was
  rejected: `opencv-python-headless` is Apache-2.0, but its wheels are 120 MB
  and bundle FFmpeg, and the macOS arm64 wheel's FFmpeg is built with
  `--enable-gpl` (x264/x265), so it could not go into an app bundle (§2).
  scipy was not needed either; the few operations (block means, box sums,
  projection profiles) are plain numpy.
- **Built-in backend steps, in order:** dark-border removal (dense regions
  grown from the page edge on a ~0.7 mm grid), despeckle (≤ 4 dark pixels with
  clean paper around them), deskew (projection-profile search ±2°, only when
  the page has a clear text-line peak, so stamps and pictures are left alone),
  mask and centre the main text area, and `soften` (bicubic quarter-pixel
  resample). The last two came from measuring what unpaper does that helps
  Docling: centring stops Docling from splitting paragraphs at their last line,
  and unpaper's near-universal resampling anti-aliases bitonal scans, which
  RapidOCR reads better. Each step has a switch in `[preprocess]`.
- **Corpus result:** CER 1.82% with the M5 defaults against 1.66% for the
  poppler + unpaper baseline re-run on the same machine; paragraph F1 0.966
  (was 0.962), no header leaks (was 1), 31 flagged pages (was 37). unpaper on
  PDFium pages scores 1.89%, so the built-in backend is not behind unpaper;
  the remaining gap is the rasterizer (poppler draws slightly heavier strokes)
  and is about four garbled lines on this book (darkening PDFium's output
  closed half of it, 1.75%, at a cost in paragraph F1; not adopted on one
  book's evidence). Accepted for M5 because
  dropping poppler is what makes wheel-only installs and app bundles possible;
  a second corpus book should confirm it (docs/benchmarks.md has every run).
- **unpaper stays an optional backend** (`preprocess.backend = "unpaper"`).
  The old `preprocess.unpaper = false` still loads and means `backend =
  "none"`; `unpaper = true` now means the built-in backend.
- **EPUBCheck is optional.** It runs when `epubcheck` is on PATH and `java
  -version` works (macOS's `/usr/bin/java` stub does not count). Otherwise the
  report records `"skipped": true` with the reason and the stage warns.
  `validate.require_epubcheck = true` makes it mandatory; CI sets
  `INKTHAW_REQUIRE_EPUBCHECK=1` for the integration test so validation is never
  silently skipped there.
- **pandoc: write EPUB 3 directly from BookIR, before M8; keep pandoc for
  now.** Bundling pandoc is ruled out for the desktop and iOS apps (GPL, §2),
  so the apps need a native writer regardless, and once it exists bundling
  pandoc buys nothing for the CLI either. The writer is not a quick swap:
  chapter splitting, `nav.xhtml` with the TOC depth, OPF metadata, cover,
  EPUB 3 footnotes, tables and images, all validated with EPUBCheck and
  checked against the corpus. That is its own piece of work, so M5 keeps
  pandoc as the one required external tool for CLI and Docker users. *(Done
  right after M5: see "Native EPUB writer decisions" below.)*
- **Licence check covers bundled native code.** `scripts/check_licenses.py`
  now lists permissive wheels that bundle copyleft native libraries
  (`opencv-python-headless`, pulled in by RapidOCR) as warnings, and `--app`
  fails on them. M8 has to replace or strip that wheel before the Python
  sidecar can ship.
- **Packaging.** `release.yml` gains a draft PyPI job (trusted publishing,
  gated on the repository variable `PYPI_PUBLISH`); the name `inkthaw` was free
  on PyPI on 2026-11-08. `packaging/homebrew/inkthaw.rb` is a draft tap formula
  that pip-installs `inkthaw[docling]` into a virtualenv (resource blocks for
  ~120 packages including torch are not practical); homebrew-core would need a
  Docling-free package first. On Linux, PyPI's torch is the CUDA build, so the
  Docker CPU image stays the light option there. CI gains a `wheel` job that
  runs the built wheel on Linux and macOS with no external tools.
- **Not verified here:** the `uvx --from 'inkthaw[docling]' inkthaw run` path on
  a clean Mac (nothing is on PyPI yet); the built wheel was run with only
  `/usr/bin:/bin` on PATH up to the preprocess stage, and the full pipeline
  with only pandoc, EPUBCheck and Java on PATH (integration test, MPS for the
  corpus run).

### Native EPUB writer decisions (after M5, before M8)

- **EPUB 3 is written in-process (`inkthaw.epub`); pandoc is optional.** The
  writer uses only the standard library (`zipfile`, `html.escape`, string
  building) plus Pillow, already a core dependency, to read the cover's size
  and to convert images that are not EPUB core media types to PNG. No new
  dependency, so the desktop and iOS bundles can build EPUBs (§2).
  `build.backend = "native"` is the default; `"pandoc"` keeps the old
  Markdown path (`book.md`, `metadata.yaml`, pandoc ≥ 3) for comparison.
  `tools.py` marks pandoc optional, so `inkthaw doctor` no longer requires any
  external tool. Build stage version 3; the backend is part of its key.
- **Same container layout as pandoc** (`EPUB/content.opf`, `nav.xhtml`,
  `toc.ncx`, `text/chNNN.xhtml`, `styles/`, `media/`) and the same spine
  (cover, title page, nav, chapters), so reader behaviour stays as it was.
  `toc.ncx` is included for EPUB 2 readers; it was cheap. The TOC nests by
  heading level and puts a skipped level (h1 → h3) under the nearest
  shallower entry; if `toc_depth` leaves no entries, every chapter file is
  listed instead (an empty `<ol>` is invalid).
- **Deliberate differences from pandoc's output.** Material before the first
  heading gets no synthetic `<h1>` with the book title (pandoc adds one; the
  title page already shows it), but is listed in the TOC under the title.
  Heading ids are `h1`…`hN`, not slugs. A footnote is an `<aside
  epub:type="footnote">` at the end of the chapter that references it, with
  a backlink, numbered 1…n through the book as pandoc does; a note whose
  reference was never found stays in place as `div.footnote-text`, and a
  reference to a dropped note keeps its marker as plain text. `dc:date` is
  only written when `metadata.date` is set (pandoc used the build date as the
  publication date) and is normalised to W3CDTF or a bare year, with a
  warning otherwise. Accessibility metadata does not claim
  `alternativeText`: scanned figures have no alt text. No Apple
  display-options file. PNG/JPEG/GIF are stored in the zip, not deflated.
  `SOURCE_DATE_EPOCH` fixes `dcterms:modified` and zip timestamps.
- **Validation.** EPUBCheck 5.4.0 reports 0 errors and 0 warnings on the
  corpus book and on a synthetic book that uses every feature (front matter,
  lists, tables with captions, figures with and without captions, linked and
  unlinked footnotes, extra CSS, cover, three split/TOC settings;
  `tests/integration/test_epub_epubcheck.py`). The end-to-end integration
  test now runs with only EPUBCheck and Java on PATH.
- **Corpus.** CER 1.82%, paragraph F1 0.966, unchanged (the scorer reads
  `40_ir/clean.json`); the chapter text extracted from the native EPUB is
  identical to the pandoc EPUB's apart from the heading above
  (docs/benchmarks.md). Building takes 0.1 s instead of 0.75 s.
- **Not done:** page-list navigation and `epub:type="pagebreak"` markers from
  the source page numbers (BookIR has them, so this is a natural follow-up),
  and MathML.

### Name (after M5, before the first PyPI release)

- **The project is called inkthaw, not rebind.** A scan is a frozen picture
  of a page; inkthaw thaws it into text that flows. rebind was dropped before
  any account was registered: Rebind Publishing, LLC (rebind.ai, an AI-assisted
  ebook publisher of public-domain classics) has pending US trademark
  applications for REBIND and REBIND PUBLISHING covering e-book publishing,
  and at least four other 2026 PDF-to-EPUB projects and a KOReader plugin
  already use the name. inkthaw had no conflicts on PyPI, Homebrew, npm,
  crates.io or GitHub and no web or brand hits when checked (2026-11-08);
  inkthaw.com is registered for the project.
