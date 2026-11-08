"""ingest -> rasterize -> preprocess on a synthetic PDF (needs poppler + unpaper, no engine)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import need_tools
from pdfgen import PageSpec, gray_image, write_pdf
from rich.console import Console

from rebind.config import Config
from rebind.imaging import png_size
from rebind.job import Job
from rebind.pipeline import run_pipeline
from rebind.stages import read_pages


def _text_lines(x: int, y: int) -> int:
    # dark horizontal bars imitating lines of text inside a margin
    return 0 if (60 < x < 540 and 80 < y < 700 and (y // 12) % 2 == 0) else 255


def make_pdf(path: Path) -> None:
    portrait = gray_image(600, 780, _text_lines)
    spread = gray_image(1200, 780, lambda x, y: _text_lines(x % 600, y))
    dpi = 100
    write_pdf(
        path,
        [
            PageSpec(600 * 72 / dpi, 780 * 72 / dpi, portrait),
            PageSpec(1200 * 72 / dpi, 780 * 72 / dpi, spread),
        ],
        info={"Title": "Synthetic"},
    )


@need_tools("pdfinfo", "pdfimages", "pdftotext", "pdftoppm", "unpaper")
def test_ingest_rasterize_preprocess(tmp_path: Path) -> None:
    pdf = tmp_path / "synthetic.pdf"
    make_pdf(pdf)
    job = Job(tmp_path / "jobs" / "synthetic")
    cfg = Config(dpi=100)
    ctx = run_pipeline(job, cfg, input_pdf=pdf, to_stage="preprocess", console=Console(quiet=True))

    info = json.loads(job.source_info.read_text())
    assert info["page_count"] == 2
    assert info["median_scan_ppi"] == 100
    assert info["pdf_metadata"]["Title"] == "Synthetic"
    assert info["text_layer"]["usable"] is False
    assert not ctx.warnings

    raster = read_pages(job.dir("rasterize") / "pages.json")
    assert [(p.source_page, p.side) for p in raster] == [(1, None), (2, "left"), (2, "right")]
    assert (raster[0].width, raster[0].height) == (600, 780)
    assert (raster[1].width, raster[2].width) == (600, 600)
    assert (job.dir("rasterize") / "cover.png").is_file()

    clean = read_pages(job.dir("preprocess") / "pages.json")
    assert len(clean) == 3
    for page in clean:
        path = job.abs(page.image_path)
        assert path.parent == job.dir("preprocess")
        assert png_size(path) == (page.width, page.height)
    assert not list(job.dir("preprocess").glob("*.pgm"))
