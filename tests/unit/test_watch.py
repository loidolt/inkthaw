from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from inkthaw import watch
from inkthaw.config import Config
from inkthaw.errors import InkthawError
from inkthaw.job import Job


@pytest.fixture
def dirs(tmp_path: Path) -> dict[str, Path]:
    return {k: tmp_path / k for k in ("inbox", "outbox", "jobs")}


def make_watcher(dirs: dict[str, Path]) -> watch.Watcher:
    return watch.Watcher(
        dirs["inbox"], dirs["outbox"], dirs["jobs"], console=Console(quiet=True), interval=0
    )


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def run(job: Job, cfg: Config, *, input_pdf: Path, console: Console) -> None:
        calls.append({"job": job, "cfg": cfg, "pdf": input_pdf})
        if b"broken" in input_pdf.read_bytes():
            raise InkthawError("ingest failed: not a PDF")
        job.epub.parent.mkdir(parents=True, exist_ok=True)
        job.epub.write_bytes(b"EPUB " + input_pdf.name.encode())

    monkeypatch.setattr(watch, "run_pipeline", run)
    return calls


def test_once_converts_and_files_away(dirs, fake_pipeline) -> None:
    w = make_watcher(dirs)
    (dirs["inbox"] / "My Book.pdf").write_bytes(b"%PDF fake")
    (dirs["inbox"] / "My Book.toml").write_text('[metadata]\ntitle = "Sidecar Title"\n')
    (dirs["inbox"] / "notes.txt").write_text("ignore me")
    (dirs["inbox"] / "partial.pdf.part").write_bytes(b"x")

    assert w.run(once=True) == 1
    assert (dirs["outbox"] / "my-book.epub").read_bytes() == b"EPUB My Book.pdf"
    assert (dirs["inbox"] / "done" / "My Book.pdf").is_file()
    assert (dirs["inbox"] / "done" / "My Book.toml").is_file()
    assert (dirs["inbox"] / "notes.txt").is_file()
    assert fake_pipeline[0]["cfg"].metadata.title == "Sidecar Title"


def test_failure_writes_error_and_moves_pdf(dirs, fake_pipeline) -> None:
    w = make_watcher(dirs)
    (dirs["inbox"] / "bad.pdf").write_bytes(b"broken")
    w.run(once=True)
    assert "not a PDF" in (dirs["outbox"] / "bad.error.txt").read_text()
    assert (dirs["inbox"] / "failed" / "bad.pdf").is_file()
    assert not (dirs["outbox"] / "bad.epub").exists()


def test_bad_sidecar_is_a_failure(dirs, fake_pipeline) -> None:
    w = make_watcher(dirs)
    (dirs["inbox"] / "a.pdf").write_bytes(b"%PDF")
    (dirs["inbox"] / "a.toml").write_text("title = = 1")
    w.run(once=True)
    assert "invalid TOML" in (dirs["outbox"] / "a.error.txt").read_text()
    assert fake_pipeline == []


def test_waits_until_file_is_stable(dirs) -> None:
    w = make_watcher(dirs)
    pdf = dirs["inbox"] / "growing.pdf"
    pdf.write_bytes(b"%PDF part one")
    assert w.stable(w.candidates()) == []  # first sighting
    pdf.write_bytes(b"%PDF part one and two")
    assert w.stable(w.candidates()) == []  # still changing
    assert w.stable(w.candidates()) == [pdf]  # unchanged since last poll


def test_same_name_twice_does_not_clobber_done(dirs, fake_pipeline) -> None:
    w = make_watcher(dirs)
    for _ in range(2):
        (dirs["inbox"] / "book.pdf").write_bytes(b"%PDF")
        w.run(once=True)
    assert len(list((dirs["inbox"] / "done").glob("book*.pdf"))) == 2
