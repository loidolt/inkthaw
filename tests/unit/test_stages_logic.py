from rebind.config import Config
from rebind.engines.docling_engine import classify
from rebind.ir import Block, BlockKind, BookIR
from rebind.stages.build import resolve_metadata
from rebind.stages.cleanup import apply_rules
from rebind.stages.cleanup.furniture import drop_furniture
from rebind.stages.rasterize import plan_pages
from rebind.stages.validate import parse_epubcheck


def _sp(n: int, w: float, h: float, rotate: int = 0) -> dict:
    return {"number": n, "width_pt": w, "height_pt": h, "rotate": rotate, "images": []}


def test_plan_pages_splits_spreads_ltr() -> None:
    cfg = Config(dpi=100)
    plans = plan_pages([_sp(1, 432, 648), _sp(2, 864, 648), _sp(3, 432, 648)], cfg)
    assert [(p.index, p.source_page, p.side) for p in plans] == [
        (0, 1, None),
        (1, 2, "left"),
        (2, 2, "right"),
        (3, 3, None),
    ]
    px_w = 864 / 72 * 100  # 1200
    assert plans[1].crop == (0, 0, 600, 900)
    assert plans[2].crop == (600, 0, px_w - 600, 900)


def test_plan_pages_rtl_and_disabled() -> None:
    cfg = Config.model_validate({"preprocess": {"spread_order": "rtl"}})
    plans = plan_pages([_sp(1, 864, 648)], cfg)
    assert [p.side for p in plans] == ["right", "left"]
    cfg = Config.model_validate({"preprocess": {"split_spreads": False}})
    assert len(plan_pages([_sp(1, 864, 648)], cfg)) == 1


def test_plan_pages_rotated_portrait_is_not_a_spread() -> None:
    # stored landscape but rotated 90 => displayed portrait
    plans = plan_pages([_sp(1, 648, 432, rotate=90)], Config())
    assert len(plans) == 1


def _ir(*blocks: Block) -> BookIR:
    return BookIR(blocks=list(blocks))


def test_drop_furniture() -> None:
    ir = _ir(
        Block(id="h", kind=BlockKind.PAGE_HEADER, text="CHAPTER ONE", page=1),
        Block(id="n", kind=BlockKind.PAGE_NUMBER, text="12", page=1),
        Block(id="p", kind=BlockKind.PARAGRAPH, text="Body.", page=1),
        Block(id="f", kind=BlockKind.PAGE_FOOTER, text="B", page=1),
    )
    out, changes = drop_furniture(ir, Config())
    assert [b.id for b in out.blocks] == ["p"]
    assert [c.block_id for c in changes] == ["h", "n", "f"]
    assert all(c.rule == "furniture" and c.action == "drop" for c in changes)
    assert len(ir.blocks) == 4  # input untouched


def test_apply_rules_respects_config() -> None:
    ir = _ir(Block(id="h", kind=BlockKind.PAGE_HEADER, text="X", page=0))
    cfg = Config.model_validate({"cleanup": {"drop_furniture": False}})
    out, changes, applied = apply_rules(ir, cfg)
    assert "furniture" not in applied
    assert [b.kind for b in out.blocks] == [BlockKind.PAGE_HEADER]
    assert not [c for c in changes if c.rule == "furniture"]


def test_classify_page_numbers() -> None:
    assert classify("page_header", "12") is BlockKind.PAGE_NUMBER
    assert classify("page_footer", "xiv") is BlockKind.PAGE_NUMBER
    assert classify("page_footer", "— 7 —") is BlockKind.PAGE_NUMBER
    assert classify("page_header", "DR. JEKYLL AND MR. HYDE") is BlockKind.PAGE_HEADER
    assert classify("text", "12") is BlockKind.PARAGRAPH
    assert classify("section_header", "One") is BlockKind.HEADING
    assert classify("weird_label", "x") is BlockKind.OTHER


def test_resolve_metadata_precedence() -> None:
    ir = _ir(Block(id="h", kind=BlockKind.HEADING, level=1, text="THE HEADING", page=0))
    cfg = Config()
    meta = resolve_metadata(ir, cfg, {"Title": "PDF Title", "Author": "A and B"}, "slug")
    assert meta["title"] == "PDF Title"
    assert meta["author"] == ["A", "B"]
    assert meta["identifier"][0]["text"].startswith("urn:uuid:")

    meta = resolve_metadata(ir, cfg, {"Title": "scan0001.pdf"}, "slug")
    assert meta["title"] == "The Heading"

    cfg = Config.model_validate({"metadata": {"title": "Mine", "isbn": "9780000000002"}})
    meta = resolve_metadata(ir, cfg, {"Title": "PDF Title"}, "slug")
    assert meta["title"] == "Mine"
    assert meta["identifier"] == [{"scheme": "ISBN", "text": "9780000000002"}]

    meta = resolve_metadata(_ir(), Config(), {}, "my-book")
    assert meta["title"] == "My Book"


def test_parse_epubcheck() -> None:
    data = {
        "checker": {"checkerVersion": "5.1.0"},
        "messages": [
            {
                "ID": "RSC-005",
                "severity": "ERROR",
                "message": "bad",
                "locations": [{"path": "a.xhtml", "line": 3}, {"path": "b.xhtml", "line": 9}],
            },
            {"ID": "OPF-003", "severity": "WARNING", "message": "meh", "locations": []},
            {"ID": "X", "severity": "USAGE", "message": "fyi", "locations": []},
        ],
    }
    out = parse_epubcheck(data)
    assert out["errors"] == 2
    assert out["warnings"] == 1
    assert out["messages"][0]["path"] == "a.xhtml"
    assert out["checker_version"] == "5.1.0"
