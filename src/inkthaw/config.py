"""Configuration: defaults < profile preset < inkthaw.toml < CLI flags."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from inkthaw.errors import InkthawError

CONFIG_FILENAME = "inkthaw.toml"


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
    """'render' rasterizes the page with PDFium; 'extract' pulls the embedded scan
    image when a page is a single full-page image (falls back to render otherwise)."""
    color: Literal["gray", "color"] = "gray"
    split_spreads: bool = True
    spread_min_aspect: float = 1.1
    """width/height above which a page is treated as a two-page spread."""
    spread_order: Literal["ltr", "rtl"] = "ltr"
    backend: Literal["builtin", "unpaper", "none"] = "builtin"
    """Page clean-up: 'builtin' (in-process: borders, despeckle, deskew; no external
    tool), 'unpaper' (needs the unpaper binary, GPL, installed separately), or
    'none' (pass the rendered pages through)."""
    remove_borders: bool = True
    """builtin: wipe dark regions connected to the page edge (scanner borders,
    the facing page, binding shadow)."""
    despeckle: int = Field(default=4, ge=0)
    """builtin: remove isolated dark clusters of up to this many pixels (0 = off)."""
    mask_content: bool = True
    """builtin: white out everything outside the main text area and centre it on
    the page (like unpaper's mask and centring; Docling splits fewer paragraphs)."""
    soften: bool = True
    """builtin: slightly anti-alias hard glyph edges (bicubic sub-pixel resample);
    RapidOCR garbles fewer lines on bitonal scans (docs/benchmarks.md)."""
    deskew: bool = True
    deskew_max_angle: float = Field(default=2.0, ge=0, le=15)
    """builtin: largest skew in degrees that is searched for and corrected."""
    unpaper_args: list[str] = Field(default_factory=lambda: ["--no-grayfilter"])
    """Extra unpaper flags (backend = "unpaper"). unpaper's gray filter whitens
    patches between text lines on gray-paper scans, which garbles OCR, so it is
    off by default."""
    binarize: bool = False
    workers: int | None = None
    """Parallel page workers for rasterize/preprocess. None = CPU count."""

    @model_validator(mode="before")
    @classmethod
    def _legacy_unpaper_switch(cls, data: Any) -> Any:
        # inkthaw <= 0.1 had `unpaper = true|false`. false meant "no clean-up";
        # true is now the built-in backend, which needs no external tool.
        if isinstance(data, dict) and "unpaper" in data:
            data = dict(data)
            enabled = data.pop("unpaper")
            if enabled is False and "backend" not in data:
                data["backend"] = "none"
        return data


class OcrConfig(_Section):
    languages: list[str] = Field(default_factory=list)
    """OCR languages as BCP-47 tags. Empty = metadata.language."""
    docling_ocr: Literal["auto", "easyocr", "rapidocr", "tesseract", "ocrmac"] = "rapidocr"
    """RapidOCR is pinned (not "auto") so output is the same on every platform and
    the benchmark below applies; "auto" picks whatever OCR back-end is installed."""
    rapidocr_backend: Literal["torch", "onnxruntime", "openvino", "paddle"] = "torch"
    """Only used when docling_ocr = "rapidocr"."""
    rapidocr_params: dict[str, float | int | str | bool] = Field(
        default_factory=lambda: {"Det.box_thresh": 0.3}
    )
    """Extra RapidOCR settings passed through Docling. The default lowers the text
    detector's box threshold (RapidOCR default 0.5): lines beside a drop cap were
    otherwise not detected at all (docs/benchmarks.md)."""
    tables: bool = True
    pictures: bool = True


class CleanupConfig(_Section):
    drop_furniture: bool = True
    reading_order: bool = True
    """Sort single-column pages top-to-bottom (fixes engine reading-order slips)."""

    running_headers: bool = True
    running_header_threshold: float = 0.3
    """Drop a page-edge line repeating on more than this share of all pages..."""
    running_header_local_density: float = 0.3
    """...or on this share of the pages between its first and last occurrence
    (catches chapter-title headers that only run through one chapter)."""
    running_header_min_pages: int = 3

    hyphenation: bool = True
    hyphen_join_min_zipf: float = 2.0
    """Join 'enter- prises' only if the joined word is at least this common
    (wordfreq Zipf scale). Otherwise keep the hyphen (a real compound)."""

    merge_paragraphs: bool = True
    typography: bool = True
    footnotes: bool = True
    chapters: bool = True

    front_matter: bool = True
    drop_scanned_toc: bool = True
    front_matter_max_fraction: float = 0.15
    front_matter_max_pages: int = 30


class QualityConfig(_Section):
    low_confidence: float = 0.80
    min_dictionary_ratio: float = 0.85
    char_count_low: float = 0.5
    """Flag pages with fewer characters than this share of the median page."""
    char_count_high: float = 1.6
    unbalanced_tolerance: int = 1
    """Allowed open/close mismatch of brackets per page before flagging."""


class BuildConfig(_Section):
    backend: Literal["native", "pandoc"] = "native"
    """'native' writes EPUB 3 directly from BookIR (no external tool); 'pandoc'
    goes through Pandoc Markdown and needs pandoc >= 3 on PATH (GPL, installed
    separately)."""
    toc_depth: int = 2
    split_level: int = 1
    css: Path | None = None
    """Extra stylesheet appended after the bundled one."""
    cover: bool = True
    azw3: bool = False


class ValidateConfig(_Section):
    epubcheck: bool = True
    """Run EPUBCheck when it (and Java) can be found; otherwise the report says
    validation was skipped."""
    require_epubcheck: bool = False
    """Fail the job instead of skipping when EPUBCheck or Java is missing."""
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
    quality: QualityConfig = Field(default_factory=QualityConfig)

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
    # Fiction and other running prose: chapters only in the TOC, no tables.
    "novel": {
        "ocr": {"tables": False},
        "cleanup": {"footnotes": False},
        "build": {"toc_depth": 1},
    },
    # General nonfiction: footnotes, the odd table or figure, sections in the TOC.
    "nonfiction": {
        "ocr": {"tables": True, "pictures": True},
        "cleanup": {"footnotes": True},
        "build": {"toc_depth": 2},
    },
    # Scholarly books: deep TOC, tables, footnotes; technical vocabulary and
    # formulas lower the dictionary ratio, so that flag is relaxed.
    "academic": {
        "ocr": {"tables": True, "pictures": True},
        "cleanup": {"footnotes": True},
        "build": {"toc_depth": 3},
        "quality": {"min_dictionary_ratio": 0.75, "unbalanced_tolerance": 2},
    },
    # Two text columns per page (encyclopedias, journals, some editions).
    # Reading-order repair already leaves side-by-side blocks alone, and
    # paragraphs are merged across column breaks.
    "two-column": {
        "ocr": {"tables": True, "pictures": True},
        "cleanup": {"footnotes": True},
        "build": {"toc_depth": 2},
        "quality": {"char_count_high": 2.0},
    },
}

