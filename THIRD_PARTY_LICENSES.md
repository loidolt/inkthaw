# Third-party licenses

rebind itself is Apache-2.0. This file lists what rebind depends on or ships
alongside. Keep it current whenever a dependency, model, or bundled tool changes
(see PLAN.md §2).

## Python dependencies (installed with rebind)

| Package | License | Notes |
|---|---|---|
| typer | MIT | CLI |
| pydantic | MIT | config, BookIR |
| rich | MIT | terminal output |

## Default engine (optional extra `rebind[docling]`)

| Package / model | License | Notes |
|---|---|---|
| docling, docling-core, docling-parse, docling-ibm-models | MIT | layout + OCR pipeline |
| Docling layout and TableFormer model weights (Hugging Face `docling-project/*`) | Apache-2.0 / MIT (check each model card) | downloaded on first use, not bundled |
| torch, torchvision | BSD-3-Clause | inference |
| rapidocr | Apache-2.0 | OCR engine Docling picks by default on this setup |
| PaddleOCR (PP-OCR) model weights used by RapidOCR | Apache-2.0 | downloaded on first use |

Docling may also use other OCR back-ends if installed (EasyOCR: Apache-2.0;
ocrmac: MIT, uses Apple Vision; Tesseract: Apache-2.0). Their transitive
dependencies are recorded in `uv.lock`.

## External command-line tools (invoked as separate processes, not linked)

These are not Python dependencies. They will be installed in the Docker images
(M3), which ship them as separate programs alongside rebind (aggregation).

| Tool | License |
|---|---|
| poppler-utils (pdfinfo, pdfimages, pdftotext, pdftoppm) | GPL-2.0-or-later |
| unpaper | GPL-2.0 |
| pandoc | GPL-2.0-or-later |
| EPUBCheck | BSD-3-Clause |
| OpenJDK runtime (for EPUBCheck) | GPL-2.0 with Classpath Exception |
| Calibre `ebook-convert` (optional, not bundled) | GPL-3.0 |

## Never bundled

marker (GPL code, restricted weights) and MinerU (license to verify) may only
be supported later as separately installed plugins.

## Test fixtures

`tests/fixtures/jekyll-5p.pdf`: five pages (printed pages 1–5) of R. L.
Stevenson, *Strange Case of Dr. Jekyll and Mr. Hyde* (London: E. Nash &
Grayson), University of Toronto scan on the Internet Archive,
<https://archive.org/details/strangecaseofd00stevuoft>, marked
NOT_IN_COPYRIGHT. Public domain. Rebuilt by `scripts/make_fixture.py`.
