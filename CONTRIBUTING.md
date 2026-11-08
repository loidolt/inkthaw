# Contributing to rebind

Thanks for helping. rebind turns scanned books into EPUBs; the bar for changes
is that they make the output measurably better or the tool easier to run, and
that they keep the project freely licensable.

## Setup

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and pandoc ≥ 3.
EPUBCheck with a Java runtime is optional but recommended (CI runs it), and
unpaper only matters if you work on the `unpaper` preprocess backend. PDF
rendering and the default page clean-up are Python dependencies.

```bash
uv sync --all-extras
```

```bash
uv run rebind doctor
```

## Checks

CI runs all of these; please run them before opening a pull request.

```bash
uv run ruff check . && uv run ruff format --check .
```

```bash
uv run pyright
```

```bash
uv run pytest -m "not integration"
```

```bash
uv run pytest -m integration
```

The integration test converts `tests/fixtures/jekyll-5p.pdf` with Docling;
the first run downloads the models.

## How the code is organized

- `src/rebind/stages/`: one module per pipeline stage. A stage reads earlier
  stages' folders, writes only its own, and declares which config sections
  and tool versions affect its output (`config_keys`, `extra_key`); that is
  what lets unchanged stages be skipped. Bump a stage's `version` when you
  change what it produces.
- `src/rebind/stages/cleanup/`: one module per rule, each a pure function
  `(BookIR, Config) -> (BookIR, list[Change])`.
- `src/rebind/engines/`: the engine protocol and the Docling engine.
- `src/rebind/quality.py`, `report.py`: page flags and `report.html`.
- `src/rebind/metrics.py`, `scripts/corpus.py`: the ground-truth benchmark.

[PLAN.md](PLAN.md) has the design; its §13 records decisions made since.

## Adding or changing a cleanup rule

1. Write the rule as a function that returns a new `BookIR` (use
   `model_copy`; never mutate the input) plus a `Change` for every edit, so
   the change log and report stay truthful.
2. Give it an on/off switch in `CleanupConfig` and register it in
   `stages/cleanup/__init__.py`, where order matters (text fixes run before
   cross-page merges; footnote linking runs on final text).
3. Unit-test it on small synthetic `BookIR` fixtures in
   `tests/unit/test_cleanup_rules.py`, including the cases it must leave alone.
4. Run the benchmark before and after (below) and put both numbers in the
   pull request.

Language-specific behavior (quotes, spacing, one-letter words) must be gated
on `metadata.language`; other languages keep their own conventions.

## Measuring

Changes to preprocessing, OCR settings, cleanup or quality flags need numbers:

```bash
uv run python scripts/corpus.py all
```

This downloads the public-domain test books, converts them, and appends CER,
WER, paragraph F1 and header leaks to `tests/corpus/results/`. Commit the new
result together with your change, and update
[docs/benchmarks.md](docs/benchmarks.md) if the numbers move. A change that
looks better on one page and worse on the book does not go in; the benchmark
history has examples of both.

## Test data and licensing

- Test fixtures and corpus books must be public domain (Internet Archive
  scans, Project Gutenberg texts). The corpus manifest stores URLs and
  checksums only; never commit large scans.
- New dependencies: ask first in an issue, and check the license against
  PLAN.md §2. Bundled code and model weights must be permissively licensed;
  GPL tools may only be invoked as separate programs. Check the native
  libraries inside binary wheels too, not only the package's own license:
  `opencv-python-headless` is Apache-2.0 but bundles FFmpeg
  (`scripts/check_licenses.py --app` lists such packages).
  `uv run python scripts/check_licenses.py` must pass, and
  `THIRD_PARTY_LICENSES.md` must be updated.
- rebind is for books you own or that are in the public domain.

## Commits and pull requests

Small, focused pull requests are easiest to review. Describe what changed and
why, how you tested it, and any benchmark numbers. By contributing you agree
that your contribution is licensed under Apache-2.0.
