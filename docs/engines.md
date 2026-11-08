# Engines

An engine turns cleaned page images into [BookIR](#bookir), rebind's
engine-neutral representation. Everything after the OCR stage (cleanup, build,
the report) works on BookIR only, so engines can be swapped without touching
the rest of the pipeline.

```bash
uv run rebind engines    # installed engines, their status and capabilities
```

## Docling (default)

[Docling](https://github.com/docling-project/docling) (MIT) does layout
analysis (headings, paragraphs, footnotes, captions, tables, pictures, page
headers and footers) and runs an OCR back-end on each page. Install it with
the `docling` extra (`uv sync --extra docling`; the Docker images include it).

- **OCR back-end:** RapidOCR with the PyTorch back-end by default, pinned so
  output is the same on every platform. Set `ocr.docling_ocr = "auto"` to let
  Docling pick (OcrMac on macOS if installed, otherwise RapidOCR or EasyOCR),
  or choose `easyocr`, `tesseract` (needs the tesseract binary) or `ocrmac`.
- **Device:** `device = "auto"` uses CUDA, then Apple MPS, then CPU. On an
  Apple M-series Mac a page takes about 3 seconds; in a 2-CPU Docker container,
  about 6.
- **Model weights** (about 700 MB): downloaded on first use into Docling's and
  RapidOCR's own caches, or, with `models_dir` set, once into that folder;
  after that the engine runs offline. `rebind models` downloads ahead of time.
- **Per-page cache:** results are cached in `30_ir/cache/`, keyed by the page
  image and the OCR settings, so an interrupted run continues where it
  stopped and re-running later stages never repeats OCR.
- **Raw output:** Docling's own JSON for each page is kept in `30_ir/docling/`
  for debugging.

Label mapping: `title` and `section_header` become headings; `text`,
`paragraph`, `reference` become paragraphs; `page_header`/`page_footer` become
`page_header`/`page_footer`, or `page_number` when the text is just a number;
`footnote`, `caption`, `table`, `picture`, `list_item` map to the same kinds;
anything else becomes `other`. Page confidence is Docling's per-page OCR score.

## Planned engines

- **olmOCR** (Apache-2.0), a vision-language model, as an optional engine.
- **marker** and **MinerU** will never be bundled (licenses); they could be
  supported as separately installed plugins.

## Licensing rule

Engines that ship with rebind must be permissively licensed, including their
model weights. `scripts/check_licenses.py` fails CI if an installed package
has a copyleft, proprietary or unknown license that hasn't been reviewed. A
third-party engine installed as a separate package is the user's choice and
is not bundled.

## BookIR

Defined with Pydantic in [`src/rebind/ir.py`](../src/rebind/ir.py) and
versioned (`ir_version`, currently 1).

```text
BookIR
  ir_version, engine, engine_version
  meta:   title, authors, language, isbn, publisher, date
  pages:  index (0-based), width, height (pixels), image_path (relative to the
          job folder), source_page (1-based PDF page), side (left/right for
          split spreads), confidence, attrs
  blocks: in reading order
    id          unique within the book
    kind        heading | paragraph | footnote | caption | table | image |
                list_item | page_header | page_footer | page_number | other
    level       heading level (1 = top), else null
    text        plain text
    page        page index
    bbox        (x0, y0, x1, y1) in page-image pixels, origin top-left, or null
    confidence  0..1 or null
    attrs       extras: table rows, image_path, caption, list marker, ...
```

Cleanup rules add their own attributes (`pages`, `merged_from`,
`page_offsets`, `noterefs`, `role`, ...); see
[writing-an-engine.md](writing-an-engine.md) for what an engine must provide.
