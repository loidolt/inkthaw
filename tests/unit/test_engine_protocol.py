"""The engine contract from docs/writing-an-engine.md, exercised with a toy engine."""

from __future__ import annotations

from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from inkthaw import engines
from inkthaw.config import Config
from inkthaw.engines import Capabilities, Engine, EngineContext
from inkthaw.engines.docling_engine import DoclingEngine
from inkthaw.ir import Block, BlockKind, BookIR, Page


class EchoEngine:
    """Minimal engine: one paragraph per page saying which image it saw."""

    name = "echo"

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(layout=False)

    def available(self) -> tuple[bool, str]:
        return True, "always"

    def settings_key(self, cfg: Config) -> str:
        return "echo-1"

    def prefetch(self, cfg: Config, log) -> Path | None:
        return None

    def convert(self, pages: list[Page], cfg: Config, ctx: EngineContext) -> BookIR:
        ir = BookIR(engine=self.name, engine_version=self.version, pages=list(pages))
        for p in pages:
            ir.blocks.append(
                Block(
                    id=f"p{p.index + 1:04d}-b001",
                    kind=BlockKind.PARAGRAPH,
                    text=f"page image {Path(p.image_path).name}",
                    page=p.index,
                    bbox=(0, 0, p.width, p.height),
                )
            )
            ctx.advance()
        return ir


def test_engines_satisfy_protocol() -> None:
    assert isinstance(EchoEngine(), Engine)
    assert isinstance(DoclingEngine(), Engine)


def test_registry_loads_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    ep = EntryPoint(name="echo", value=f"{__name__}:EchoEngine", group=engines.GROUP)
    monkeypatch.setattr(engines, "_entry_points", lambda: {"echo": ep})
    engine = engines.get_engine("echo")
    pages = [Page(index=0, width=10, height=20, image_path="20_clean/p0001.png")]
    seen = []
    ctx = EngineContext(job_root=Path("."), work_dir=Path("."), advance=lambda: seen.append(1))
    ir = engine.convert(pages, Config(), ctx)
    assert ir.blocks[0].text == "page image p0001.png"
    assert seen == [1]
    with pytest.raises(Exception, match="Unknown engine"):
        engines.get_engine("nope")
