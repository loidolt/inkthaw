"""Watch-folder mode: convert every PDF dropped into an inbox.

- A PDF is picked up once its size and mtime stop changing between two polls
  (so half-copied files are left alone).
- An optional sidecar `<name>.toml` next to the PDF is layered on top of the
  global config (title, authors, profile, ...).
- Success: `<outbox>/<slug>.epub`; the PDF (and sidecar) move to `inbox/done/`.
- Failure: `<outbox>/<slug>.error.txt`; the PDF moves to `inbox/failed/`.
- Jobs live in the jobs folder and resume after a restart.
"""

from __future__ import annotations

import shutil
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from rebind.config import load_config
from rebind.errors import RebindError
from rebind.job import Job, slugify
from rebind.pipeline import run_pipeline

DONE_DIR = "done"
FAILED_DIR = "failed"
_SKIP_SUFFIXES = (".part", ".crdownload", ".download", ".tmp")


@dataclass
class Watcher:
    inbox: Path
    outbox: Path
    jobs_dir: Path
    config_path: Path | None = None
    interval: float = 5.0
    console: Console = field(default_factory=Console)
    _seen: dict[Path, tuple[int, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for d in (self.inbox, self.outbox, self.jobs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str) -> None:
        self.console.print(f"[dim]{datetime.now():%Y-%m-%d %H:%M:%S}[/] {msg}")

    def candidates(self) -> list[Path]:
        return sorted(
            p
            for p in self.inbox.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".pdf"
            and not p.name.startswith((".", "~"))
            and not p.name.endswith(_SKIP_SUFFIXES)
        )

    def stable(self, paths: list[Path]) -> list[Path]:
        """Files whose size and mtime did not change since the previous poll."""
        ready = []
        current: dict[Path, tuple[int, float]] = {}
        for p in paths:
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            sig = (st.st_size, st.st_mtime)
            current[p] = sig
            if st.st_size > 0 and self._seen.get(p) == sig:
                ready.append(p)
        self._seen = current
        return ready

    def sidecar_overrides(self, pdf: Path) -> dict[str, Any]:
        side = pdf.with_suffix(".toml")
        if not side.is_file():
            return {}
        try:
            with side.open("rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise RebindError(f"{side.name}: invalid TOML: {e}") from e

    def _move(self, pdf: Path, sub: str) -> None:
        dest_dir = self.inbox / sub
        dest_dir.mkdir(exist_ok=True)
        for f in (pdf, pdf.with_suffix(".toml")):
            if f.is_file():
                dest = dest_dir / f.name
                if dest.exists():
                    dest = dest_dir / f"{f.stem}-{int(time.time())}{f.suffix}"
                shutil.move(str(f), dest)

    def process(self, pdf: Path) -> bool:
        slug = slugify(pdf.stem)
        self.log(f"[bold]{pdf.name}[/] -> job {slug}")
        error_file = self.outbox / f"{slug}.error.txt"
        try:
            cfg = load_config(self.config_path, self.sidecar_overrides(pdf))
            job = Job((self.jobs_dir / slug).resolve())
            run_pipeline(job, cfg, input_pdf=pdf.resolve(), console=self.console)
            out = self.outbox / f"{slug}.epub"
            tmp = out.with_suffix(".epub.tmp")
            shutil.copyfile(job.epub, tmp)
            tmp.replace(out)  # atomic: consumers never see a half-written EPUB
        except RebindError as e:
            error_file.write_text(f"{pdf.name}: {e}\n", encoding="utf-8")
            self._move(pdf, FAILED_DIR)
            self.log(f"[red]failed[/] {pdf.name}: {str(e).splitlines()[0]}")
            return False
        error_file.unlink(missing_ok=True)
        self._move(pdf, DONE_DIR)
        self.log(f"[green]done[/] {out.name} (report: {job.dir('validate') / 'report.html'})")
        return True

    def run(self, *, once: bool = False) -> int:
        """Loop until interrupted. With once=True, convert what is there and return."""
        self.log(f"watching {self.inbox} -> {self.outbox} (jobs: {self.jobs_dir})")
        processed = 0
        while True:
            pdfs = self.candidates()
            ready = pdfs if once else self.stable(pdfs)
            for pdf in ready:
                self.process(pdf)
                processed += 1
            if once:
                return processed
            time.sleep(self.interval)
