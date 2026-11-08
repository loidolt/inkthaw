# Profiles and configuration

## How settings are layered

Each setting comes from the first of these that sets it, highest first:

1. Command-line flags (`--dpi`, `--title`, `--profile`, ...)
2. In watch mode, the book's sidecar file: `inbox/<name>.toml` next to `<name>.pdf`
3. `rebind.toml` in the current directory, or the file given with `--config`
4. The profile preset
5. Built-in defaults

`REBIND_MODELS_DIR` sets `models_dir` when no file or flag does.

See the result for any combination:

```bash
uv run rebind config --profile academic
```

The output is a complete `rebind.toml`; save it and edit what you need. Unset
values appear as comments. [`rebind.example.toml`](../rebind.example.toml)
has the commonly changed options.

## Profiles

```bash
uv run rebind profiles
```

| Profile | For | Changes from the defaults |
|---|---|---|
| `novel` (default) | Fiction and other running prose | No table detection; footnote linking off; TOC lists chapters only |
| `nonfiction` | History, biography, essays | Footnotes linked; tables and figures kept; two-level TOC |
| `academic` | Scholarly books, textbooks | As nonfiction, three-level TOC; dictionary-based quality flags relaxed (jargon, formulas); one more unbalanced bracket allowed per page |
| `two-column` | Encyclopedias, journals, some editions | As nonfiction; "too much text on this page" flag relaxed (two columns hold more) |

Every profile uses the same OCR and cleanup steps; the differences are which
optional parts run and how strict the report is. Things that need no profile:

- **Columns.** Reading-order repair only reorders pages without side-by-side
  blocks, and paragraphs are merged across column breaks, in every profile.
- **Language.** Set `metadata.language` (or `--language`); OCR, hyphenation,
  dictionary checks and typography follow it. Curly-quote conversion and the
  removal of old-style spacing before `; : ! ?` happen for English only; other
  languages keep their printed conventions.

## Configuration reference

### Top level

| Key | Default | Meaning |
|---|---|---|
| `profile` | `novel` | Preset, see above |
| `dpi` | `300` | Rasterization resolution |
| `engine` | `docling` | OCR/layout engine (`rebind engines` lists them) |
| `device` | `auto` | `auto` (CUDA, then MPS, then CPU), `cpu`, `cuda`, `mps` |
| `models_dir` | unset | Keep model weights here and run offline after the first download |

### `[metadata]`

`title`, `authors`, `language` (BCP-47, default `en`), `isbn`, `publisher`,
`date`, `rights`, `cover` (image file). Unset title and author fall back to the
PDF's own metadata, then to the first heading or the file name.

### `[preprocess]`

| Key | Default | Meaning |
|---|---|---|
| `raster_mode` | `render` | `render` the page with PDFium, or `extract` the embedded scan image when a page is exactly one image |
| `color` | `gray` | `gray` or `color` page images (the cover is always in color) |
| `split_spreads` | `true` | Split two-page spreads |
| `spread_min_aspect` | `1.1` | Width/height above which a page counts as a spread |
| `spread_order` | `ltr` | `rtl` for right-to-left books |
| `backend` | `builtin` | Page clean-up: `builtin` (in-process, no external tool), `unpaper` (needs the unpaper binary), or `none` |
| `remove_borders` | `true` | builtin: wipe dark regions touching the page edge (scanner borders, the facing page, binding shadow) |
| `despeckle` | `4` | builtin: remove isolated dark clusters of up to this many pixels; `0` turns it off |
| `mask_content` | `true` | builtin: white out everything outside the main text area and centre it on the page (unpaper's mask and centring) |
| `soften` | `true` | builtin: slightly anti-alias hard glyph edges (bicubic quarter-pixel resample); RapidOCR misreads fewer lines on bitonal scans |
| `deskew` | `true` | builtin: straighten skewed pages |
| `deskew_max_angle` | `2.0` | builtin: largest skew (degrees) searched for |
| `unpaper_args` | `["--no-grayfilter"]` | Extra unpaper flags (`backend = "unpaper"`); the gray filter damages text on gray-paper scans |
| `workers` | CPU count | Parallel page workers |

### `[ocr]`

| Key | Default | Meaning |
|---|---|---|
| `languages` | `metadata.language` | OCR languages |
| `docling_ocr` | `rapidocr` | OCR back-end inside Docling: `rapidocr`, `auto`, `easyocr`, `tesseract`, `ocrmac` |
| `rapidocr_backend` | `torch` | RapidOCR inference back-end |
| `rapidocr_params` | `{"Det.box_thresh" = 0.3}` | Passed to RapidOCR; the default keeps lines beside drop caps (see [benchmarks](benchmarks.md)) |
| `tables` | per profile | Table structure recognition |
| `pictures` | `true` | Keep figures as images |

### `[cleanup]`

Every rule has an on/off switch: `drop_furniture`, `reading_order`,
`running_headers`, `typography`, `hyphenation`, `merge_paragraphs`, `footnotes`,
`chapters`, `front_matter`. Tuning knobs:

| Key | Default | Meaning |
|---|---|---|
| `running_header_threshold` | `0.3` | A page-edge line on more than this share of all pages is a running header |
| `running_header_local_density` | `0.3` | ... or on this share of the pages between its first and last occurrence (chapter titles in headers) |
| `running_header_min_pages` | `3` | Minimum repeats before anything is treated as a header |
| `hyphen_join_min_zipf` | `2.0` | How common (wordfreq Zipf) a joined word must be to drop the hyphen |
| `drop_scanned_toc` | `true` | Drop the scanned contents pages; the EPUB has its own |
| `front_matter_max_fraction`, `front_matter_max_pages` | `0.15`, `30` | Front matter is only looked for at the start of the book |

### `[build]`

`backend` (`"native"`, the default, writes EPUB 3 directly from BookIR with no
external tool; `"pandoc"` goes through Pandoc Markdown and needs pandoc ≥ 3),
`toc_depth`, `split_level` (heading level that starts a new EPUB file), `css`
(extra stylesheet applied after the bundled one), `cover` (use the first page
when no cover image is given), `azw3` (also write AZW3; needs Calibre).

### `[validate]` and `[quality]`

`validate.epubcheck` runs EPUBCheck when it and a Java runtime are found;
otherwise the EPUB is still written and the report says validation was
skipped. `validate.require_epubcheck = true` makes a missing EPUBCheck an
error instead, and `validate.fail_on_error` fails the job on EPUBCheck errors.
`[quality]` sets the report's thresholds: `low_confidence` (0.80),
`min_dictionary_ratio` (0.85), `char_count_low` / `char_count_high` (0.5 / 1.6
of the median page), `unbalanced_tolerance` (1).
