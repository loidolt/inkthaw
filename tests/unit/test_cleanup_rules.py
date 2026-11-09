"""Cleanup rules on small synthetic BookIR fixtures."""

from __future__ import annotations

import pytest

from inkthaw.config import Config
from inkthaw.ir import Block, BlockKind, BookIR, Page
from inkthaw.stages.cleanup import apply_rules, registry
from inkthaw.stages.cleanup.chapters import structure_chapters
from inkthaw.stages.cleanup.footnotes import find_marker, link_footnotes, split_marker
from inkthaw.stages.cleanup.frontmatter import mark_front_matter
from inkthaw.stages.cleanup.headers import drop_running_headers
from inkthaw.stages.cleanup.hyphenation import join_hyphenation, join_split_word
from inkthaw.stages.cleanup.paragraphs import merge_paragraphs
from inkthaw.stages.cleanup.reading_order import fix_reading_order
from inkthaw.stages.cleanup.typography import normalize, normalize_typography

K = BlockKind
PROSE = "It was a dark and stormy night, and the rain fell in torrents upon the town. " * 3


def blk(kind: BlockKind, text: str, page: int, n: int = 0, **kw) -> Block:
    return Block(id=f"p{page}-{n}-{kind.value}", kind=kind, text=text, page=page, **kw)


def book(blocks: list[Block], n_pages: int | None = None) -> BookIR:
    n = n_pages or (max(b.page for b in blocks) + 1 if blocks else 1)
    pages = [Page(index=i, width=1000, height=1500, image_path=f"p{i}.png") for i in range(n)]
    return BookIR(pages=pages, blocks=blocks)


def texts(ir: BookIR) -> list[str]:
    return [b.text for b in ir.blocks]


# -- registry ---------------------------------------------------------------


def test_registry_order() -> None:
    assert [r.name for r in registry()] == [
        "furniture",
        "reading_order",
        "headers",
        "typography",
        "hyphenation",
        "paragraphs",
        "footnotes",
        "chapters",
        "front_matter",
    ]


def test_every_rule_can_be_disabled() -> None:
    cfg = Config.model_validate(
        {
            "cleanup": {
                k: False
                for k in (
                    "drop_furniture",
                    "reading_order",
                    "running_headers",
                    "typography",
                    "hyphenation",
                    "merge_paragraphs",
                    "footnotes",
                    "chapters",
                    "front_matter",
                )
            }
        }
    )
    ir = book([blk(K.PAGE_HEADER, "X", 0), blk(K.PARAGRAPH, 'a "b"', 0, 1)])
    out, changes, applied = apply_rules(ir, cfg)
    assert applied == [] and changes == [] and out == ir


# -- reading order --------------------------------------------------------


def test_reading_order_sorts_single_column_page() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "top", 0, 0, bbox=(160, 270, 1190, 478)),
            blk(K.PARAGRAPH, "bottom", 0, 1, bbox=(160, 1170, 1196, 1880)),
            blk(K.PARAGRAPH, "middle", 0, 2, bbox=(163, 465, 1196, 1178)),
            blk(K.PARAGRAPH, "next page", 1, 0, bbox=(160, 100, 1190, 400)),
        ]
    )
    out, changes = fix_reading_order(ir, Config())
    assert texts(out) == ["top", "middle", "bottom", "next page"]
    assert len(changes) == 1


def test_reading_order_keeps_columns_and_missing_boxes() -> None:
    cols = book(
        [
            blk(K.PARAGRAPH, "left top", 0, 0, bbox=(0, 100, 400, 900)),
            blk(K.PARAGRAPH, "left bottom", 0, 1, bbox=(0, 950, 400, 1400)),
            blk(K.PARAGRAPH, "right top", 0, 2, bbox=(500, 100, 900, 1400)),
        ]
    )
    assert fix_reading_order(cols, Config())[1] == []
    nobox = book([blk(K.PARAGRAPH, "b", 0, 0, bbox=(0, 900, 9, 999)), blk(K.PARAGRAPH, "a", 0, 1)])
    assert texts(fix_reading_order(nobox, Config())[0]) == ["b", "a"]


# -- running headers --------------------------------------------------------


