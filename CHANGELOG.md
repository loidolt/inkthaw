# Changelog

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
