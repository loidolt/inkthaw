"""PDF access through pypdfium2 on synthetic image-only PDFs (no external tools)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pdfgen import PageSpec, gray_image, write_pdf
from PIL import Image

from rebind import pdf


def _stripes(x: int, y: int) -> int:
    return 0 if (y // 10) % 2 == 0 and 20 < x < 180 else 255


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "s.pdf"
    img = gray_image(200, 300, _stripes)  # 200x300 px placed at 100 ppi
    write_pdf(
        path,
        [
            PageSpec(144, 216, img),
            PageSpec(288, 216, gray_image(400, 300, lambda x, y: _stripes(x % 200, y))),
            PageSpec(144, 216, img, rotate=90),
            PageSpec(144, 216, None),
        ],
        info={"Title": "A (Book)", "Author": "Some One"},
    )
    return path


def test_inspect(sample: Path) -> None:
    fields, pages = pdf.inspect(sample)
    assert fields["Title"] == "A (Book)"
    assert fields["Author"] == "Some One"
    assert "Subject" not in fields  # empty entries are dropped
    assert [p.number for p in pages] == [1, 2, 3, 4]
    assert (pages[0].width_pt, pages[0].height_pt) == (144, 216)
    assert pages[1].aspect == pytest.approx(288 / 216)
    assert pages[2].rotate == 90
    assert pages[2].display_size == (216, 144)
    img = pages[0].images[0]
    assert (img.width, img.height, img.color, img.encoding) == (200, 300, "gray", "image")
    assert pages[0].scan_ppi == 100
    assert pages[3].images == []
    assert pages[3].scan_ppi is None


def test_text_layer_absent(sample: Path) -> None:
    assert pdf.text_chars_per_page(sample) == [0, 0, 0, 0]


def test_render_size_gray_and_crop(sample: Path, tmp_path: Path) -> None:
    out = pdf.render_page(sample, 1, tmp_path / "a.png", dpi=200, gray=True)
    with Image.open(out) as im:
        assert im.mode == "L"
        assert im.size == (400, 600)
    out = pdf.render_page(
        sample, 2, tmp_path / "b.png", dpi=100, gray=False, crop=(200, 0, 200, 300)
    )
    with Image.open(out) as im:
        assert im.mode == "RGB"
        assert im.size == (200, 300)


def test_render_honours_rotate(sample: Path) -> None:
    im = pdf.render_image(sample, 3, dpi=100, gray=True)
    assert im.size == (300, 200)


def test_extract_native_image(sample: Path, tmp_path: Path) -> None:
    out = pdf.extract_page_image(sample, 1, tmp_path / "x.png")
    assert out is not None
    with Image.open(out) as im:
        assert im.size == (200, 300)
        assert im.getpixel((100, 5)) == 0
        assert im.getpixel((100, 15)) == 255
    assert pdf.extract_page_image(sample, 4, tmp_path / "none.png") is None


def test_write_subset(sample: Path, tmp_path: Path) -> None:
    sub = tmp_path / "sub.pdf"
    pdf.write_subset(sample, sub, 2, 3)
    _, pages = pdf.inspect(sub)
    assert [(p.width_pt, p.rotate) for p in pages] == [(288, 0), (144, 90)]


def test_versions() -> None:
    v = pdf.versions()
    assert v["pypdfium2"] and v["pdfium"]
