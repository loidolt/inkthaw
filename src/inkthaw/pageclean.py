"""In-process scan clean-up: dark border removal, despeckle, deskew.

The built-in replacement for unpaper (PLAN.md §13, M5 decisions). Only numpy
and Pillow are used: both are permissively licensed, ship wheels for every
platform, and are small. Every function works on an 8-bit gray ("L") numpy
array and returns a new array; colour pages are analysed on their luminance
and the same edits are applied to every channel (see `clean_image`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

Gray = NDArray[np.uint8]

# Border removal works on blocks of about 0.7 mm (8 px at 300 dpi).
BORDER_BLOCK_MM = 0.68
BORDER_SEED_DARK = 0.3
"""An edge block this dark starts a border region (catches thin edge shadows)."""
BORDER_GROW_DARK = 0.5
"""Blocks at least this dark extend a border region inwards."""

MASK_HGAP_MM = 5.0
"""Columns of ink closer than this belong to the same text area."""
MASK_VGAP_MM = 10.0
"""Rows of ink closer than this belong to the same text area (bridges the gap
between running header and text, and between paragraphs)."""
MASK_PAD_MM = 2.0
MASK_MIN_INK = 0.002
"""A row/column counts as inked if at least this share of its pixels is dark."""
MASK_EDGE_ZONE = 0.09
"""Outer share of the page (per axis) where small runs of ink count as stray marks."""
MASK_STRAY_MASS = 0.03
"""A run of ink holding less than this share of the largest run's ink is small."""

SOFTEN_SHIFT_PX = 0.25
"""Bicubic resample by this sub-pixel offset. Bitonal (MRC/JBIG2) scans render
with hard glyph edges; RapidOCR's recognizer garbles fewer lines once they are
slightly anti-aliased. unpaper does this as a side effect of resampling almost
every page while deskewing (Jekyll benchmark, M5: 2.31% -> 1.82% CER; a
half-pixel shift, which softens more, gave 1.96%)."""

DESKEW_ANALYSIS_DPI = 100
DESKEW_FINE_DPI = 200
DESKEW_MIN_DARK_PIXELS = 400
"""Pages with less ink than this (at the analysis resolution) are left alone."""
DESKEW_MIN_CONTRAST = 1.15
"""Text pages have one sharply best angle: their row profile at that angle scores
1.3-1.7x the worst angle searched (Jekyll benchmark). Pictures, stamps and
near-blank pages stay near 1.0 and are not rotated."""
DESKEW_MIN_ANGLE = 0.05
"""Smaller corrections are not worth resampling the page."""


@dataclass
class CleanStats:
    border_fraction: float = 0.0
    """Share of the page area wiped as scanner border."""
    specks: int = 0
    """Dark pixels removed as isolated specks."""
    skew_deg: float = 0.0
    """Measured skew; the page was rotated by -skew_deg."""
    rotated: bool = False
    content_box: tuple[int, int, int, int] | None = None
    """Text area (x0, y0, x1, y1) kept and centred, before padding, if masking ran."""

    def as_dict(self) -> dict[str, float | int | bool]:
        d = asdict(self)
        d["border_fraction"] = round(self.border_fraction, 4)
        d["skew_deg"] = round(self.skew_deg, 3)
        return d


