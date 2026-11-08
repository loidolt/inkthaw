"""Built-in page clean-up (borders, specks, skew) on synthetic page images."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from inkthaw import pageclean


def text_page(width: int = 1500, height: int = 2100) -> Image.Image:
    """Rows of dark 'words' inside generous margins, like a 300 dpi book page."""
    img = Image.new("L", (width, height), 245)
    draw = ImageDraw.Draw(img)
    for y in range(300, height - 300, 42):
        for x in range(200, width - 260, 34):
            draw.rectangle([x, y, x + 24, y + 16], fill=25)
    return img


@pytest.mark.parametrize("angle", [1.5, -0.8, 0.4])
def test_estimate_skew_recovers_rotation(angle: float) -> None:
    skewed = text_page().rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=245)
    est = pageclean.estimate_skew(np.array(skewed), 300, 2.0)
    assert est == pytest.approx(angle, abs=0.08)


def test_straight_page_is_left_alone() -> None:
    _, stats = pageclean.clean_image(text_page(), 300)
    assert stats.skew_deg == 0.0
    assert not stats.rotated
    assert stats.border_fraction == 0.0


def test_blank_page_has_no_skew() -> None:
    blank = np.full((2100, 1500), 250, dtype=np.uint8)
    assert pageclean.estimate_skew(blank, 300, 2.0) == 0.0


def test_dark_scan_border_is_wiped_but_text_kept() -> None:
    page = np.array(text_page())
    page[:, :90] = 40  # scanner border down the left edge
    page[:60, :] = 30  # and along the top
    out, stats = pageclean.clean_image(
        Image.fromarray(page), 300, deskew=False, despeckle=0, mask=False, soften=False
    )
    a = np.array(out)
    assert a[:, :90].min() == 255
    assert a[:60, :].min() == 255
    assert stats.border_fraction > 0.05
    # Text near the margin survives: the first word column starts at x=200.
    assert (a[300:316, 200:224] < 128).mean() > 0.9


def test_specks_removed_but_small_text_kept() -> None:
    page = np.array(text_page())
    page[150, 700] = 0  # single-pixel dust in the top margin
    page[160:162, 900:902] = 0  # 2x2 speck
    page[180:186, 1100:1106] = 0  # a full stop-sized dot (6x6) must stay
    out, stats = pageclean.clean_image(
        Image.fromarray(page), 300, deskew=False, borders=False, mask=False, soften=False
    )
    a = np.array(out)
    assert a[150, 700] == 255
    assert a[160:162, 900:902].min() == 255
    assert a[180:186, 1100:1106].max() < 128
    assert stats.specks == 5
    assert (a[300:316, 200:224] < 128).all()


def test_color_page_keeps_mode_and_size() -> None:
    page = text_page().convert("RGB").rotate(1.0, fillcolor=(245, 245, 245))
    out, stats = pageclean.clean_image(page, 300)
    assert out.mode == "RGB"
    assert out.size == page.size
    assert stats.rotated


def test_dark_threshold_separates_ink_and_paper() -> None:
    a = np.full((100, 100), 200, dtype=np.uint8)
    a[:30] = 30
    assert 30 < pageclean.dark_threshold(a) < 200


def test_picture_page_is_not_rotated() -> None:
    # A single irregular blob (stamp, figure) has no text lines to align.
    img = Image.new("L", (1500, 2100), 250)
    ImageDraw.Draw(img).ellipse([500, 700, 1000, 1100], outline=20, width=12)
    assert pageclean.estimate_skew(np.array(img.rotate(1.2, fillcolor=250)), 300, 2.0) == 0.0


def test_mask_wipes_stray_marks_and_centres_text() -> None:
    page = np.array(text_page())  # text block x 200..1264, y 300..1800 (off-centre)
    page[1000:1012, 20:24] = 0  # mark near the left edge, far from the text
    page[2040:2050, 700:720] = 0  # signature mark at the bottom
    out, stats = pageclean.clean_image(Image.fromarray(page), 300, deskew=False, despeckle=0)
    a = np.array(out)
    assert stats.content_box is not None
    assert stats.content_box[:2] == (200, 300)
    assert a[:, :100].min() == 255  # edge mark gone
    assert a[1950:, :].min() == 255  # bottom mark gone
    ink_cols = np.nonzero((a < 128).any(axis=0))[0]
    left, right = ink_cols[0], a.shape[1] - 1 - ink_cols[-1]
    assert abs(left - right) <= 2  # text area now centred


def test_content_box_prefers_the_text_over_a_speck() -> None:
    page = np.array(text_page())
    page[300:1100, :] = 245  # text only in the lower part...
    page[1050, 700] = 0  # ...and a speck right at the page centre
    box = pageclean.content_box(page, 300)
    assert box is not None and box[1] >= 1100


def test_soften_antialiases_hard_edges_only() -> None:
    page = np.full((60, 60), 255, dtype=np.uint8)
    page[20:40, 20:40] = 0
    out = np.array(pageclean.soften_edges(Image.fromarray(page)))
    assert out.shape == page.shape
    assert out[5, 5] == 255 and out[30, 30] == 0  # flat areas unchanged
    edge = out[30, 18:22]
    assert ((edge > 0) & (edge < 255)).any()  # edge pixels now gray
