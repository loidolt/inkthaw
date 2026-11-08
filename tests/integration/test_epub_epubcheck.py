"""EPUBCheck on native-writer output that uses every feature (no Docling needed).

Run with: uv run pytest -m integration
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from epubbook import META, sample_ir, write_image

from inkthaw import epub, tools
from inkthaw.stages.build import _bundled_css
from inkthaw.stages.validate import run_epubcheck

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def epubcheck() -> list[str]:
    tools.java_works.cache_clear()
    cmd, reason = tools.epubcheck_status()
    if cmd is None:
        if os.environ.get("INKTHAW_REQUIRE_EPUBCHECK"):
            pytest.fail(f"INKTHAW_REQUIRE_EPUBCHECK is set but {reason}")
        pytest.skip(reason)
    return cmd


@pytest.mark.parametrize(
    ("split_level", "toc_depth", "cover"), [(1, 2, True), (2, 3, False), (1, 1, True)]
)
def test_native_epub_passes_epubcheck(
    tmp_path: Path, epubcheck: list[str], split_level: int, toc_depth: int, cover: bool
) -> None:
    img = write_image(tmp_path / "30_ir" / "images" / "p0001-01.png")
    dest = tmp_path / "book.epub"
    epub.write_epub(
        dest,
        sample_ir("30_ir/images/p0001-01.png"),
        META,
        image_source=lambda rel: tmp_path / rel,
        css=[("epub.css", _bundled_css()), ("extra.css", b"p { color: #333; }")],
        cover=write_image(tmp_path / "cover.jpg", (600, 900)) if cover else None,
        split_level=split_level,
        toc_depth=toc_depth,
    )
    assert img.is_file()
    check = run_epubcheck(epubcheck, dest, tmp_path / "epubcheck.json")
    problems = [m for m in check["messages"] if m["severity"] in ("FATAL", "ERROR", "WARNING")]
    assert check["errors"] == 0 and check["warnings"] == 0, json.dumps(problems, indent=1)