WORDS = [
    "apple",
    "birch",
    "cedar",
    "dune",
    "ember",
    "fjord",
    "grove",
    "heath",
    "inlet",
    "juniper",
    "kestrel",
    "larch",
]


def _filler(p: int, k: int) -> str:
    return f"{WORDS[p % 12]} {WORDS[(p // 12 + k) % 12]} {WORDS[(p * 7 + k) % 12]} said the man."


def _paged(header_for, n=10) -> BookIR:
    blocks = []
    for p in range(n):
        h = header_for(p)
        if h:
            blocks.append(blk(K.PARAGRAPH, h, p, 0))
        blocks.append(blk(K.PARAGRAPH, _filler(p, 1), p, 1))
        blocks.append(blk(K.PARAGRAPH, _filler(p, 2) + " More.", p, 2))
    return book(blocks, n)


def test_headers_drops_book_title_and_numbered_variants() -> None:
    ir = _paged(lambda p: f"{p + 10} THE BOOK TITLE" if p % 2 else None, n=12)
    out, changes = drop_running_headers(ir, Config())
    assert not any("BOOK TITLE" in t for t in texts(out))
    assert len(changes) == 6
    assert all(c.rule == "headers" for c in changes)


def test_headers_drops_chapter_title_running_locally_keeps_first_heading() -> None:
    blocks = [blk(K.HEADING, "THE DOOR", 0, 0, level=1)]
    for p in range(40):
        if p and p < 8 and p % 2 == 0:
            blocks.append(blk(K.PARAGRAPH, "THE DOOR", p, 0))
        blocks.append(blk(K.PARAGRAPH, _filler(p, 1), p, 1))
        blocks.append(blk(K.PARAGRAPH, _filler(p, 2) + " More.", p, 2))
    out, _ = drop_running_headers(book(blocks, 40), Config())
    remaining = [b for b in out.blocks if b.text == "THE DOOR"]
    assert len(remaining) == 1 and remaining[0].kind == K.HEADING


def test_headers_drops_bare_page_numbers_at_edges_only() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "17", 0, 0),
            blk(K.PARAGRAPH, "Prose.", 0, 1),
            blk(K.PARAGRAPH, "3", 0, 2),  # middle of page: kept
            blk(K.PARAGRAPH, "More prose.", 0, 3),
            blk(K.PARAGRAPH, "Even more.", 0, 4),
            blk(K.PARAGRAPH, "xiv", 0, 5),
        ]
    )
    out, _ = drop_running_headers(ir, Config())
    assert texts(out) == ["Prose.", "3", "More prose.", "Even more."]


def test_headers_leaves_rare_repeats() -> None:
    ir = _paged(lambda p: '"Yes."' if p in (0, 30, 59) else None, n=60)
    _out, changes = drop_running_headers(ir, Config())
    assert changes == []


# -- typography -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ofﬁce  and ﬂow", "office and flow"),
        ("wait... what . . . now", "wait… what … now"),
        ("well--I mean", "well—I mean"),
        (
            'used to say quaintly : " I let my brother go"',
            "used to say quaintly: “I let my brother go”",
        ),
        ('"Indeed!"said Mr. Utterson', "“Indeed!” said Mr. Utterson"),
        (
            '" One moment. I thank you, sir ; " and the clerk',
            "“One moment. I thank you, sir;” and the clerk",
        ),
        (
            "Hyde's face; 'Set your mind at rest,' says he",
            "Hyde’s face; ‘Set your mind at rest,’ says he",
        ),
        ("the Joneses' house", "the Joneses’ house"),
        ('""I was coming home', "“I was coming home"),
        # old-style quotes read as 66/99 by OCR
        ("66 Did you ever remark that door?", "“Did you ever remark that door?"),
        ("added he, 66 with a very odd story. 99", "added he, “with a very odd story.”"),
        ("at 66 Gaunt Street in 1866, 99 men", "at 66 Gaunt Street in 1866, 99 men"),
        ("soft­hyphen gone, zero​width", "softhyphen gone, zerowidth"),
    ],
)
def test_typography_english(raw: str, expected: str) -> None:
    assert normalize(raw, "en") == expected


