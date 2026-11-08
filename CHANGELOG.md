# Changelog

## Unreleased (M5: fewer external tools)

### Changed

- PDFs are read and rendered in-process with PDFium (`pypdfium2`); poppler
  (`pdfinfo`, `pdfimages`, `pdftotext`, `pdftoppm`) is no longer needed.
- New built-in preprocess backend (numpy + Pillow): dark-border removal,
  despeckle, deskew, masking/centring of the text area, and slight
  anti-aliasing of glyph edges. It is the default; unpaper stays available with
  `preprocess.backend = "unpaper"`. The old `preprocess.unpaper = false` still
  works and means `backend = "none"`.
- EPUBCheck is optional: without it (or without a working Java runtime) the
  EPUB is still built and the report says validation was skipped.
  `validate.require_epubcheck = true` restores the old hard requirement.
- The EPUB is written in-process by a native EPUB 3 writer (`rebind.epub`,
  standard library + Pillow): chapters split at `build.split_level`,
  `nav.xhtml` and `toc.ncx` honouring `build.toc_depth`, OPF metadata, cover
  page, bundled and extra CSS, EPUB 3 pop-up footnotes, tables, figures and
  front matter. pandoc is no longer required; `build.backend = "pandoc"` keeps
  the old path for anyone who wants it. Note numbers are sequential through
  the book, as with pandoc; the material before the first heading no longer
  gets the book title as an extra heading (the title page carries it).
- `rebind doctor` lists the built-in libraries; no external tool is required
  any more. The Docker images no longer install poppler, unpaper or pandoc.
- The ingest, rasterize, preprocess, build and validate stage versions changed, so
  existing jobs re-run from ingest once (OCR results stay cached per page
  image where the image is unchanged).

### Added

- Draft PyPI publishing job (`release.yml`, off until a trusted publisher is
  configured) and a draft Homebrew formula in `packaging/homebrew/`.
- `scripts/check_licenses.py --app` fails on wheels that bundle copyleft
  native libraries (currently `opencv-python-headless`, via RapidOCR).

## 0.1.0 (2026-11-08)

First release.

### Pipeline

- `rebind run book.pdf`: ingest, rasterize (spread splitting), preprocess
  (unpaper), OCR (Docling), cleanup, build (Pandoc, EPUB 3), validate
  (EPUBCheck). Every stage writes its own folder in `jobs/<slug>/`; unchanged
  stages are skipped, `--from` / `--to` re-run part of the pipeline, and OCR
  resumes page by page.
- Cleanup rules: furniture removal, reading-order repair, running-header
  heuristic, typography (English: curly quotes, old-style spacing, quotes
  OCR'd as 66/99), dictionary-checked hyphen joins, cross-page and
  cross-column paragraph merging, EPUB 3 footnotes, chapter structure, front
  matter and scanned-contents removal.
- Quality report (`report.html`): flagged pages shown next to their text, with
  a 0–100 score. `rebind report <job> --open`.
- Profiles: `novel`, `nonfiction`, `academic`, `two-column`.
  `rebind profiles`, `rebind config`.

### Running it

- `rebind watch` watch-folder mode with per-book sidecar settings.
- Docker images (CPU: amd64 and arm64; NVIDIA CUDA: amd64) and `compose.yml`.
- `rebind models` and `models_dir` for offline use; `rebind doctor`,
  `rebind engines`.

### Quality

- Benchmark against public-domain ground truth (`scripts/corpus.py`):
  1.66% CER, 2.63% WER, paragraph F1 0.962 on *Strange Case of Dr. Jekyll
  and Mr. Hyde* (120 pages). See `docs/benchmarks.md`.

### Known limitations

- An occasional line is misread by the OCR recognizer; the report flags these
  pages.
- Footnotes are tested on a 12-page excerpt of Gibbon's *Decline and Fall*
  (27 of 36 notes linked; the rest have OCR-damaged markers) but not yet in
  the benchmark corpus.
- The CUDA image is built in CI but has not been run on a GPU by the
  maintainers yet.
- Binarization (`preprocess.binarize`) is not implemented.
- No web UI yet (planned for v1).
