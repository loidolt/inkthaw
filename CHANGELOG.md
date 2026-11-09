# Changelog

## 0.2.0 (2026-11-09)

M5: fewer external tools, plus fixes from a code review.

### Changed

- **Renamed from rebind to inkthaw.** The package, the CLI command, the Python
  import (`inkthaw`), the config file (`inkthaw.toml`), the environment
  variables (`INKTHAW_MODELS_DIR`, `INKTHAW_REQUIRE_EPUBCHECK`, `INKTHAW_UID`,
  `INKTHAW_GID`, `INKTHAW_IMAGE`, `INKTHAW_GPU_IMAGE`), the `inkthaw.engines`
  entry-point group, the error class (`InkthawError`), the Compose services and
  the models marker (`.inkthaw-models.json`) all changed. Rename an existing
  `rebind.toml` to `inkthaw.toml` and `.rebind-models.json` in your models
  folder to `.inkthaw-models.json` (or the models download again). Old job
  manifests still load; their `rebind_version` field is ignored.
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
- The EPUB is written in-process by a native EPUB 3 writer (`inkthaw.epub`,
  standard library + Pillow): chapters split at `build.split_level`,
  `nav.xhtml` and `toc.ncx` honouring `build.toc_depth`, OPF metadata, cover
  page, bundled and extra CSS, EPUB 3 pop-up footnotes, tables, figures and
  front matter. pandoc is no longer required; `build.backend = "pandoc"` keeps
  the old path for anyone who wants it. Note numbers are sequential through
  the book, as with pandoc; the material before the first heading no longer
  gets the book title as an extra heading (the title page carries it).
- `inkthaw doctor` lists the built-in libraries; no external tool is required
  any more. The Docker images no longer install poppler, unpaper or pandoc.
- The ingest, rasterize, preprocess, build and validate stage versions changed, so
  existing jobs re-run from ingest once (OCR results stay cached per page
  image where the image is unchanged).

### Fixed

- The page mask no longer erases real text: a second text column, a footnote
  block or a heading set well apart from the body was whitened before OCR.
  Only small marks near the page edge are masked now.
- A page Docling fails on is no longer cached as an empty page; the next run
  retries it (pages cached that way by 0.1.0 are retried too). The OCR stage
  reports `failed_pages`.
- After a paragraph was merged across a page break, the next paragraph on
  the new page was merged into it too whenever the text allowed.
- Suspended hyphens are kept as printed: "nineteenth- and twentieth-century"
  no longer becomes "nineteenth-and twentieth-century" (coordinating words
  for en, de, fr, es, it and nl; other languages use the English set).
- Chapter titles set with a period ("THE CAREW MURDER CASE.") are no longer
  demoted to paragraphs. A period-terminated heading stays a heading when it
  is short, has no other sentence punctuation and is followed by body prose;
  letter sign-offs ("HASTIE LANYON.") are still demoted.

he
Release workflow failed on the CUDA image, so the release job and the `-cuda`
image were skipped. 0.2.0 is the first published release.

### Pipeline

- `inkthaw run book.pdf`: ingest, rasterize (spread splitting), preprocess
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
  a 0–100 score. `inkthaw report <job> --open`.
- Profiles: `novel`, `nonfiction`, `academic`, `two-column`.
  `inkthaw profiles`, `inkthaw config`.

### Running it

- `inkthaw watch` watch-folder mode with per-book sidecar settings.
- Docker images (CPU: amd64 and arm64; NVIDIA CUDA: amd64) and `compose.yml`.
- `inkthaw models` and `models_dir` for offline use; `inkthaw doctor`,
  `inkthaw engines`.

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