def test_typography_keeps_other_languages_conventions() -> None:
    fr = "Il dit : « Bonjour ! »  Puis : rien"
    assert normalize(fr, "fr") == "Il dit : « Bonjour ! » Puis : rien"
    de = '„Ja", sagte er --- und ging'
    assert normalize(de, "de") == '„Ja", sagte er — und ging'


def test_typography_rule_records_changes_and_skips_images() -> None:
    ir = book([blk(K.PARAGRAPH, "a  b", 0), blk(K.IMAGE, "", 0, 1, attrs={"image_path": "x"})])
    out, changes = normalize_typography(ir, Config())
    assert texts(out) == ["a b", ""]
    assert len(changes) == 1


# -- hyphenation ------------------------------------------------------------


def test_hyphenation_joins_dictionary_words_and_keeps_compounds() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "the agents of obscure enter- prises and good- nature", 0),
            blk(K.HEADING, "DIS- TANT", 0, 1, level=1),
            blk(K.PARAGRAPH, "pre- 1900 and Anglo- Saxon", 0, 2),
        ]
    )
    out, changes = join_hyphenation(ir, Config())
    assert texts(out)[0] == "the agents of obscure enterprises and good-nature"
    assert texts(out)[1] == "DIS- TANT"  # headings untouched
    assert texts(out)[2] == "pre- 1900 and Anglo- Saxon"  # needs a lowercase continuation
    assert len(changes) == 2


def test_join_split_word_across_blocks() -> None:
    assert join_split_word("obscure enter-", "prises. One house", "en", 2.0) == (
        "obscure enterprises. One house"
    )
    assert join_split_word("ends here.", "next", "en", 2.0) is None
    assert join_split_word("a good-", "nature man", "en", 2.0) == "a good-nature man"


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "in the nineteenth- and twentieth-century novel"),
        ("en", "a two- or three-volume edition"),
        ("en-GB", "pre- and post-war"),
        ("de", "Ein- und Ausgang"),
        ("fr", "les pré- et post-scriptum"),
        ("la", "fore- and aft"),  # unknown language: English set
    ],
)
def test_hyphenation_keeps_suspended_hyphens(lang: str, text: str) -> None:
    cfg = Config.model_validate({"metadata": {"language": lang}})
    out, changes = join_hyphenation(book([blk(K.PARAGRAPH, text, 0)]), cfg)
    assert texts(out) == [text]
    assert changes == []


def test_join_split_word_falls_through_on_suspended_hyphen() -> None:
    assert join_split_word("the nineteenth-", "and twentieth century", "en", 2.0) is None
    assert join_split_word("reput-", "able man", "en", 2.0) == "reputable man"


# -- paragraph merge --------------------------------------------------------


def test_merge_across_page_break() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "First para ends.", 0, 0),
            blk(K.PARAGRAPH, "Second para runs over the", 0, 1),
            blk(K.FOOTNOTE, "1 A note.", 0, 2),
            blk(K.PARAGRAPH, "page break and ends.", 1, 0),
            blk(K.PARAGRAPH, "New paragraph.", 1, 1),
        ]
    )
    out, changes = merge_paragraphs(ir, Config())
    assert texts(out) == [
        "First para ends.",
        "Second para runs over the page break and ends.",
        "1 A note.",
        "New paragraph.",
    ]
    merged = out.blocks[1]
    assert merged.attrs["pages"] == [0, 1]
    assert merged.attrs["merged_from"] == ["p1-0-paragraph"]
    assert len(changes) == 1


def test_merge_lowercase_start_even_after_period_and_joins_hyphen() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "the estranged Damon and Pythias.”", 0),
            blk(K.PARAGRAPH, "on some point of science, the obscure enter-", 1),
            blk(K.PARAGRAPH, "prises of the town.", 2),
        ]
    )
    out, _ = merge_paragraphs(ir, Config())
    assert texts(out) == [
        "the estranged Damon and Pythias.” on some point of science, "
        "the obscure enterprises of the town."
    ]


def test_no_merge_on_same_page_or_after_heading() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "No full stop here", 0, 0),
            blk(K.PARAGRAPH, "same page lowercase", 0, 1, bbox=(0, 500, 10, 600)),
            blk(K.HEADING, "CHAPTER II", 1, 0, level=1),
            blk(K.PARAGRAPH, "after a heading", 1, 1),
        ]
    )
    out, changes = merge_paragraphs(ir, Config())
    assert changes == []
    assert len(out.blocks) == 4


