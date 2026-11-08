"""preprocess: clean page images (unpaper: deskew, borders, noise).

Designed as a list of small per-page ops so an alternate backend (e.g. a
ScanTailor CLI) can be slotted in later.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rebind import tools
from rebind.config import Config
from rebind.errors import RebindError
from rebind.imaging import png_size, pnm_to_png
from rebind.ir import Page
from rebind.pipeline import StageContext
from rebind.stages import read_pages, write_pages

PageOp = Callable[[Path, Path, Config], None]
"""(input png, output png, config). Must write the output file."""


def op_unpaper(src: Path, dst: Path, cfg: Config) -> None:
    pnm_type = "pgm" if cfg.preprocess.color == "gray" else "ppm"
    tmp = dst.with_suffix("." + pnm_type)
    args: list[str | Path] = [
        "unpaper",
        "--overwrite",
        "--quiet",
        "--layout",
        "single",
        "--dpi",
        str(cfg.dpi),
        "-t",
        pnm_type,
        *cfg.preprocess.unpaper_args,
        src,
        tmp,
    ]
    tools.run(args)
    if not tmp.is_file():
        raise RebindError(f"unpaper produced no output for {src.name}")
    pnm_to_png(tmp, dst)
    tmp.unlink()


def build_ops(cfg: Config) -> list[tuple[str, PageOp]]:
    ops: list[tuple[str, PageOp]] = []
    if cfg.preprocess.unpaper:
        ops.append(("unpaper", op_unpaper))
    return ops


class PreprocessStage:
    name = "preprocess"
    version = "1"
    config_keys: tuple[str, ...] = ("dpi", "preprocess")
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        if not ctx.cfg.preprocess.unpaper:
            return ""
        return tools.version("unpaper") or ""

    def run(self, ctx: StageContext) -> dict[str, Any]:
        job, cfg = ctx.job, ctx.cfg
        if cfg.preprocess.unpaper:
            tools.require("unpaper")
        if cfg.preprocess.binarize:
            ctx.warn("preprocess.binarize is not implemented yet; ignoring")
        pages = read_pages(job.dir("rasterize") / "pages.json")
        out_dir = job.dir(self.name)
        ops = build_ops(cfg)

        def do(page: Page) -> Page:
            src = job.abs(page.image_path)
            final = out_dir / src.name
            current = src
            for i, (_, op) in enumerate(ops):
                nxt = final if i == len(ops) - 1 else out_dir / f"{src.stem}.step{i}.png"
                op(current, nxt, cfg)
                if current != src:
                    current.unlink()
                current = nxt
            if current == src:
                shutil.copyfile(src, final)
            w, h = png_size(final)
            return page.model_copy(update={"image_path": job.rel(final), "width": w, "height": h})

        cleaned = ctx.map_pages(do, pages, "preprocess")
        write_pages(out_dir / "pages.json", cleaned)
        return {"pages": len(cleaned), "ops": [name for name, _ in ops]}


STAGE = PreprocessStage()
