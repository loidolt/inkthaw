"""ocr: run the configured engine over cleaned page images -> BookIR (raw.json)."""

from __future__ import annotations

from typing import Any

from inkthaw.engines import EngineContext, get_engine
from inkthaw.pipeline import StageContext
from inkthaw.stages import read_pages


class OcrStage:
    name = "ocr"
    version = "1"
    config_keys: tuple[str, ...] = ("engine", "ocr", "metadata")
    clean_dir = False  # engines keep a per-page cache here

    def extra_key(self, ctx: StageContext) -> str:
        engine = get_engine(ctx.cfg.engine)
        return f"{engine.name}:{engine.settings_key(ctx.cfg)}"

    def run(self, ctx: StageContext) -> dict[str, Any]:
        job, cfg = ctx.job, ctx.cfg
        engine = get_engine(cfg.engine)
        pages = read_pages(job.dir("preprocess") / "pages.json")
        out_dir = job.dir(self.name)
        with ctx.progress(len(pages), f"ocr ({engine.name})") as advance:
            ectx = EngineContext(
                job_root=job.root,
                work_dir=out_dir,
                advance=advance,
                warn=ctx.warn,
                log=ctx.info,
            )
            ir = engine.convert(pages, cfg, ectx)
        ir.save(job.raw_ir)
        confs = [p.confidence for p in ir.pages if p.confidence is not None]
        mean_conf = round(sum(confs) / len(confs), 4) if confs else None
        ctx.info(f"{len(ir.blocks)} blocks from {len(ir.pages)} pages, mean confidence {mean_conf}")
        return {
            "engine": engine.name,
            "engine_version": engine.version,
            "blocks": len(ir.blocks),
            "mean_confidence": mean_conf,
        }


STAGE = OcrStage()
