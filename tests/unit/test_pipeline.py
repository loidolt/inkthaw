from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from rebind import pipeline
from rebind.config import Config
from rebind.errors import RebindError
from rebind.job import STAGE_DIRS, Job
from rebind.manifest import Manifest


class FakeStage:
    def __init__(self, name: str, keys: tuple[str, ...] = (), fail: bool = False) -> None:
        self.name = name
        self.version = "1"
        self.config_keys = keys
        self.clean_dir = True
        self.fail = fail
        self.runs = 0

    def extra_key(self, ctx: pipeline.StageContext) -> str:
        return ""

    def run(self, ctx: pipeline.StageContext) -> dict[str, Any]:
        self.runs += 1
        if self.fail:
            raise RebindError(f"{self.name} broke")
        (ctx.job.dir(self.name) / "out.txt").write_text(str(self.runs))
        return {"runs": self.runs}


@pytest.fixture
def fake_stages(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeStage]:
    stages = {name: FakeStage(name, ("dpi",) if name == "rasterize" else ()) for name in STAGE_DIRS}
    monkeypatch.setattr(pipeline, "_stages", lambda: list(stages.values()))
    return stages


def _run(job: Job, cfg: Config, **kw: Any) -> pipeline.StageContext:
    return pipeline.run_pipeline(job, cfg, input_pdf=None, console=Console(quiet=True), **kw)


def test_runs_all_then_skips(tmp_path: Path, fake_stages: dict[str, FakeStage]) -> None:
    job = Job(tmp_path / "job")
    _run(job, Config())
    assert all(s.runs == 1 for s in fake_stages.values())
    _run(job, Config())
    assert all(s.runs == 1 for s in fake_stages.values())
    m = Manifest.load(job.manifest_path)
    assert all(m.stages[n].status == "done" for n in STAGE_DIRS)
    assert m.stages["ingest"].info == {"runs": 1}


def test_config_change_reruns_affected_and_downstream(
    tmp_path: Path, fake_stages: dict[str, FakeStage]
) -> None:
    job = Job(tmp_path / "job")
    _run(job, Config())
    _run(job, Config(dpi=400))
    runs = {n: s.runs for n, s in fake_stages.items()}
    assert runs["ingest"] == 1
    assert runs["rasterize"] == 2
    assert runs["validate"] == 2


def test_from_stage_forces_rerun(tmp_path: Path, fake_stages: dict[str, FakeStage]) -> None:
    job = Job(tmp_path / "job")
    _run(job, Config())
    _run(job, Config(), from_stage="cleanup")
    runs = {n: s.runs for n, s in fake_stages.items()}
    assert runs["ocr"] == 1
    assert runs["cleanup"] == 2 and runs["build"] == 2


def test_to_stage_stops(tmp_path: Path, fake_stages: dict[str, FakeStage]) -> None:
    job = Job(tmp_path / "job")
    _run(job, Config(), to_stage="preprocess")
    assert fake_stages["preprocess"].runs == 1
    assert fake_stages["ocr"].runs == 0


def test_missing_output_dir_reruns(tmp_path: Path, fake_stages: dict[str, FakeStage]) -> None:
    job = Job(tmp_path / "job")
    _run(job, Config())
    import shutil

    shutil.rmtree(job.dir("build"))
    _run(job, Config())
    assert fake_stages["build"].runs == 2
    assert fake_stages["cleanup"].runs == 1


def test_failure_is_recorded_and_retried(tmp_path: Path, fake_stages: dict[str, FakeStage]) -> None:
    job = Job(tmp_path / "job")
    fake_stages["build"].fail = True
    with pytest.raises(RebindError, match="build broke"):
        _run(job, Config())
    m = Manifest.load(job.manifest_path)
    assert m.stages["build"].status == "failed"
    assert m.stages["build"].error == "build broke"
    assert "validate" not in m.stages
    fake_stages["build"].fail = False
    _run(job, Config())
    assert fake_stages["cleanup"].runs == 1
    assert fake_stages["build"].runs == 2


def test_unknown_stage_name(tmp_path: Path, fake_stages: dict[str, FakeStage]) -> None:
    with pytest.raises(RebindError, match="Unknown stage"):
        _run(Job(tmp_path / "job"), Config(), from_stage="nope")
