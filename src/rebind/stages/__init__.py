"""Pipeline stages. Each reads earlier stages' outputs and writes only its own folder."""

from __future__ import annotations

import json
from pathlib import Path

from rebind.ir import Page


def write_pages(path: Path, pages: list[Page]) -> None:
    data = [p.model_dump(mode="json", exclude_defaults=False) for p in pages]
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def read_pages(path: Path) -> list[Page]:
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; re-run the earlier stage")
    return [Page.model_validate(p) for p in json.loads(path.read_text(encoding="utf-8"))]


def page_filename(index: int, suffix: str = ".png") -> str:
    return f"p{index + 1:04d}{suffix}"
