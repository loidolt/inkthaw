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
| wordfreq | Apache-2.0 (code); word-frequency data CC-BY-SA 4.0 | dictionary checks: hyphenation joins, garbled-text flags. The data is used at runtime, not redistributed by rebind itself; anyone redistributing an image or bundle that includes wordfreq must keep its data attribution. |
| ftfy | Apache-2.0 | wordfreq dependency |
| langcodes | MIT | wordfreq dependency |
| locate | MIT | wordfreq dependency (its PyPI classifier says "Other/Proprietary", but the shipped LICENSE file is MIT) |
| msgpack | Apache-2.0 | wordfreq dependency |
| regex | Apache-2.0 AND CNRI-Python | wordfreq dependency |
| wcwidth | MIT | ftfy dependency |
| pypdfium2 | Apache-2.0 OR BSD-3-Clause | reads and renders PDFs (replaces poppler since M5) |
| PDFium (inside the pypdfium2 wheel) | BSD-3-Clause / Apache-2.0 | Google's PDF engine; its bundled libraries (FreeType, libjpeg-turbo, libpng, zlib, OpenJPEG, Little CMS, ICU, abseil, ...) are permissive; full list in the wheel's `BUILD_LICENSES/` |
| Pillow | MIT-CMU (HPND) | page images; wheels bundle libjpeg-turbo, libpng, libtiff, libwebp, libavif, FreeType, HarfBuzz, Little CMS, OpenJPEG, zlib-ng, Brotli, libxcb (all permissive) |
| numpy | BSD-3-Clause | in-process preprocessing (replaces unpaper since M5); Linux wheels bundle OpenBLAS (BSD-3-Clause) and libgfortran (GPL-3.0 with the GCC Runtime Library Exception, which permits redistribution in any program) |

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

**Bundled native code to watch:** rapidocr depends on `opencv-python-headless`
(Apache-2.0). Its wheels bundle FFmpeg, which is LGPL-2.1+, and the macOS arm64
wheel (5.0.0.93) ships an FFmpeg built with `--enable-gpl` (x264, x265; its
`libavcodec` reports "GPL version 3 or later"). rebind's own code does not use
OpenCV. Installing it next to rebind (CLI, Docker) is aggregation, but it must
not go into the desktop or mobile app bundles as is (PLAN.md §2);
`scripts/check_licenses.py --app` fails on it.

## CUDA image only

The NVIDIA image is based on `nvidia/cuda` and installs PyTorch's CUDA wheels,
which bring NVIDIA's CUDA runtime libraries (`nvidia-*` packages, e.g. cuBLAS,
cuDNN). These are proprietary but redistributable under the
[NVIDIA CUDA EULA](https://docs.nvidia.com/cuda/eula/) and the NVIDIA
Deep Learning Container license that covers the base image. They are not part
of the CPU image or of `pip install rebind`. `triton` (MIT) is also included.

## External command-line tools (invoked as separate processes, not linked)

These are not Python dependencies. The Docker images ship EPUBCheck and a JRE
as separate programs alongside rebind (aggregation). None of them may
go into the desktop or mobile app bundles if GPL (PLAN.md §2).

| Tool | License | Status |
|---|---|---|
| pandoc | GPL-2.0-or-later | optional EPUB builder (`build.backend = "pandoc"`); the default native writer replaced it, not installed in the images |
| EPUBCheck (5.x via Homebrew, 4.2.6 in the Debian/Ubuntu images) | BSD-3-Clause | optional: validates the EPUB; skipped with a note when missing |
| OpenJDK runtime (for EPUBCheck) | GPL-2.0 with Classpath Exception | optional |
| unpaper | GPL-2.0 | optional preprocess backend (`preprocess.backend = "unpaper"`); not installed in the images since M5 |
| Calibre `ebook-convert` | GPL-3.0 | optional AZW3 output, not bundled |

poppler-utils (GPL) was used up to 0.1.0 and is no longer needed.

## Never bundled

marker (GPL code, restricted weights) and MinerU (license to verify) may only
be supported later as separately installed plugins.

## Benchmark corpus (downloaded on demand, never committed)

`tests/corpus/manifest.toml` lists public-domain scans (Internet Archive) and
ground-truth texts (Project Gutenberg). `scripts/corpus.py` downloads them into
the git-ignored `tests/corpus/downloads/`. Project Gutenberg texts are public
domain in the US; the Gutenberg licence applies to their trademark and header.

## Test fixtures

`tests/fixtures/jekyll-5p.pdf`: five pages (printed pages 1–5) of R. L.
Stevenson, *Strange Case of Dr. Jekyll and Mr. Hyde* (London: E. Nash &
Grayson), University of Toronto scan on the Internet Archive,
<https://archive.org/details/strangecaseofd00stevuoft>, marked
NOT_IN_COPYRIGHT. Public domain. Rebuilt by `scripts/make_fixture.py`.
