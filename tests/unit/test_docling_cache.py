"""Docling's per-page cache: failed pages are never cached (docling not needed)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from inkthaw.config import Config
from inkthaw.engines import EngineContext
from inkthaw.engines.docling_engine import DoclingEngine
from inkthaw.ir import Page


class StubConverter:
    """Fails every image whose name is in `failing`; records what it was asked."""

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.asked: list[str] = []

    def convert_all(self, paths: list[Path], raises_on_error: bool) -> list[Any]:
        out = []
        for p in paths:
            self.asked.append(p.name)
            if p.name in self.failing:
                err = SimpleNamespace(error_message="boom")
                out.append(SimpleNamespace(status=SimpleNamespace(value="failure"), errors=[err]))
            else:
                out.append(SimpleNamespace(status=SimpleNamespace(value="success"), errors=[]))
        return out


def _ok_entry(self, page: Page, res: Any, img_dir: Path, raw_dir: Path, ctx: Any) -> dict:
    block = {"id": f"p{page.index + 1:04d}-b001", "kind": "paragraph", "text": "ok"}
    return {"blocks": [{**block, "page": page.index}], "confidence": 0.9, "page_attrs": {}}


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pages = []
    for i in range(3):
        img = tmp_path / f"p{i + 1:04d}.png"
        img.write_bytes(f"image {i}".encode())
        pages.append(Page(index=i, width=100, height=100, image_path=img.name))
    monkeypatch.setattr(DoclingEngine, "_page_entry", _ok_entry)
    monkeypatch.setattr(DoclingEngine, "version", property(lambda self: "test"))
    work = tmp_path / "work"
    warnings: list[str] = []
    ctx = EngineContext(job_root=tmp_path, work_dir=work, warn=warnings.append)
    return pages, ctx, work, warnings, monkeypatch


def _run(engine: DoclingEngine, pages, ctx, monkeypatch, conv: StubConverter):
    monkeypatch.setattr(DoclingEngine, "_converter", lambda self, cfg, ctx: conv)
    return engine.convert(pages, Config(), ctx)


def test_failed_page_is_not_cached_and_is_retried(setup) -> None:
    pages, ctx, work, warnings, mp = setup
    engine = DoclingEngine()
    first = StubConverter({"p0002.png"})
    ir = _run(engine, pages, ctx, mp, first)
    assert first.asked == ["p0001.png", "p0002.png", "p0003.png"]
    assert "engine_error" in ir.pages[1].attrs
    assert len(ir.blocks) == 2
    assert any("page 2" in w for w in warnings)
    assert sorted(p.name for p in (work / "cache").iterdir()) == ["p0001.json", "p0003.json"]

    second = StubConverter(set())
    ir = _run(engine, pages, ctx, mp, second)
    assert second.asked == ["p0002.png"]
    assert len(ir.blocks) == 3
    assert "engine_error" not in ir.pages[1].attrs


def test_old_cached_error_entry_is_a_miss(setup) -> None:
    pages, ctx, work, _warnings, mp = setup
    engine = DoclingEngine()
    _run(engine, pages, ctx, mp, StubConverter(set()))
    # What an older version wrote for a failed page: same key, no blocks.
    path = work / "cache" / "p0003.json"
    entry = json.loads(path.read_text())
    entry.update(blocks=[], confidence=None, page_attrs={"engine_error": "old failure"})
    path.write_text(json.dumps(entry))

    conv = StubConverter(set())
    ir = _run(engine, pages, ctx, mp, conv)
    assert conv.asked == ["p0003.png"]
    assert len(ir.blocks) == 3
    assert "engine_error" not in json.loads(path.read_text())["page_attrs"]
