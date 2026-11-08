"""Stage runner: ordered stages, fingerprint-based skipping, manifest bookkeeping."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import traceback
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeVar

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from rebind import __version__, pdf, tools
from rebind.config import Config
from rebind.errors import RebindError, StageError
from rebind.job import STAGE_DIRS, Job
from rebind.manifest import Manifest, now_iso

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class StageContext:
    job: Job
    cfg: Config
    manifest: Manifest
    console: Console = field(default_factory=Console)
    input_pdf: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def workers(self) -> int:
        return self.cfg.preprocess.workers or max(1, (os.cpu_count() or 2))

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.console.print(f"  [yellow]warning:[/] {msg}")

    def info(self, msg: str) -> None:
        self.console.print(f"  [dim]{msg}[/]")

    @contextmanager
    def progress(self, total: int, description: str) -> Iterator[Callable[[], None]]:
        if not self.console.is_terminal:
            yield lambda: None
            return
        with Progress(
            TextColumn("  {task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as prog:
            task = prog.add_task(description, total=total)
            yield lambda: prog.advance(task)

    def map_pages(self, fn: Callable[[T], R], items: Iterable[T], description: str) -> list[R]:
        """Run fn over items in a thread pool (work is mostly subprocess-bound)."""
        items = list(items)
        with self.progress(len(items), description) as advance:

            def wrapped(item: T) -> R:
                try:
                    return fn(item)
                finally:
                    advance()

            if self.workers == 1:
                return [wrapped(i) for i in items]
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                return list(pool.map(wrapped, items))


class Stage(Protocol):
    name: str
    version: str
    """Bump when the stage's output for the same inputs changes."""
    config_keys: tuple[str, ...]
    clean_dir: bool
    """Wipe the stage directory before running (False lets a stage keep a cache)."""

    def extra_key(self, ctx: StageContext) -> str: ...

    def run(self, ctx: StageContext) -> dict[str, Any]: ...


def _stages() -> list[Stage]:
    from rebind.stages import build, cleanup, ingest, ocr, preprocess, rasterize, validate

    return [
        ingest.STAGE,
        rasterize.STAGE,
        preprocess.STAGE,
        ocr.STAGE,
        cleanup.STAGE,
        build.STAGE,
        validate.STAGE,
    ]


STAGE_NAMES = list(STAGE_DIRS)


def stage_key(stage: Stage, ctx: StageContext, upstream: str) -> str:
    h = hashlib.sha256()
    for part in (
        stage.name,
        stage.version,
        ctx.cfg.fingerprint(*stage.config_keys),
        stage.extra_key(ctx),
        upstream,
    ):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()[:20]


def run_pipeline(
    job: Job,
    cfg: Config,
    *,
    input_pdf: Path | None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    console: Console | None = None,
) -> StageContext:
    for name in (from_stage, to_stage):
        if name is not None and name not in STAGE_NAMES:
            raise RebindError(f"Unknown stage '{name}'. Stages: {', '.join(STAGE_NAMES)}")

    job.root.mkdir(parents=True, exist_ok=True)
    manifest = job.load_manifest()
    manifest.rebind_version = __version__
    manifest.config = cfg.model_dump(mode="json", by_alias=True)
    manifest.tools = {name: tools.version(name) for name in tools.TOOLS}
    manifest.tools.update(pdf.versions())
    ctx = StageContext(job=job, cfg=cfg, manifest=manifest, input_pdf=input_pdf)
    if console is not None:
        ctx.console = console

    upstream = ""
    forced = False
    for stage in _stages():
        if stage.name == from_stage:
            forced = True
        key = stage_key(stage, ctx, upstream)
        rec = manifest.stage(stage.name)
        out_dir = job.dir(stage.name)
        if not forced and rec.status == "done" and rec.key == key and out_dir.is_dir():
            ctx.console.print(f"[dim]• {stage.name}: up to date, skipped[/]")
        else:
            # Anything downstream of a re-run stage must re-run too.
            forced = True
            if stage.clean_dir and out_dir.exists():
                shutil.rmtree(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ctx.console.print(f"[bold]• {stage.name}[/]")
            rec.status, rec.error, rec.key = "running", None, None
            rec.started_at, rec.finished_at, rec.duration_s = now_iso(), None, None
            manifest.save(job.manifest_path)
            t0 = time.perf_counter()
            try:
                rec.info = stage.run(ctx) or {}
            except BaseException as e:
                rec.status = "failed"
                rec.error = str(e) if isinstance(e, RebindError) else traceback.format_exc()
                rec.finished_at = now_iso()
                rec.duration_s = round(time.perf_counter() - t0, 2)
                manifest.save(job.manifest_path)
                if isinstance(e, RebindError | KeyboardInterrupt):
                    raise
                raise StageError(f"stage '{stage.name}' crashed: {e!r}") from e
            rec.status, rec.key = "done", key
            rec.finished_at = now_iso()
            rec.duration_s = round(time.perf_counter() - t0, 2)
            manifest.save(job.manifest_path)
            ctx.console.print(f"  [green]done[/] in {rec.duration_s:.1f}s")
        upstream = key
        if stage.name == to_stage:
            break
    return ctx
