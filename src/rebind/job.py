"""Job directory layout (one directory per book)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rebind.manifest import Manifest

STAGE_DIRS: dict[str, str] = {
    "ingest": "00_source",
    "rasterize": "10_pages",
    "preprocess": "20_clean",
    "ocr": "30_ir",
    "cleanup": "40_ir",
    "build": "50_build",
    "validate": "60_report",
}


_TRANSLIT = str.maketrans(
    {
        "Æ": "AE",
        "æ": "ae",
        "Œ": "OE",
        "œ": "oe",
        "Ø": "O",
        "ø": "o",
        "ß": "ss",
        "Ł": "L",
        "ł": "l",
        "Đ": "D",
        "đ": "d",
        "Þ": "Th",
        "þ": "th",
        "ı": "i",
    }
)


def slugify(name: str, max_len: int = 60) -> str:
    norm = unicodedata.normalize("NFKD", name.translate(_TRANSLIT))
    norm = norm.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return (slug[:max_len].rstrip("-")) or "book"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Job:
    root: Path

    @property
    def slug(self) -> str:
        return self.root.name

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def dir(self, stage: str) -> Path:
        return self.root / STAGE_DIRS[stage]

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root / rel

    # Well-known files
    @property
    def source_pdf(self) -> Path:
        return self.dir("ingest") / "input.pdf"

    @property
    def source_info(self) -> Path:
        return self.dir("ingest") / "info.json"

    @property
    def raw_ir(self) -> Path:
        return self.dir("ocr") / "raw.json"

    @property
    def clean_ir(self) -> Path:
        return self.dir("cleanup") / "clean.json"

    @property
    def epub(self) -> Path:
        return self.dir("build") / "book.epub"

    @property
    def report_json(self) -> Path:
        return self.dir("validate") / "report.json"

    def load_manifest(self) -> Manifest:
        if self.manifest_path.is_file():
            return Manifest.load(self.manifest_path)
        return Manifest(slug=self.slug)
