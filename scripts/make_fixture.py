"""Rebuild tests/fixtures/jekyll-5p.pdf from public-domain Internet Archive page scans.

Source: "Strange case of Dr. Jekyll and Mr. Hyde" (R. L. Stevenson, London: E. Nash & Grayson),
University of Toronto scan, https://archive.org/details/strangecaseofd00stevuoft
(NOT_IN_COPYRIGHT). Leaves n14-n18 = printed pages 1-5.

Dev-only: needs Pillow (installed with the docling extra). Run:
    uv run python scripts/make_fixture.py
"""

from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path

from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from pdfgen import PageSpec, jpeg_image, write_pdf  # noqa: E402

ITEM = "strangecaseofd00stevuoft"
LEAVES = [14, 15, 16, 17, 18]
TARGET_WIDTH = 1000  # px; ~220 ppi on this book's 4.5in page
DPI = 220
OUT = ROOT / "tests" / "fixtures" / "jekyll-5p.pdf"


def fetch(leaf: int) -> bytes:
    url = f"https://archive.org/download/{ITEM}/page/n{leaf}.jpg"
    req = urllib.request.Request(url, headers={"User-Agent": "rebind-fixture-builder"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    pages = []
    for leaf in LEAVES:
        im = PILImage.open(io.BytesIO(fetch(leaf))).convert("L")
        h = round(im.height * TARGET_WIDTH / im.width)
        im = im.resize((TARGET_WIDTH, h), PILImage.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=60, optimize=True)
        img = jpeg_image(buf.getvalue())
        pages.append(PageSpec(img.width * 72 / DPI, img.height * 72 / DPI, img))
        print(f"leaf n{leaf}: {img.width}x{img.height}, {len(buf.getvalue()) // 1024} KiB")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_pdf(
        OUT,
        pages,
        info={
            "Title": "Strange case of Dr. Jekyll and Mr. Hyde",
            "Author": "Robert Louis Stevenson",
        },
    )
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
