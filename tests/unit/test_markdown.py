import pytest

from inkthaw.ir import Block, BlockKind, BookIR
from inkthaw.markdown import escape, render


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("  spaced \n out\t", "spaced out"),
        ("*stars* and _under_", r"\*stars\* and \_under\_"),
        ("[link](x) <tag>", r"\[link\](x) \<tag\>"),
        ("# not a heading", r"\# not a heading"),
        ("1. not a list", r"1\. not a list"),
        ("IV. Roman numeral", r"IV\. Roman numeral"),
        ("a) letter", r"a\) letter"),
        ("(iii) paren", r"\(iii\) paren"),
        ("- dash start", r"\- dash start"),
        ("> quote", r"\> quote"),
        (": colon", r"\: colon"),
        ("Mr. Utterson said 1. no", "Mr. Utterson said 1. no"),
        ("cost $5 & @me", r"cost \$5 \& \@me"),
        ("back\\slash", r"back\\slash"),
    ],
)
def test_escape(raw: str, expected: str) -> None:
    assert escape(raw) == expected


def _b(i: int, kind: BlockKind, text: str = "", **kw) -> Block:
    return Block(id=f"b{i}", kind=kind, text=text, page=0, **kw)


def test_render_structure() -> None:
    ir = BookIR(
        blocks=[
            _b(1, BlockKind.HEADING, "Chapter I", level=1),
            _b(2, BlockKind.PARAGRAPH, "First para."),
            _b(3, BlockKind.LIST_ITEM, "• one"),
            _b(4, BlockKind.LIST_ITEM, "two"),
            _b(5, BlockKind.PARAGRAPH, "After."),
            _b(6, BlockKind.HEADING, "Deep", level=9),
            _b(7, BlockKind.FOOTNOTE, "1 A note."),
            _b(8, BlockKind.IMAGE, attrs={"image_path": "30_ir/images/p1.png", "caption": "Fig"}),
            _b(9, BlockKind.PARAGRAPH, ""),
        ]
    )
    md = render(ir, lambda p: "images/" + p.rsplit("/", 1)[-1])
    assert md == (
        "# Chapter I\n\n"
        "First para.\n\n"
        "- one\n- two\n\n"
        "After.\n\n"
        "###### Deep\n\n"
        "::: footnote-text\n1 A note.\n:::\n\n"
        "![Fig](images/p1.png)\n"
    )


def test_render_table() -> None:
    ir = BookIR(
        blocks=[
            _b(1, BlockKind.TABLE, attrs={"rows": [["A", "B|C"], ["1"]], "caption": "T"}),
        ]
    )
    md = render(ir)
    assert "| A | B\\|C |" in md
    assert "|---|---|" in md
    assert "| 1 |   |" in md
    assert ": T" in md


def test_render_footnotes_and_front_matter() -> None:
    ir = BookIR(
        blocks=[
            _b(1, BlockKind.PARAGRAPH, "A NOVEL", attrs={"role": "front_matter"}),
            _b(2, BlockKind.PARAGRAPH, "© 1920", attrs={"role": "copyright"}),
            _b(3, BlockKind.HEADING, "One", level=1),
            _b(
                4,
                BlockKind.PARAGRAPH,
                "1. He said so.1 And *more*",
                attrs={"noterefs": [{"start": 14, "end": 15, "note": "n/1"}]},
            ),
            Block(
                id="n/1", kind=BlockKind.FOOTNOTE, text="See [x].", page=0, attrs={"linked": True}
            ),
            _b(6, BlockKind.FOOTNOTE, "Orphan note", attrs={"unmatched": True}),
        ]
    )
    md = render(ir)
    assert md == (
        "::: front-matter\n\nA NOVEL\n\n© 1920\n\n:::\n\n"
        "# One\n\n"
        "1\\. He said so.[^n-1] And \\*more\\*\n\n"
        "[^n-1]: See \\[x\\].\n\n"
        "::: footnote-text\nOrphan note\n:::\n"
    )
