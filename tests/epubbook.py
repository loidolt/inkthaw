"""A small BookIR exercising every feature of the native EPUB writer.

Shared by the unit tests and the EPUBCheck integration test.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from inkthaw.ir import Block, BlockKind, BookIR

PROSE = "It was a dark and stormy night; the rain fell in torrents. " * 4


def b(i: str, kind: BlockKind, text: str = "", page: int = 0, **kw: Any) -> Block:
    return Block(id=i, kind=kind, text=text, page=page, **kw)


def sample_ir(image_rel: str | None = None) -> BookIR:
    note_para = "Mr. Utterson2 frowned & said <nothing>."
    start = note_para.index("2")
    blocks = [
        b("f1", BlockKind.PARAGRAPH, "THE STRANGE CASE", attrs={"role": "front_matter"}),
        b("f2", BlockKind.PARAGRAPH, "© 1886 Longmans", attrs={"role": "copyright"}),
        b("h1", BlockKind.HEADING, "Chapter I", level=1),
        b("p1", BlockKind.PARAGRAPH, PROSE),
        b(
            "p2",
            BlockKind.PARAGRAPH,
            note_para,
            attrs={"noterefs": [{"start": start, "end": start + 1, "note": "n1"}]},
        ),
        b("l1", BlockKind.LIST_ITEM, "• first"),
        b("l2", BlockKind.LIST_ITEM, "- second"),
        b("l3", BlockKind.LIST_ITEM, "1. numbered", attrs={"enumerated": True}),
        b("n1", BlockKind.FOOTNOTE, "A note on Utterson.", attrs={"linked": True, "marker": "2"}),
        b("n2", BlockKind.FOOTNOTE, "* stray note", attrs={"unmatched": True}),
        b("h2", BlockKind.HEADING, "Section A", level=2),
        b(
            "t1",
            BlockKind.TABLE,
            attrs={
                "rows": [["Name", "Age"], ["Hyde", "?"], ["", ""], ["Jekyll"]],
                "caption": "Men",
            },
        ),
        b("c1", BlockKind.CAPTION, "A caption."),
        b("h3", BlockKind.HEADING, "Chapter II", level=1),
        b("h4", BlockKind.HEADING, "Deep section", level=3),
        b("p3", BlockKind.PARAGRAPH, "Ctrl\x01char\x0cand   spaced\n text."),
        b("pn", BlockKind.PAGE_NUMBER, "12"),
    ]
    if image_rel:
        blocks.append(
            b("i1", BlockKind.IMAGE, attrs={"image_path": image_rel, "caption": "The door"})
        )
        blocks.append(b("i2", BlockKind.IMAGE, attrs={"image_path": image_rel}))
    return BookIR(blocks=blocks)


META: dict[str, Any] = {
    "title": "Dr. Jekyll & Mr. Hyde",
    "lang": "en",
    "author": ["Robert Louis Stevenson", "A. N. Other"],
    "identifier": [{"scheme": "ISBN", "text": "978-0-14-143973-7"}],
    "publisher": "Longmans, Green & Co.",
    "date": "1886-01-05",
    "rights": "Public domain",
}


def write_image(path: Path, size: tuple[int, int] = (40, 60), fmt: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 100, 50)).save(path, format=fmt)
    return path


def read(epub: Path, name: str) -> str:
    with zipfile.ZipFile(epub) as z:
        return z.read(name).decode("utf-8")
