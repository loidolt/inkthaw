from __future__ import annotations

from pathlib import Path

from inkthaw.config import Config
from inkthaw.imaging import write_png
from inkthaw.ir import Block, BlockKind, BookIR, Page
from inkthaw.quality import assess, dictionary_ratio, garbled_runs

K = BlockKind
SENTENCE = "The lawyer walked slowly home through the quiet streets of London that evening. "


def test_garbled_runs_returns_original_substrings() -> None:
    text = "But he was quite easy and sneering. 'Set your i   ts l    ss t  il"
    assert garbled_runs(text, "en") == ["your i   ts l    ss"]
    assert garbled_runs(SENTENCE * 3, "en") == []
    # stray single letters are not words in English...
    assert garbled_runs("to read the two narrat s rs  t   s explained.", "en")
    # ...but initials and abbreviations are fine
    assert garbled_runs("Dr. H. Jekyll, M.D., D.C.L., LL.D., F.R.S., of W.C. said", "en") == []


def test_dictionary_ratio_needs_enough_tokens() -> None:
    assert dictionary_ratio("too short", "en") == (None, 2)
    ratio, n = dictionary_ratio(SENTENCE * 3, "en")
    assert n == 39 and ratio == 1.0
    ratio, _ = dictionary_ratio("xqzt vrbl " * 20, "en")
    assert ratio == 0.0


def _png(path: Path, ink: bool) -> None:
    import random

    rnd = random.Random(1)
    px = bytes(rnd.randrange(256) if ink else 255 for _ in range(100 * 100))
    write_png(path, 100, 100, 1, px)


def test_assess_flags(tmp_path: Path) -> None:
    pages, raw_blocks, clean_blocks = [], [], []
    for i in range(8):
        img = tmp_path / f"p{i}.png"
        _png(img, ink=i != 7)  # page 7: really blank
        conf = 0.5 if i == 3 else 0.97
        pages.append(Page(index=i, width=100, height=100, image_path=img.name, confidence=conf))
    for i in range(8):
        if i in (6, 7):  # 6: inked but nothing found; 7: blank
            continue
        body = SENTENCE * (2 if i == 4 else 12)
        if i == 2:
            body += " and then xq zv bk rt pl went on"
        raw_blocks.append(Block(id=f"h{i}", kind=K.PAGE_HEADER, text="THE BOOK", page=i))
        raw_blocks.append(Block(id=f"b{i}", kind=K.PARAGRAPH, text=body, page=i))
        clean_blocks.append(Block(id=f"b{i}", kind=K.PARAGRAPH, text=body, page=i))
    clean_blocks.insert(1, Block(id="leak", kind=K.PARAGRAPH, text="The Book", page=1))
    clean_blocks.append(
        Block(id="fn", kind=K.FOOTNOTE, text="x", page=5, attrs={"unmatched": True})
    )
    clean_blocks.append(Block(id="br", kind=K.PARAGRAPH, text="((( a", page=5))
    raw = BookIR(pages=pages, blocks=raw_blocks)
    clean = BookIR(pages=pages, blocks=clean_blocks)

    q = assess(raw, clean, Config(), tmp_path)
    flags = {d["index"]: {f["code"] for f in d["flags"]} for d in q["page_details"]}
    assert flags[0] == set()
    assert "leaked_furniture" in flags[1]
    assert "garbled_text" in flags[2]
    assert flags[3] == {"low_confidence"}
    assert "low_char_count" in flags[4]
    assert {"unmatched_footnote", "unbalanced_brackets"} <= flags[5]
    assert flags[6] == {"empty_page"}
    assert flags[7] == set()
    assert q["flagged_pages"] == 6
    assert 0 < q["score"] < 100