def test_merge_on_column_jump_same_page() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "column one runs into", 0, 0, bbox=(0, 1200, 400, 1400)),
            blk(K.PARAGRAPH, "column two here.", 0, 1, bbox=(500, 100, 900, 300)),
        ]
    )
    out, _ = merge_paragraphs(ir, Config())
    assert texts(out) == ["column one runs into column two here."]


def test_no_merge_with_next_paragraph_on_page_after_cross_page_merge() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "The sentence runs over the", 0, 0, bbox=(0, 1300, 900, 1400)),
            blk(K.PARAGRAPH, "page and he wrote as follows:", 1, 0, bbox=(0, 100, 900, 150)),
            blk(
                K.PARAGRAPH,
                "Dear Sir, a new paragraph on the same page.",
                1,
                1,
                bbox=(0, 200, 900, 300),
            ),
        ]
    )
    out, changes = merge_paragraphs(ir, Config())
    assert texts(out) == [
        "The sentence runs over the page and he wrote as follows:",
        "Dear Sir, a new paragraph on the same page.",
    ]
    assert len(changes) == 1


def test_merge_paragraph_running_over_three_pages() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "It began on one", 0, 0, bbox=(0, 1300, 900, 1400)),
            blk(K.PARAGRAPH, "page, filled the whole of the next", 1, 0, bbox=(0, 100, 900, 1400)),
            blk(K.PARAGRAPH, "and ended on a third.", 2, 0, bbox=(0, 100, 900, 200)),
        ]
    )
    out, _ = merge_paragraphs(ir, Config())
    assert texts(out) == [
        "It began on one page, filled the whole of the next and ended on a third."
    ]
    assert out.blocks[0].attrs["pages"] == [0, 1, 2]


def test_merge_on_column_jump_after_cross_page_merge() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "It began on one", 0, 0, bbox=(0, 1300, 900, 1400)),
            blk(K.PARAGRAPH, "page and runs down column one into", 1, 0, bbox=(0, 300, 400, 1400)),
            blk(K.PARAGRAPH, "column two here.", 1, 1, bbox=(500, 100, 900, 300)),
        ]
    )
    out, _ = merge_paragraphs(ir, Config())
    assert texts(out) == ["It began on one page and runs down column one into column two here."]


# -- footnotes --------------------------------------------------------------


def test_split_and_find_marker() -> None:
    assert split_marker("1 The note.") == ("1", "The note.")
    assert split_marker("² Super.") == ("2", "Super.")
    assert split_marker("* Star note") == ("*", "Star note")
    assert split_marker("No marker") is None
    assert find_marker("as Smith says.1 Then", "1", []) == (14, 15)
    assert find_marker("word2 next", "2", []) == (4, 5)
    assert find_marker("in 1902 he", "1", []) is None
    assert find_marker("a claim³ here", "3", []) == (7, 8)
    assert find_marker("first* and second*", "*", [(5, 6)]) == (17, 18)


def test_link_footnotes() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "He said so.1 Later, a claim* arose.", 0, 0),
            blk(K.FOOTNOTE, "1 See the letter.", 0, 1),
            blk(K.FOOTNOTE, "* Doubtful.", 0, 2),
            blk(K.FOOTNOTE, "continued on the next page.", 1, 0),
            blk(K.FOOTNOTE, "7 Orphan note.", 1, 1),
        ]
    )
    out, changes = link_footnotes(ir, Config())
    para, n1, star, orphan = out.blocks
    assert para.attrs["noterefs"] == [
        {"start": 11, "end": 12, "note": n1.id},
        {"start": 27, "end": 28, "note": star.id},
    ]
    assert n1.text == "See the letter."
    assert star.text == "Doubtful. continued on the next page."
    assert orphan.attrs["unmatched"] is True
    actions = sorted(c.action for c in changes)
    assert actions == ["link", "link", "merge", "unmatched"]


