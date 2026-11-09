"""rasterize: render (or extract) page images, splitting two-page spreads."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import PIL

from inkthaw import pdf
from inkthaw.config import Config
from inkthaw.imaging import png_size
from inkthaw.ir import Page
from inkthaw.pipeline import StageContext
from inkthaw.stages import page_filename, write_pages

COVER_DPI = 150
SPREAD_MIN_WIDTH_RATIO = 1.6
"""In a book of portrait pages, a wide page is a spread when it is at least this
many times as wide as the median portrait page..."""
SPREAD_MAX_HEIGHT_DIFF = 0.15
"""...and its height is within this share of theirs."""


@dataclass(frozen=True)
class PagePlan:
    index: int
    source_page: int
    side: str | None
    crop: tuple[int, int, int, int] | None  # x, y, w, h in output pixels


def _shown_size(sp: dict[str, Any]) -> tuple[float, float]:
    w_pt, h_pt = sp["width_pt"], sp["height_pt"]
    if sp.get("rotate", 0) % 180 == 90:
        w_pt, h_pt = h_pt, w_pt
    return w_pt, h_pt


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def classify_wide(source_pages: list[dict[str, Any]], cfg: Config) -> tuple[set[int], list[int]]:
    """(numbers of pages to split as spreads, numbers of wide pages kept whole).

    A page is wide when width/height >= spread_min_aspect. Whether a wide page
    is a spread depends on the whole document: it is when wide pages are the
    majority (the book was scanned as spreads), or when it is about twice as
    wide as the book's portrait pages and as tall. Otherwise (a single
    landscape page: a rotated table, a fold-out map) it is kept whole."""
    pp = cfg.preprocess
    sizes = {sp["number"]: _shown_size(sp) for sp in source_pages}
    wide = [n for n, (w, h) in sizes.items() if h and w / h >= pp.spread_min_aspect]
    if not pp.split_spreads or not wide:
        return set(), []
    if len(wide) * 2 > len(sizes):
        return set(wide), []
    portrait = [sizes[n] for n in sizes if n not in set(wide)]
    med_w = _median([w for w, _ in portrait])
    med_h = _median([h for _, h in portrait])
    spreads = {
        n
        for n in wide
        if sizes[n][0] >= SPREAD_MIN_WIDTH_RATIO * med_w
        and abs(sizes[n][1] - med_h) <= SPREAD_MAX_HEIGHT_DIFF * med_h
    }
    return spreads, [n for n in wide if n not in spreads]


def plan_pages(source_pages: list[dict[str, Any]], cfg: Config) -> list[PagePlan]:
    """Decide output pages: one per source page, or two for a detected spread."""
    pp = cfg.preprocess
    spreads, _kept = classify_wide(source_pages, cfg)
    plans: list[PagePlan] = []
    for sp in source_pages:
        w_pt, h_pt = _shown_size(sp)
        if sp["number"] in spreads:
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
    version = "3"  # 3: spreads decided with the whole document in view
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
        _spreads, wide_kept = classify_wide(info["pages"], cfg)
        if wide_kept:
            ctx.warn(
                f"{len(wide_kept)} wide page(s) kept whole, not split as spreads "
                f"(source pages {', '.join(map(str, wide_kept))})"
            )
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
        return {
            "pages": len(pages),
            "spreads_split": spreads,
            "wide_kept": len(wide_kept),
            "extracted": extracted,
        }


STAGE = RasterizeStage()
