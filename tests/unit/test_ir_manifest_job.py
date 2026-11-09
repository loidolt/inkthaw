import json
from pathlib import Path

import pytest

from inkthaw.ir import IR_VERSION, Block, BlockKind, BookIR, Page
from inkthaw.job import Job, sha256_file, slugify
from inkthaw.manifest import Manifest


def sample_ir() -> BookIR:
    return BookIR(
        engine="test",
        pages=[Page(index=0, width=100, height=200, image_path="20_clean/p0001.png")],
        blocks=[
            Block(id="b1", kind=BlockKind.HEADING, level=1, text="One", page=0),
            Block(id="b2", kind=BlockKind.PARAGRAPH, text="Body", page=0, bbox=(1, 2, 3, 4)),
        ],
    )


def test_ir_roundtrip(tmp_path: Path) -> None:
    ir = sample_ir()
    path = tmp_path / "ir.json"
    ir.save(path)
    loaded = BookIR.load(path)
    assert loaded == ir
    assert loaded.blocks[1].bbox == (1, 2, 3, 4)
    assert loaded.page_blocks(0)[0].kind is BlockKind.HEADING


def test_ir_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "ir.json"
    data = json.loads(sample_ir().model_dump_json())
    data["ir_version"] = IR_VERSION + 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="version"):
        BookIR.load(path)


def test_block_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        Block.model_validate({"id": "x", "kind": "paragraph", "page": 0, "colour": "red"})


def test_manifest_roundtrip(tmp_path: Path) -> None:
    m = Manifest(slug="book")
    rec = m.stage("ingest")
    rec.status = "done"
    rec.info = {"pages": 3}
    path = tmp_path / "manifest.json"
    m.save(path)
    loaded = Manifest.load(path)
    assert loaded.stages["ingest"].status == "done"
    assert loaded.stages["ingest"].info == {"pages": 3}


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("My Book (1902) scan", "my-book-1902-scan"),
        ("Ærø – Œuvres complètes", "aero-oeuvres-completes"),
        ("___", "book"),
    ],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_slugify_truncated_names_stay_apart() -> None:
    base = "The History of the Decline and Fall of the Roman Empire - Volume"
    one, two = slugify(f"{base} 1"), slugify(f"{base} 2")
    assert one != two
    assert len(one) <= 60 and len(two) <= 60
    assert one.startswith("the-history-of-the-decline-and-fall-of-the-roman")
    assert one == slugify(f"{base} 1")  # stable
    assert slugify("x" * 60) == "x" * 60  # fits: unchanged


def test_job_paths(tmp_path: Path) -> None:
    job = Job(tmp_path / "book")
    assert job.slug == "book"
    assert job.raw_ir == tmp_path / "book" / "30_ir" / "raw.json"
    assert job.clean_ir == tmp_path / "book" / "40_ir" / "clean.json"
    (tmp_path / "book" / "10_pages").mkdir(parents=True)
    f = tmp_path / "book" / "10_pages" / "p0001.png"
    f.write_bytes(b"x")
    assert job.rel(f) == "10_pages/p0001.png"
    assert job.abs("10_pages/p0001.png") == f
    assert len(sha256_file(f)) == 64
