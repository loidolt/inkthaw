"""Per-job manifest: input hash, config snapshot, stage status, timings, tool versions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

MANIFEST_VERSION = 1

StageStatus = Literal["pending", "running", "done", "failed"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StageRecord(BaseModel):
    status: StageStatus = "pending"
    key: str | None = None
    """Fingerprint of (stage version, relevant config, upstream key). Unchanged => skip."""
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    error: str | None = None
    info: dict[str, Any] = Field(default_factory=dict)
    """Stage-specific summary (page counts, warnings, ...)."""


class Manifest(BaseModel):
    manifest_version: int = MANIFEST_VERSION
    slug: str
    source_name: str | None = None
    input_sha256: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    inkthaw_version: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    tools: dict[str, str | None] = Field(default_factory=dict)
    stages: dict[str, StageRecord] = Field(default_factory=dict)

    def stage(self, name: str) -> StageRecord:
        return self.stages.setdefault(name, StageRecord())

    def save(self, path: Path) -> None:
        self.updated_at = now_iso()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
