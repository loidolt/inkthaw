"""Full pipeline on a 5-page public-domain scan (Jekyll & Hyde, IA). Needs Docling.

Slow on first run (model download). Run with: uv run pytest -m integration
"""

from __future__ import annotations

import importlib.util
import json
import re
import zipfile

import pytest
from conftest import FIXTURES, need_tools
from rich.console import Console

from rebind.config import load_config
from rebind.job import Job
from rebind.manifest import Manifest
from rebind.pipeline import run_pipeline

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(importlib.util.find_spec("docling") is None, reason="docling not installed"),
    need_tools("pdfinfo", "pdftoppm", "unpaper", "pandoc", "epubcheck"),
]


@pytest.fixture(scope="module")
def finished_job(tmp_path_factory: pytest.TempPathFactory) -> Job:
    root = tmp_path_factory.mktemp("e2e")
    job = Job(root / "jekyll")
    cfg = load_config(search_dir=root, overrides={"device": "cpu"})
    run_pipeline(job, cfg, input_pdf=FIXTURES / "jekyll-5p.pdf", console=Console(quiet=True))
    return job


def test_epub_is_valid(finished_job: Job) -> None:
    report = json.loads(finished_job.report_json.read_text())
    assert report["epubcheck"]["errors"] == 0
    with zipfile.ZipFile(finished_job.epub) as z:
        assert z.read("mimetype") == b"application/epub+zip"
        opf = next(n for n in z.namelist() if n.endswith(".opf"))
        assert b"Jekyll" in z.read(opf)


def test_text_and_furniture(finished_job: Job) -> None:
    md = (finished_job.dir("build") / "book.md").read_text()
    assert "Utterson" in md
    assert "Enfield" in md
    # Running header "STORY OF THE DOOR" appears on pages 3 and 5; only the
    # chapter heading on page 1 should survive.
    assert md.count("STORY OF THE DOOR") == 1
    # "DR. JEKYLL AND MR. HYDE" heads pages 2 and 4; only the title on page 1 may remain.
    assert len(re.findall(r"JEKYLL\s*AND\s*MR\.?\s*HYDE", md, re.I)) <= 1
    changes = json.loads((finished_job.dir("cleanup") / "changes.json").read_text())
    assert sum(1 for c in changes if c["rule"] == "furniture") >= 6


def test_rerun_skips_everything(finished_job: Job) -> None:
    cfg = load_config(search_dir=finished_job.root, overrides={"device": "cpu"})
    before = Manifest.load(finished_job.manifest_path)
    run_pipeline(
        finished_job, cfg, input_pdf=FIXTURES / "jekyll-5p.pdf", console=Console(quiet=True)
    )
    after = Manifest.load(finished_job.manifest_path)
    for name, rec in after.stages.items():
        assert rec.finished_at == before.stages[name].finished_at, name