def test_footnote_marker_found_in_paragraph_merged_from_previous_page() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "runs over the break.2", 0, 0, attrs={"pages": [0, 1]}),
            blk(K.FOOTNOTE, "2 Note on page one.", 1, 0),
        ]
    )
    out, _ = link_footnotes(ir, Config())
    assert out.blocks[0].attrs["noterefs"][0]["start"] == 20


# -- chapters ---------------------------------------------------------------


def test_chapters_promote_demote_merge_and_levels() -> None:
    ir = book(
        [
            blk(K.HEADING, "THE STRANGE CASE", 0, 0, level=2),
            blk(K.PARAGRAPH, "OF", 0, 1),
            blk(K.HEADING, "DR. JEKYLL AND MR. HYDE", 0, 2, level=2),
            blk(K.HEADING, "STORY OF THE DOOR", 0, 3, level=2),
            blk(K.PARAGRAPH, PROSE, 0, 4),
            blk(K.HEADING, '"Your friend,', 1, 0, level=2),
            blk(K.HEADING, "HASTIE LANYON.", 1, 1, level=2),
            blk(K.PARAGRAPH, "CHAPTER IV.", 2, 0),
            blk(K.PARAGRAPH, PROSE, 2, 1),
            blk(K.HEADING, "III.", 3, 0, level=3),
        ]
    )
    out, changes = structure_chapters(ir, Config())
    heads = [(b.level, b.text) for b in out.blocks if b.kind == K.HEADING]
    assert heads == [
        (1, "THE STRANGE CASE OF DR. JEKYLL AND MR. HYDE"),
        (1, "STORY OF THE DOOR"),
        (1, "CHAPTER IV."),
        (2, "III."),
    ]
    demoted = [b.text for b in out.blocks if b.attrs.get("demoted_heading")]
    assert demoted == ['"Your friend,', "HASTIE LANYON."]
    assert {c.action for c in changes} >= {"promote", "demote", "merge", "edit"}


def test_chapters_keep_period_title_followed_by_prose() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, PROSE, 0, 0),
            blk(K.HEADING, "THE CAREW MURDER CASE.", 1, 0, level=2),
            blk(K.PARAGRAPH, PROSE, 1, 1),
            blk(K.HEADING, "DR. LANYON'S NARRATIVE.", 2, 0, level=2),
            blk(K.PARAGRAPH, PROSE, 2, 1),
        ]
    )
    out, changes = structure_chapters(ir, Config())
    heads = [b.text for b in out.blocks if b.kind == K.HEADING]
    assert heads == ["THE CAREW MURDER CASE.", "DR. LANYON'S NARRATIVE."]
    assert not [c for c in changes if c.action == "demote"]


@pytest.mark.parametrize(
    "after",
    [
        [],  # the letter ends the book
        [blk(K.HEADING, "CHAPTER V", 3, 0, level=1)],
        [blk(K.PARAGRAPH, "Short.", 3, 0)],
    ],
)
def test_chapters_demote_period_signoff_not_followed_by_prose(after: list[Block]) -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, PROSE, 2, 0),
            blk(K.HEADING, "HENRY JEKYLL.", 2, 1, level=2),
            *after,
        ]
    )
    out, _ = structure_chapters(ir, Config())
    assert out.blocks[1].kind == K.PARAGRAPH
    assert out.blocks[1].attrs.get("demoted_heading")


def test_chapters_demote_period_heading_after_closing_or_with_sentences() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "I am, dear sir, your obedient servant,", 0, 0),
            blk(K.HEADING, "HENRY JEKYLL.", 0, 1, level=2),
            blk(K.PARAGRAPH, PROSE, 0, 2),
            blk(K.HEADING, "He went home. Then he slept.", 1, 0, level=2),
            blk(K.PARAGRAPH, PROSE, 1, 1),
        ]
    )
    out, _ = structure_chapters(ir, Config())
    assert [b.text for b in out.blocks if b.kind == K.HEADING] == []


def test_chapters_title_page_run_merges_fully() -> None:
    ir = book(
        [
            blk(K.HEADING, "A NOVEL", 0, 0, level=1),
            blk(K.PARAGRAPH, "BY", 0, 1),
            blk(K.HEADING, "JANE AUTHOR", 0, 2, level=1),
            blk(K.HEADING, "CHAPTER I", 1, 0, level=1),
        ]
    )
    out, _ = structure_chapters(ir, Config())
    assert [b.text for b in out.blocks] == ["A NOVEL BY JANE AUTHOR", "CHAPTER I"]


