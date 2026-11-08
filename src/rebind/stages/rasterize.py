"""rasterize: render (or extract) page images, splitting two-page spreads."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import PIL

from rebind import pdf
from rebind.config import Config
from rebind.imaging import png_size
from rebind.ir import Page
from rebind.pipeline import StageContext
from rebind.stages import page_filename, write_pages

COVER_DPI = 150


@dataclass(frozen=True)
class PagePlan:
    index: int
    source_page: int
    side: str | None
    crop: tuple[int, int, int, int] | None  # x, y, w, h in output pixels


def plan_pages(source_pages: list[dict[str, Any]], cfg: Config) -> list[PagePlan]:
    """Decide output pages: one per source page, or two for a detected spread."""
    pp = cfg.preprocess
    plans: list[PagePlan] = []
    for sp in source_pages:
        w_pt, h_pt = sp["width_pt"], sp["height_pt"]
        if sp.get("rotate", 0) % 180 == 90:
            w_pt, h_pt = h_pt, w_pt
        aspect = w_pt / h_pt if h_pt else 0
        if pp.split_spreads and aspect >= pp.spread_min_aspect:
            px_w = math.ceil(w_pt / 72 * cfg.dpi)
            px_h = math.ceil(h_pt / 72 * cfg.dpi)
            half = px_w // 2
            left = ("left", (0, 0, half, px_h))
            right = ("right", (half, 0, px_w - half, px_h))
            for side, crop in [left, right] if pp.spread_order == "ltr" else [right, left]:
                plans.append(PagePlan(len(plans), sp["number"], side, crop))
        else:
            plans.append(PagePlan(len(plans), sp["number"], None, None))
    return plans


def _can_extract(sp: dict[str, Any]) -> bool:
    imgs = sp.get("images", [])
    if len(imgs) != 1 or sp.get("rotate", 0):
        return False
    img = imgs[0]
    page_aspect = sp["width_pt"] / sp["height_pt"]
    img_aspect = img["width"] / img["height"]
    return abs(page_aspect - img_aspect) / page_aspect < 0.03


class RasterizeStage:
    name = "rasterize"
    version = "2"  # 2: PDFium (pypdfium2) instead of poppler's pdftoppm/pdfimages
    config_keys: tuple[str, ...] = ("dpi", "preprocess")
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        v = pdf.versions()
        return f"pdfium={v['pdfium']};pillow={PIL.__version__}"

    def run(self, ctx: StageContext) -> dict[str, Any]:
        cfg, job = ctx.cfg, ctx.job
        info = json.loads(job.source_info.read_text(encoding="utf-8"))
        by_number = {p["number"]: p for p in info["pages"]}
        plans = plan_pages(info["pages"], cfg)
        out_dir = job.dir(self.name)
        gray = cfg.preprocess.color == "gray"
        extract = cfg.preprocess.raster_mode == "extract"

        def do(plan: PagePlan) -> tuple[Page, str]:
            out = out_dir / page_filename(plan.index)
            method = "render"
            if (
                extract
                and plan.side is None
                and _can_extract(by_number[plan.source_page])
                and pdf.extract_page_image(job.source_pdf, plan.source_page, out, gray=gray)
            ):
                method = "extract"
            if method == "render":
                pdf.render_page(
                    job.source_pdf, plan.source_page, out, dpi=cfg.dpi, gray=gray, crop=plan.crop
                )
            w, h = png_size(out)
            page = Page(
                index=plan.index,
                width=w,
                height=h,
                image_path=job.rel(out),
                source_page=plan.source_page,
                side=plan.side,
            )
            return page, method

        results = ctx.map_pages(do, plans, "rasterize")
        pages = [p for p, _ in results]
        write_pages(out_dir / "pages.json", pages)

        # Colour cover candidate (first source page) for the build stage.
        pdf.render_page(job.source_pdf, 1, out_dir / "cover.png", dpi=COVER_DPI, gray=False)

        spreads = sum(1 for p in pages if p.side == "left")
        extracted = sum(1 for _, m in results if m == "extract")
        ctx.info(f"{len(pages)} page images ({spreads} spreads split, {extracted} extracted)")
        return {"pages": len(pages), "spreads_split": spreads, "extracted": extracted}


STAGE = RasterizeStage()