def dark_threshold(gray: Gray) -> int:
    """Otsu threshold between ink and paper, clamped to a sane range."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 128
    levels = np.arange(256, dtype=np.float64)
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * levels)
    mean_all = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mean_all * w0 / total - m0) ** 2 / (w0 * w1 / total)
    between[~np.isfinite(between)] = 0
    t = int(np.argmax(between))
    return min(max(t, 64), 192)


def _dilate4(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def border_mask(gray: Gray, dpi: int, threshold: int | None = None) -> NDArray[np.bool_]:
    """Pixels belonging to dark regions connected to the page edge (scanner borders,
    the facing page's edge, binding shadow). Text never qualifies: the gaps between
    letters and lines keep it from forming a dense region that reaches the edge."""
    h, w = gray.shape
    block = max(4, round(BORDER_BLOCK_MM / 25.4 * dpi))
    gh, gw = -(-h // block), -(-w // block)
    if gh < 3 or gw < 3:
        return np.zeros_like(gray, dtype=bool)
    t = dark_threshold(gray) if threshold is None else threshold
    dark = np.zeros((gh * block, gw * block), dtype=np.float32)
    dark[:h, :w] = gray < t
    frac = dark.reshape(gh, block, gw, block).mean(axis=(1, 3))

    grow = frac >= BORDER_GROW_DARK
    seed = np.zeros_like(grow)
    edge = frac >= BORDER_SEED_DARK
    seed[0, :], seed[-1, :] = edge[0, :], edge[-1, :]
    seed[:, 0], seed[:, -1] = edge[:, 0], edge[:, -1]
    region = seed
    allowed = grow | seed
    while True:  # morphological reconstruction of `allowed` from the edge seeds
        nxt = _dilate4(region) & allowed
        if np.array_equal(nxt, region):
            break
        region = nxt
    if not region.any():
        return np.zeros_like(gray, dtype=bool)
    region = _dilate4(region)  # take the anti-aliased fringe too
    full = np.repeat(np.repeat(region, block, axis=0), block, axis=1)
    return full[:h, :w]


def _box_sum(mask: NDArray[np.bool_], r: int) -> NDArray[np.int32]:
    """Number of True pixels in the (2r+1) x (2r+1) window around each pixel."""
    k = 2 * r + 1
    h, w = mask.shape
    padded = np.pad(mask.astype(np.int32), r + 1)[: h + k, : w + k]
    integral = padded.cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
    return integral[k:, k:] - integral[:-k, k:] - integral[k:, :-k] + integral[:-k, :-k]


def speck_mask(
    gray: Gray, dpi: int, max_size: int, threshold: int | None = None
) -> NDArray[np.bool_]:
    """Isolated specks: at most max_size dark pixels within about 0.4 mm, and no
    ink at all (not even faint anti-aliased gray) in a ring around them out to
    about 0.75 mm. Letter strokes always have ink nearby, so thin or broken
    glyphs are never touched; only dust and scanner noise in white space is."""
    if max_size <= 0:
        return np.zeros_like(gray, dtype=bool)
    t = dark_threshold(gray) if threshold is None else threshold
    dark = gray < t
    faint = gray < (t + 255) // 2
    inner = max(1, round(2 * dpi / 300))
    outer = max(inner + 1, round(4 * dpi / 300))
    candidates = dark & (_box_sum(dark, inner) <= max_size)
    if not candidates.any():
        return candidates
    ring_ink = _box_sum(faint, outer) - _box_sum(faint, inner)
    return candidates & (ring_ink == 0)


def _ink_points(gray: Gray, dpi: int, analysis_dpi: int, threshold: int) -> NDArray[np.float64]:
    """(N, 2) array of (x, y) ink pixel positions, centred, at analysis_dpi."""
    img = Image.fromarray(gray)
    scale = min(1.0, analysis_dpi / dpi)
    if scale < 1.0:
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.Resampling.BOX)
    small = np.asarray(img)
    ys, xs = np.nonzero(small < threshold)
    pts = np.empty((len(ys), 2), dtype=np.float64)
    pts[:, 0] = xs - small.shape[1] / 2
    pts[:, 1] = ys - small.shape[0] / 2
    return pts


def _best_angle(
    pts: NDArray[np.float64], angles: NDArray[np.float64], bins_per_px: int
) -> tuple[float, float]:
    """(angle with the sharpest row profile, best score / worst score)."""
    span = int(np.abs(pts).sum(axis=1).max() * bins_per_px) * 2 + 8
    scores = []
    for deg in angles:
        a = np.deg2rad(deg)
        # Row of each ink pixel after rotating the page clockwise by deg on
        # screen, which undoes a counter-clockwise skew of deg.
        rows = np.rint((pts[:, 1] * np.cos(a) + pts[:, 0] * np.sin(a)) * bins_per_px)
        counts = np.bincount(rows.astype(np.int64) + span // 2, minlength=span)
        counts = counts.astype(np.float64)
        scores.append(float(np.dot(counts, counts)))
    best = max(scores)
    # Near-ties (flat optimum): prefer the smallest correction.
    near = [float(a) for a, sc in zip(angles, scores, strict=True) if sc >= best * (1 - 1e-4)]
    return min(near, key=abs), best / max(min(scores), 1.0)


def estimate_skew(gray: Gray, dpi: int, max_angle: float, threshold: int | None = None) -> float:
    """Skew of the text lines in degrees (projection-profile search).

    Positive means the content is rotated counter-clockwise, as PIL's
    `Image.rotate(angle)` would do; rotating by the negative undoes it.
    Returns 0.0 for pages with too little ink to tell.
    """
    if max_angle <= 0:
        return 0.0
    t = dark_threshold(gray) if threshold is None else threshold
    coarse_pts = _ink_points(gray, dpi, DESKEW_ANALYSIS_DPI, t)
    if len(coarse_pts) < DESKEW_MIN_DARK_PIXELS:
        return 0.0
    step = 0.1
    coarse, contrast = _best_angle(coarse_pts, np.arange(-max_angle, max_angle + step / 2, step), 1)
    if contrast < DESKEW_MIN_CONTRAST:
        return 0.0  # no text lines to align (picture, stamp, near-blank page)
    fine_pts = _ink_points(gray, dpi, DESKEW_FINE_DPI, t)
    fine, _ = _best_angle(fine_pts, np.arange(coarse - step, coarse + step + 0.005, 0.01), 2)
    return round(fine, 2)


def _ink_runs(
    profile: NDArray[np.float64], min_ink: float, gap: int
) -> list[tuple[int, int, float]]:
    """Stretches of inked positions (gaps up to `gap` bridged) as (start, end, ink mass),
    end exclusive."""
    idx = np.nonzero(profile >= min_ink)[0]
    if len(idx) == 0:
        return []
    breaks = np.nonzero(np.diff(idx) > gap)[0]
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    return [
        (int(a), int(b) + 1, float(profile[a : b + 1].sum()))
        for a, b in zip(starts, ends, strict=True)
    ]


def _kept_span(profile: NDArray[np.float64], min_ink: float, gap: int) -> tuple[int, int] | None:
    """From the first to the last run of ink that is not a stray mark.

    A run is stray only when it is both small (under MASK_STRAY_MASS of the
    largest run's ink) and lies wholly inside the edge zone (the outer
    MASK_EDGE_ZONE of the page on this axis). Everything else is kept, so a
    second text column, a footnote block or a heading set well apart from the
    body survives (an earlier version kept only the single densest run)."""
    runs = _ink_runs(profile, min_ink, gap)
    if not runs:
        return None
    n = len(profile)
    lo, hi = n * MASK_EDGE_ZONE, n * (1 - MASK_EDGE_ZONE)
    biggest = max(m for _, _, m in runs)
    kept = [
        (a, b) for a, b, m in runs if not (m < biggest * MASK_STRAY_MASS and (b <= lo or a >= hi))
    ]
    return kept[0][0], kept[-1][1]


def content_box(
    gray: Gray, dpi: int, threshold: int | None = None
) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1) of the page's text: every run of inked columns
    and of inked rows except small stray marks near the page edge (edge shadows,
    library stamps in the margin, signature marks)."""
    t = dark_threshold(gray) if threshold is None else threshold
    ink = gray < t
    mm = dpi / 25.4
    xs = _kept_span(ink.mean(axis=0), MASK_MIN_INK, max(1, round(MASK_HGAP_MM * mm)))
    ys = _kept_span(ink.mean(axis=1), MASK_MIN_INK, max(1, round(MASK_VGAP_MM * mm)))
    if xs is None or ys is None:
        return None
    return xs[0], ys[0], xs[1], ys[1]


def mask_and_center(
    arr: NDArray[np.uint8], box: tuple[int, int, int, int], dpi: int
) -> NDArray[np.uint8]:
    """White out everything outside box (plus a small pad) and move the box to the
    middle of the page, as unpaper's mask detection and centring do. Docling's
    layout model splits fewer paragraphs on pages with even margins."""
    h, w = arr.shape[:2]
    pad = round(MASK_PAD_MM / 25.4 * dpi)
    x0, y0 = max(0, box[0] - pad), max(0, box[1] - pad)
    x1, y1 = min(w, box[2] + pad), min(h, box[3] + pad)
    bw, bh = x1 - x0, y1 - y0
    nx, ny = (w - bw) // 2, (h - bh) // 2
    out = np.full_like(arr, 255)
    out[ny : ny + bh, nx : nx + bw] = arr[y0:y1, x0:x1]
    return out


def soften_edges(img: Image.Image, shift: float = SOFTEN_SHIFT_PX) -> Image.Image:
    """Anti-alias hard glyph edges with a bicubic sub-pixel resample."""
    fill: int | tuple[int, int, int] = 255 if img.mode == "L" else (255, 255, 255)
    return img.transform(
        img.size,
        Image.Transform.AFFINE,
        (1, 0, shift, 0, 1, shift),
        resample=Image.Resampling.BICUBIC,
        fillcolor=fill,
    )


def clean_image(
    img: Image.Image,
    dpi: int,
    *,
    borders: bool = True,
    despeckle: int = 4,
    deskew: bool = True,
    max_angle: float = 2.0,
    mask: bool = True,
    soften: bool = True,
) -> tuple[Image.Image, CleanStats]:
    """Run the enabled steps on an L or RGB page image."""
    stats = CleanStats()
    color = img.mode != "L"
    rgb = np.array(img.convert("RGB")) if color else None
    gray = np.array(img.convert("L"))
    t = dark_threshold(gray)

    def wipe(mask: NDArray[np.bool_]) -> None:
        gray[mask] = 255
        if rgb is not None:
            rgb[mask] = 255

    if borders:
        m = border_mask(gray, dpi, t)
        stats.border_fraction = float(m.mean())
        wipe(m)
    if despeckle > 0:
        m = speck_mask(gray, dpi, despeckle, t)
        stats.specks = int(m.sum())
        wipe(m)
    out = Image.fromarray(rgb) if rgb is not None else Image.fromarray(gray)
    if deskew:
        stats.skew_deg = estimate_skew(gray, dpi, max_angle, t)
        if abs(stats.skew_deg) >= DESKEW_MIN_ANGLE:
            fill: int | tuple[int, int, int] = (255, 255, 255) if color else 255
            out = out.rotate(
                -stats.skew_deg, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=fill
            )
            stats.rotated = True
    if mask:
        g = np.asarray(out.convert("L"))
        box = content_box(g, dpi, t)
        if box is not None:
            stats.content_box = box
            out = Image.fromarray(mask_and_center(np.asarray(out), box, dpi))
    if soften:
        out = soften_edges(out)
    return out, stats
