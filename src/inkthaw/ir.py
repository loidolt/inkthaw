"""BookIR: the engine-neutral intermediate representation.

Engines produce BookIR; cleanup rules and the build stage consume it. Nothing
downstream of the OCR stage may depend on engine-specific output.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

IR_VERSION = 1


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    FOOTNOTE = "footnote"
    CAPTION = "caption"
    TABLE = "table"
    IMAGE = "image"
    LIST_ITEM = "list_item"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    PAGE_NUMBER = "page_number"
    OTHER = "other"


FURNITURE_KINDS = frozenset({BlockKind.PAGE_HEADER, BlockKind.PAGE_FOOTER, BlockKind.PAGE_NUMBER})

BBox = tuple[float, float, float, float]
"""(x0, y0, x1, y1) in page-image pixels, origin top-left."""


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: BlockKind
    level: int | None = None
    text: str = ""
    page: int
    bbox: BBox | None = None
    confidence: float | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    width: int
    height: int
    image_path: str
    """Path to the page image, relative to the job directory."""
    source_page: int | None = None
    """1-based page number in the source PDF (spreads map two pages to one)."""
    side: str | None = None
    """'left' / 'right' when the page came from a split spread."""
    confidence: float | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class BookMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    language: str | None = None
    isbn: str | None = None
    publisher: str | None = None
    date: str | None = None


class BookIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ir_version: int = IR_VERSION
    engine: str | None = None
    engine_version: str | None = None
    meta: BookMeta = Field(default_factory=BookMeta)
    pages: list[Page] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    """Blocks in reading order."""

    def page_blocks(self, page: int) -> list[Block]:
        return [b for b in self.blocks if b.page == page]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> BookIR:
        data = path.read_text(encoding="utf-8")
        ir = cls.model_validate_json(data)
        if ir.ir_version != IR_VERSION:
            raise ValueError(
                f"{path}: BookIR version {ir.ir_version} is not supported "
                f"(expected {IR_VERSION}); re-run from the ocr stage"
            )
        return ir