# -- front matter -----------------------------------------------------------


def test_front_matter_demotes_title_drops_toc_tags_copyright() -> None:
    blocks = [
        blk(K.HEADING, "A NOVEL", 0, 0, level=1),
        blk(K.PARAGRAPH, "Copyright © 1920 by Jane Author", 1, 0),
        blk(K.HEADING, "CONTENTS", 2, 0, level=1),
        blk(K.PARAGRAPH, "I. The Beginning 1", 2, 1),
        blk(K.PARAGRAPH, "II. The Middle 20", 2, 2),
        blk(K.PARAGRAPH, "III. The End 45", 2, 3),
        blk(K.PARAGRAPH, "IV. Epilogue 60", 3, 0),
        blk(K.PARAGRAPH, "V. Notes 70", 3, 1),
        blk(K.PARAGRAPH, "Index 80", 3, 2),
        blk(K.HEADING, "CHAPTER I", 4, 0, level=1),
        blk(K.PARAGRAPH, PROSE, 4, 1),
        blk(K.PARAGRAPH, PROSE, 5, 0),
    ]
    out, changes = mark_front_matter(book(blocks, 40), Config())
    assert [b.text for b in out.blocks][:3] == [
        "A NOVEL",
        "Copyright © 1920 by Jane Author",
        "CHAPTER I",
    ]
    assert out.blocks[0].kind == K.PARAGRAPH and out.blocks[0].attrs["role"] == "front_matter"
    assert out.blocks[1].attrs["role"] == "copyright"
    assert out.blocks[2].kind == K.HEADING and "role" not in out.blocks[2].attrs
    assert sum(1 for c in changes if c.action == "drop") == 7


def test_front_matter_keeps_toc_when_configured() -> None:
    blocks = [
        blk(K.HEADING, "CONTENTS", 0, 0, level=1),
        blk(K.PARAGRAPH, "I. One 1", 0, 1),
        blk(K.HEADING, "CHAPTER I", 1, 0, level=1),
        blk(K.PARAGRAPH, PROSE * 2, 1, 1),
    ]
    cfg = Config.model_validate({"cleanup": {"drop_scanned_toc": False}})
    out, _ = mark_front_matter(book(blocks, 20), cfg)
    assert len(out.blocks) == 4
    assert out.blocks[0].kind == K.PARAGRAPH


def test_front_matter_ignores_late_body_start() -> None:
    blocks = [blk(K.PARAGRAPH, "short", p, 0) for p in range(30)]
    blocks.append(blk(K.HEADING, "LATE", 30, 0, level=1))
    blocks.append(blk(K.PARAGRAPH, PROSE, 30, 1))
    _out, changes = mark_front_matter(book(blocks, 31), Config())
    assert changes == []


def test_find_marker_ocr_variants() -> None:
    assert find_marker("ropes and precipices?”96 He was", "96", []) == (22, 24)
    assert find_marker("indignation and contempt 97 Notwithstanding", "97", []) == (25, 27)
    assert find_marker("in 1 case", "1", []) is None  # single digits need to be glued on


def test_footnote_prefers_marker_on_its_own_page() -> None:
    ir = book(
        [
            blk(K.PARAGRAPH, "First page claim* goes on", 0, 0),
            blk(K.FOOTNOTE, "* Note for page zero.", 0, 1),
            blk(K.PARAGRAPH, "and on the next page another claim* here.", 1, 0),
            blk(K.FOOTNOTE, "* Note for page one.", 1, 1),
        ]
    )
    merged, _ = merge_paragraphs(ir, Config())
    assert merged.blocks[0].attrs["page_offsets"] == [[0, 0], [26, 1]]
    out, _ = link_footnotes(merged, Config())
    text = out.blocks[0].text
    first, second = text.index("*"), text.rindex("*")
    refs = out.blocks[0].attrs["noterefs"]
    assert [(r["start"], r["note"]) for r in refs] == [
        (first, "p0-1-footnote"),
        (second, "p1-1-footnote"),
    ]
