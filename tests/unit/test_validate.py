"""validate: EPUBCheck is optional; the report says when it was skipped."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from rich.console import Console

from rebind import tools
from rebind.config import Config
from rebind.errors import ToolMissingError
from rebind.imaging import write_png
from rebind.ir import Block, BlockKind, BookIR, Page
from rebind.job import Job
from rebind.pipeline import StageContext
from rebind.stages.validate import STAGE

TEXT = "The lawyer walked slowly home through the quiet streets of London that evening. " * 10


@pytest.fixture
def no_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    tools.version.cache_clear()
    tools.java_works.cache_clear()
    yield
    tools.version.cache_clear()
    tools.java_works.cache_clear()


def _job(tmp_path: Path) -> Job:
    job = Job(tmp_path / "job")
    for stage in ("preprocess", "ocr", "cleanup", "build", "validate"):
        job.dir(stage).mkdir(parents=True)
    img = job.dir("preprocess") / "p0001.png"
    write_png(img, 10, 10, 1, bytes([0] * 100))
    page = Page(index=0, width=10, height=10, image_path=job.rel(img))
    ir = BookIR(pages=[page], blocks=[Block(id="b1", kind=BlockKind.PARAGRAPH, text=TEXT, page=0)])
    ir.save(job.raw_ir)
    ir.save(job.clean_ir)
    job.epub.write_bytes(b"PK fake epub")
    return job


def _ctx(job: Job, cfg: Config) -> StageContext:
    return StageContext(job=job, cfg=cfg, manifest=job.load_manifest(), console=Console(quiet=True))


def test_epubcheck_missing_is_skipped_with_note(tmp_path: Path, no_tools: None) -> None:
    job = _job(tmp_path)
    ctx = _ctx(job, Config())
    assert STAGE.extra_key(ctx) == "missing"
    info = STAGE.run(ctx)
    assert info["epubcheck_skipped"] is True
    report = json.loads(job.report_json.read_text())
    assert report["epubcheck"]["skipped"] is True
    assert "not found" in report["epubcheck"]["reason"]
    assert any("epubcheck skipped" in w for w in ctx.warnings)
    html = (job.dir("validate") / "report.html").read_text()
    assert "skipped" in html


def test_epubcheck_required_fails_when_missing(tmp_path: Path, no_tools: None) -> None:
    job = _job(tmp_path)
    cfg = Config.model_validate({"validate": {"require_epubcheck": True}})
    with pytest.raises(ToolMissingError, match="EPUBCheck not found"):
        STAGE.run(_ctx(job, cfg))


def test_epubcheck_turned_off(tmp_path: Path) -> None:
    job = _job(tmp_path)
    cfg = Config.model_validate({"validate": {"epubcheck": False}})
    ctx = _ctx(job, cfg)
    assert STAGE.extra_key(ctx) == "off"
    STAGE.run(ctx)
    report = json.loads(job.report_json.read_text())
    assert report["epubcheck"]["skipped"] is True
    assert not ctx.warnings


def test_java_stub_does_not_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # macOS ships /usr/bin/java even without a JDK; it only prints an error.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stubs = [
        ("java", "echo 'Unable to locate a Java Runtime' >&2; exit 1"),
        ("epubcheck", "exit 0"),
    ]
    for name, body in stubs:
        f = bindir / name
        f.write_text(f"#!/bin/sh\n{body}\n")
        f.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    tools.java_works.cache_clear()
    try:
        cmd, reason = tools.epubcheck_status()
        assert cmd is None
        assert "Java" in reason
    finally:
        tools.java_works.cache_clear()
