"""Full pipeline on a 5-page public-domain scan (Jekyll & Hyde, IA). Needs Docling.

Runs with a PATH that holds only EPUBCheck and Java (when they are installed),
proving that no pandoc, poppler or unpaper binary is needed.

Slow on first run (model download). Run with: uv run pytest -m integration
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES
from rich.console import Console

from rebind import tools
from rebind.config import load_config
from rebind.job import Job
from rebind.manifest import Manifest
from rebind.pipeline import run_pipeline

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(importlib.util.find_spec("docling") is None, reason="docling not installed"),
]

ALLOWED_TOOLS = ("epubcheck", "java")


def _minimal_path(bindir: Path) -> str:
    """A PATH with only symlinks to the tools rebind may call (no pandoc, poppler, unpaper)."""
    bindir.mkdir()
    for name in ALLOWED_TOOLS:
        if found := shutil.which(name):
            (bindir / name).symlink_to(found)
    return str(bindir)


@pytest.fixture(scope="module")
def epubcheck_expected() -> bool:
    tools.java_works.cache_clear()
    found = tools.epubcheck_status()[0] is not None
    if os.environ.get("REBIND_REQUIRE_EPUBCHECK") and not found:
        pytest.fail("REBIND_REQUIRE_EPUBCHECK is set but EPUBCheck/Java is not usable")
    return found


@pytest.fixture(scope="module")
def finished_job(tmp_path_factory: pytest.TempPathFactory, epubcheck_expected: bool) -> Job:
    root = tmp_path_factory.mktemp("e2e")
    job = Job(root / "jekyll")
    cfg = load_config(search_dir=root, overrides={"device": "cpu"})
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", _minimal_path(root / "bin"))
        tools.version.cache_clear()
        tools.java_works.cache_clear()
        for absent in ("pandoc", "pdftoppm", "pdfinfo", "pdfimages", "unpaper"):
            assert shutil.which(absent) is None, f"{absent} on PATH {os.environ['PATH']}"
        run_pipeline(job, cfg, input_pdf=FIXTURES / "jekyll-5p.pdf", console=Console(quiet=True))
    tools.version.cache_clear()
    tools.java_works.cache_clear()
    return job


def test_epub_is_valid(finished_job: Job, epubcheck_expected: bool) -> None:
    report = json.loads(finished_job.report_json.read_text())
    if epubcheck_expected:
        assert report["epubcheck"]["errors"] == 0
    else:
        assert report["epubcheck"]["skipped"] is True
    with zipfile.ZipFile(finished_job.epub) as z:
        assert z.read("mimetype") == b"application/epub+zip"
        opf = next(n for n in z.namelist() if n.endswith(".opf"))
        assert b"Jekyll" in z.read(opf)
    build = Manifest.load(finished_job.manifest_path).stages["build"].info
    assert build["backend"] == "native"


def _epub_text(epub: Path) -> str:
    """Text of the book's chapters, tags stripped."""
    with zipfile.ZipFile(epub) as z:
        names = sorted(n for n in z.namelist() if re.match(r"EPUB/text/ch\d+\.xhtml$", n))
        body = " ".join(z.read(n).decode("utf-8") for n in names)
    body = re.sub(r"<title>.*?</title>", " ", body, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", body))


def test_text_and_furniture(finished_job: Job) -> None:
    md = _epub_text(finished_job.epub)
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
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", str(finished_job.root.parent / "bin"))
        tools.version.cache_clear()
        tools.java_works.cache_clear()
        run_pipeline(
            finished_job, cfg, input_pdf=FIXTURES / "jekyll-5p.pdf", console=Console(quiet=True)
        )
    tools.version.cache_clear()
    tools.java_works.cache_clear()
    after = Manifest.load(finished_job.manifest_path)
    for name, rec in after.stages.items():
        assert rec.finished_at == before.stages[name].finished_at, name