PROFILE_HELP: dict[str, str] = {
    "novel": "fiction and running prose: no tables or footnote linking, chapters-only TOC",
    "nonfiction": "footnotes, tables and figures, two-level TOC",
    "academic": "footnotes, tables, three-level TOC, relaxed dictionary checks",
    "two-column": "two text columns per page; footnotes and tables on",
}


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f'"{k}" = {_toml_value(x)}' for k, x in v.items()) + " }"
    raise TypeError(f"cannot write {type(v).__name__} as TOML")


def to_toml(cfg: Config) -> str:
    """The effective configuration as a inkthaw.toml (unset values commented out)."""
    data = cfg.model_dump(mode="json", by_alias=True)
    lines: list[str] = []
    tables: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif value is None:
            lines.append(f"# {key} =")
        else:
            lines.append(f"{key} = {_toml_value(value)}")
    for name, table in tables:
        lines.append(f"\n[{name}]")
        for key, value in table.items():
            lines.append(f"# {key} =" if value is None else f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


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
        raise InkthawError(f"{path}: invalid TOML: {e}") from e


def find_config_file(explicit: Path | None, search_dir: Path | None = None) -> Path | None:
    if explicit is not None:
        if not explicit.is_file():
            raise InkthawError(f"Config file not found: {explicit}")
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
        raise InkthawError(f"Unknown profile '{profile}'. Available: {', '.join(sorted(PROFILES))}")

    merged = deep_merge(PROFILES[profile], file_data)
    merged = deep_merge(merged, overrides)
    merged["profile"] = profile
    # Environment fallbacks, mainly for containers.
    if "models_dir" not in merged and os.environ.get("INKTHAW_MODELS_DIR"):
        merged["models_dir"] = os.environ["INKTHAW_MODELS_DIR"]
    try:
        return Config.model_validate(merged)
    except ValidationError as e:
        where = f" in {file_path}" if file_path else ""
        raise InkthawError(f"Invalid configuration{where}:\n{e}") from e
