"""preprocess: clean page images (dark borders, specks, skew).

Backends:
- builtin (default): in-process with numpy and Pillow (`inkthaw.pageclean`).
- unpaper: the external unpaper tool, for users who install it.
- none: copy the rendered pages through.

Each backend is a per-page op, so another one (e.g. a ScanTailor CLI) can be
slotted in later.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import PIL
from PIL import Image

from inkthaw import pageclean, tools
from inkthaw.config import Config
from inkthaw.errors import InkthawError
from inkthaw.imaging import png_size, pnm_to_png
from inkthaw.ir import Page
from inkthaw.pipeline import StageContext
from inkthaw.stages import read_pages, write_pages

PageOp = Callable[[Path, Path, Config], dict[str, Any]]
"""(input png, output png, config) -> per-page stats. Must write the output file."""


def op_builtin(src: Path, dst: Path, cfg: Config) -> dict[str, Any]:
    pp = cfg.preprocess
    with Image.open(src) as img:
        img.load()
        page = img if img.mode in ("L", "RGB") else img.convert("RGB")
    out, stats = pageclean.clean_image(
        page,
        cfg.dpi,
        borders=pp.remove_borders,
        despeckle=pp.despeckle,
        deskew=pp.deskew,
        max_angle=pp.deskew_max_angle,
        mask=pp.mask_content,
        soften=pp.soften,
    )
    out.save(dst, format="PNG", compress_level=6)
    return stats.as_dict()


def op_unpaper(src: Path, dst: Path, cfg: Config) -> dict[str, Any]:
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
        raise InkthawError(f"unpaper produced no output for {src.name}")
    pnm_to_png(tmp, dst)
    tmp.unlink()
    return {}


def op_copy(src: Path, dst: Path, cfg: Config) -> dict[str, Any]:
    shutil.copyfile(src, dst)
    return {}


OPS: dict[str, PageOp] = {"builtin": op_builtin, "unpaper": op_unpaper, "none": op_copy}


class PreprocessStage:
    name = "preprocess"
    version = "3"  # 3: mask keeps every run of ink but small edge marks
    config_keys: tuple[str, ...] = ("dpi", "preprocess")
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        backend = ctx.cfg.preprocess.backend
        if backend == "unpaper":
            return f"unpaper={tools.version('unpaper') or ''}"
        if backend == "builtin":
            return f"numpy={np.__version__};pillow={PIL.__version__}"
        return backend

    def run(self, ctx: StageContext) -> dict[str, Any]:
        job, cfg = ctx.job, ctx.cfg
        backend = cfg.preprocess.backend
        if backend == "unpaper":
            tools.require("unpaper")
        if cfg.preprocess.binarize:
            ctx.warn("preprocess.binarize is not implemented yet; ignoring")
        pages = read_pages(job.dir("rasterize") / "pages.json")
        out_dir = job.dir(self.name)
        op = OPS[backend]

        def do(page: Page) -> tuple[Page, dict[str, Any]]:
            src = job.abs(page.image_path)
            final = out_dir / src.name
            stats = op(src, final, cfg)
            w, h = png_size(final)
            update: dict[str, Any] = {"image_path": job.rel(final), "width": w, "height": h}
            if stats:
                update["attrs"] = {**page.attrs, "preprocess": stats}
            return page.model_copy(update=update), stats

        results = ctx.map_pages(do, pages, "preprocess")
        cleaned = [p for p, _ in results]
        write_pages(out_dir / "pages.json", cleaned)
        info: dict[str, Any] = {"pages": len(cleaned), "backend": backend}
        stats = [s for _, s in results if s]
        if stats:
            rotated = [s["skew_deg"] for s in stats if s.get("rotated")]
            info["deskewed_pages"] = len(rotated)
            info["max_skew_deg"] = max((abs(a) for a in rotated), default=0.0)
            info["border_pages"] = sum(1 for s in stats if s.get("border_fraction", 0) > 0)
            info["specks_removed"] = sum(int(s.get("specks", 0)) for s in stats)
            ctx.info(
                f"{backend}: {info['deskewed_pages']} pages deskewed "
                f"(max {info['max_skew_deg']:.2f}°), borders wiped on "
                f"{info['border_pages']}, {info['specks_removed']} speck pixels removed"
            )
        else:
            ctx.info(f"{backend}: {len(cleaned)} pages")
        return info


STAGE = PreprocessStage()
