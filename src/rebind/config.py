"""Configuration: defaults < profile preset < rebind.toml < CLI flags."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rebind.errors import RebindError

CONFIG_FILENAME = "rebind.toml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetadataConfig(_Section):
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    language: str = "en"
    isbn: str | None = None
    publisher: str | None = None
    date: str | None = None
    rights: str | None = None
    cover: Path | None = None
    """User-supplied cover image. Defaults to the first page of the scan."""


class PreprocessConfig(_Section):
    raster_mode: Literal["render", "extract"] = "render"
    """'render' rasterizes with pdftoppm; 'extract' pulls the embedded scan image
    when a page is a single full-page image (falls back to render otherwise)."""
    color: Literal["gray", "color"] = "gray"
    split_spreads: bool = True
    spread_min_aspect: float = 1.1
    """width/height above which a page is treated as a two-page spread."""
    spread_order: Literal["ltr", "rtl"] = "ltr"
    unpaper: bool = True
    unpaper_args: list[str] = Field(default_factory=lambda: ["--no-grayfilter"])
    """Extra unpaper flags. unpaper's gray filter whitens patches between text
    lines on gray-paper scans, which garbles OCR, so it is off by default."""
    binarize: bool = False
    workers: int | None = None
    """Parallel page workers for rasterize/preprocess. None = CPU count."""


class OcrConfig(_Section):
    languages: list[str] = Field(default_factory=list)
    """OCR languages as BCP-47 tags. Empty = metadata.language."""
    docling_ocr: Literal["auto", "easyocr", "rapidocr", "tesseract", "ocrmac"] = "auto"
    tables: bool = True
    pictures: bool = True
    page_batch: int = 1
    """Reserved for engines that can batch pages."""


class CleanupConfig(_Section):
    drop_furniture: bool = True
    running_headers: bool = True
    running_header_threshold: float = 0.3
    hyphenation: bool = True
    merge_paragraphs: bool = True
    typography: bool = True
    footnotes: bool = True
    chapters: bool = True
    front_matter: bool = True
    drop_scanned_toc: bool = True


class BuildConfig(_Section):
    toc_depth: int = 2
    split_level: int = 1
    css: Path | None = None
    """Extra stylesheet appended after the bundled one."""
    cover: bool = True
    azw3: bool = False


class ValidateConfig(_Section):
    epubcheck: bool = True
    fail_on_error: bool = True


class Config(_Section):
    profile: str = "novel"
    dpi: int = Field(default=300, ge=72, le=1200)
    engine: str = "docling"
    device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    models_dir: Path | None = None
    """Where engines cache model weights (mount this as a volume in Docker)."""
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    preprocess: PreprocessConfig = Field(default_factory=PreprocessConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)
    validate_: ValidateConfig = Field(default_factory=ValidateConfig, alias="validate")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def ocr_languages(self) -> list[str]:
        return self.ocr.languages or [self.metadata.language]

    def fingerprint(self, *keys: str) -> str:
        """Stable hash of the named top-level config entries (used for stage skipping)."""
        data = self.model_dump(mode="json", by_alias=True)
        subset = {k: data[k] for k in sorted(keys)}
        blob = json.dumps(subset, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


# Profiles are partial configs layered between defaults and the user's file.
PROFILES: dict[str, dict[str, Any]] = {
    "novel": {
        "ocr": {"tables": False},
        "cleanup": {"footnotes": False},
    },
    "nonfiction": {},
    "academic": {
        "ocr": {"tables": True, "pictures": True},
        "build": {"toc_depth": 3},
    },
    "two-column": {
        "ocr": {"tables": True},
    },
}


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RebindError(f"{path}: invalid TOML: {e}") from e


def find_config_file(explicit: Path | None, search_dir: Path | None = None) -> Path | None:
    if explicit is not None:
        if not explicit.is_file():
            raise RebindError(f"Config file not found: {explicit}")
        return explicit
    candidate = (search_dir or Path.cwd()) / CONFIG_FILENAME
    return candidate if candidate.is_file() else None


def load_config(
    path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    *,
    search_dir: Path | None = None,
) -> Config:
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    file_path = find_config_file(path, search_dir)
    file_data = _read_toml(file_path) if file_path else {}

    profile = overrides.get("profile") or file_data.get("profile") or "novel"
    if profile not in PROFILES:
        raise RebindError(f"Unknown profile '{profile}'. Available: {', '.join(sorted(PROFILES))}")

    merged = deep_merge(PROFILES[profile], file_data)
    merged = deep_merge(merged, overrides)
    merged["profile"] = profile
    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        where = f" in {file_path}" if file_path else ""
        raise RebindError(f"Invalid configuration{where}:\n{e}") from e
