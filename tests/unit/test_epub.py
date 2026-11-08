"""Native EPUB 3 writer (rebind.epub) and the build stage's native backend."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from epubbook import META, PROSE, b, read, sample_ir, write_image
from rich.console import Console

from rebind import epub, tools
from rebind.config import Config
from rebind.ir import BlockKind, BookIR
from rebind.job import Job
from rebind.pipeline import StageContext
from rebind.stages.build import STAGE, _bundled_css

XHTML = "{http://www.w3.org/1999/xhtml}"
OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
EPUB_NS = "{http://www.idpf.org/2007/ops}"
FIXED = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)


def _write(tmp_path: Path, ir: BookIR | None = None, **kw) -> tuple[Path, epub.EpubResult]:
    img = write_image(tmp_path / "30_ir" / "images" / "p0001-01.png")
    ir = ir or sample_ir("30_ir/images/p0001-01.png")
    dest = tmp_path / "book.epub"
    kw.setdefault("css", [("epub.css", _bundled_css())])
    res = epub.write_epub(
        dest, ir, kw.pop("meta", META), image_source=lambda rel: img.parents[2] / rel, **kw
    )
    return dest, res


def _parse(epub_path: Path, name: str) -> ET.Element:
    return ET.fromstring(read(epub_path, name))


def _chapter_text(epub_path: Path) -> str:
    with zipfile.ZipFile(epub_path) as z:
        names = sorted(n for n in z.namelist() if re.match(r"EPUB/text/ch\d+\.xhtml", n))
        return "\n".join(z.read(n).decode() for n in names)


# --- container ----------------------------------------------------------------


def test_container_layout_and_wellformed_xml(tmp_path: Path) -> None:
    dest, _ = _write(
        tmp_path, cover=write_image(tmp_path / "cover.png", (300, 450)), modified=FIXED
    )
    with zipfile.ZipFile(dest) as z:
        infos = z.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert infos[0].extra == b""
        assert z.read("mimetype") == b"application/epub+zip"
        names = z.namelist()
        for n in names:
            if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ET.fromstring(z.read(n))  # well-formed
    assert "EPUB/content.opf" in names
    assert "EPUB/nav.xhtml" in names and "EPUB/toc.ncx" in names
    assert "EPUB/text/cover.xhtml" in names and "EPUB/text/title_page.xhtml" in names
    assert "EPUB/styles/epub.css" in names
    container = _parse(dest, "META-INF/container.xml")
    assert container.find(".//{*}rootfile").get("full-path") == "EPUB/content.opf"  # type: ignore[union-attr]


def test_manifest_lists_every_file_and_spine_order(tmp_path: Path) -> None:
    dest, res = _write(tmp_path, cover=write_image(tmp_path / "cover.jpg", (300, 450)))
    opf = _parse(dest, "EPUB/content.opf")
    items = {i.get("id"): i for i in opf.iter(f"{OPF}item")}
    with zipfile.ZipFile(dest) as z:
        payload = {n[len("EPUB/") :] for n in z.namelist() if n.startswith("EPUB/")}
    assert {i.get("href") for i in items.values()} == payload - {"content.opf"}
    assert items["nav"].get("properties") == "nav"
    assert items["cover-image"].get("properties") == "cover-image"
    assert items["cover-image"].get("media-type") == "image/jpeg"
    assert items["cover"].get("properties") == "svg"
    spine = [r.get("idref") for r in opf.iter(f"{OPF}itemref")]
    assert spine[:3] == ["cover", "title-page", "nav"]
    assert spine[3:] == [f"ch{i:03d}" for i in range(1, res.chapters + 1)]
    assert opf.find(f"{OPF}spine").get("toc") == "ncx"  # type: ignore[union-attr]


# --- metadata -----------------------------------------------------------------


def test_opf_metadata(tmp_path: Path) -> None:
    dest, _ = _write(tmp_path, modified=FIXED)
    md = _parse(dest, "EPUB/content.opf").find(f"{OPF}metadata")
    assert md is not None
    assert md.findtext(f"{DC}title") == "Dr. Jekyll & Mr. Hyde"
    assert md.findtext(f"{DC}language") == "en"
    assert md.findtext(f"{DC}identifier") == "urn:isbn:9780141439737"
    assert [c.text for c in md.iter(f"{DC}creator")] == ["Robert Louis Stevenson", "A. N. Other"]
    assert md.findtext(f"{DC}publisher") == "Longmans, Green & Co."
    assert md.findtext(f"{DC}date") == "1886-01-05"
    assert md.findtext(f"{DC}rights") == "Public domain"
    props = {m.get("property"): m.text for m in md.iter(f"{OPF}meta") if m.get("property")}
    assert props["dcterms:modified"] == "2026-11-08T12:00:00Z"
    roles = [m for m in md.iter(f"{OPF}meta") if m.get("property") == "role"]
    assert [m.get("refines") for m in roles] == ["#creator1", "#creator2"]


def test_uuid_identifier_and_optional_fields(tmp_path: Path) -> None:
    meta = {
        "title": "T",
        "lang": "de",
        "identifier": [{"scheme": "UUID", "text": "urn:uuid:1234"}],
    }
    dest, _ = _write(tmp_path, meta=meta)
    opf = read(dest, "EPUB/content.opf")
    assert "urn:uuid:1234" in opf
    assert 'xml:lang="de"' in opf
    for tag in ("dc:creator", "dc:publisher", "dc:date", "dc:rights"):
        assert tag not in opf
    assert 'lang="de"' in read(dest, "EPUB/text/ch001.xhtml")
    assert 'content="urn:uuid:1234"' in read(dest, "EPUB/toc.ncx")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1886", "1886"),
        ("1886-01", "1886-01"),
        ("2026-11-08T21:36:56Z", "2026-11-08T21:36:56Z"),
        ("January 1886", "1886"),
        ("c. 1890?", "1890"),
        ("unknown", None),
    ],
)
def test_epub_date(raw: str, expected: str | None) -> None:
    assert epub.epub_date(raw) == expected


def test_bad_date_is_dropped_with_warning(tmp_path: Path) -> None:
    dest, res = _write(tmp_path, meta={**META, "date": "someday"})
    assert "dc:date" not in read(dest, "EPUB/content.opf")
    assert any("someday" in w for w in res.warnings)


def test_source_date_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert epub.modified_now() == datetime(1970, 1, 1, tzinfo=UTC)


# --- body ---------------------------------------------------------------------


def test_split_level_1(tmp_path: Path) -> None:
    dest, res = _write(tmp_path, split_level=1)
    # front matter before the first heading, Chapter I (+ Section A), Chapter II
    assert res.chapters == 3
    ch1, ch2, ch3 = (read(dest, f"EPUB/text/ch00{i}.xhtml") for i in (1, 2, 3))
    assert 'epub:type="frontmatter"' in ch1 and 'class="front-matter"' in ch1
    assert "© 1886 Longmans" in ch1
    assert 'epub:type="bodymatter"' in ch2
    assert '<h1 id="h1">Chapter I</h1>' in ch2 and '<h2 id="h2">Section A</h2>' in ch2
    assert "Chapter II" in ch3 and '<h3 id="h4">Deep section</h3>' in ch3
    assert "<title>Chapter I</title>" in ch2


def test_split_level_2(tmp_path: Path) -> None:
    _, res = _write(tmp_path, split_level=2)
    assert res.chapters == 4  # Section A gets its own file; h3 does not


def test_nav_nesting_and_depth(tmp_path: Path) -> None:
    dest, res = _write(tmp_path, toc_depth=3)
    nav = _parse(dest, "EPUB/nav.xhtml")
    toc = next(n for n in nav.iter(f"{XHTML}nav") if n.get(f"{EPUB_NS}type") == "toc")
    top = toc.find(f"{XHTML}ol")
    assert top is not None
    labels = [li.find(f"{XHTML}a").text for li in top.findall(f"{XHTML}li")]  # type: ignore[union-attr]
    assert labels == ["Dr. Jekyll & Mr. Hyde", "Chapter I", "Chapter II"]
    ch1 = top.findall(f"{XHTML}li")[1]
    assert [a.text for a in ch1.iter(f"{XHTML}a")] == ["Chapter I", "Section A"]
    assert ch1.find(f".//{XHTML}a[@href='text/ch002.xhtml#h2']") is not None
    ch2 = top.findall(f"{XHTML}li")[2]
    # h3 directly under h1 nests one level down
    assert [a.text for a in ch2.iter(f"{XHTML}a")] == ["Chapter II", "Deep section"]
    assert res.nav_entries == 5
    ncx = _parse(dest, "EPUB/toc.ncx")
    orders = [int(p.get("playOrder") or 0) for p in ncx.findall(".//{*}navPoint")]
    assert orders == [1, 2, 3, 4, 5]
    assert ncx.find(".//{*}meta[@name='dtb:depth']").get("content") == "2"  # type: ignore[union-attr]


def test_toc_depth_limits_entries(tmp_path: Path) -> None:
    _, res = _write(tmp_path, toc_depth=1)
    assert res.nav_entries == 3


def test_toc_falls_back_to_chapters_without_shallow_headings() -> None:
    ir = BookIR(
        blocks=[
            b("h", BlockKind.HEADING, "Only level two", level=2),
            b("p", BlockKind.PARAGRAPH, "x"),
        ]
    )
    chapters = epub.render_chapters(ir, split_level=2)
    tree = epub.toc_tree(chapters, toc_depth=1, book_title="Book")
    assert [(p.label, p.href) for p in tree] == [("Only level two", "text/ch001.xhtml")]


def test_landmarks(tmp_path: Path) -> None:
    dest, _ = _write(tmp_path, cover=write_image(tmp_path / "cover.png"))
    nav = read(dest, "EPUB/nav.xhtml")
    assert 'epub:type="cover" href="text/cover.xhtml"' in nav
    assert 'epub:type="bodymatter" href="text/ch002.xhtml"' in nav
    assert 'epub:type="toc" href="nav.xhtml#toc"' in nav


def test_footnotes_link_both_ways_in_same_chapter(tmp_path: Path) -> None:
    dest, res = _write(tmp_path)
    ch = read(dest, "EPUB/text/ch002.xhtml")
    assert (
        'Mr. Utterson<a href="#fn1" id="fnref1" class="footnote-ref" epub:type="noteref" '
        'role="doc-noteref">1</a> frowned &amp; said &lt;nothing&gt;.' in ch
    )
    assert '<aside id="fn1" epub:type="footnote" role="doc-footnote">' in ch
    assert '<a href="#fnref1" role="doc-backlink">1.</a> A note on Utterson.' in ch
    # the note is written once, after the chapter's text, not in reading order
    assert ch.count("A note on Utterson") == 1
    assert ch.index("Section A") < ch.index("<aside")
    # unmatched footnote stays as plain footnote text in place
    assert '<div class="footnote-text"><p>* stray note</p></div>' in ch
    assert res.notes == 1


def test_noteref_to_missing_note_keeps_marker() -> None:
    ir = BookIR(
        blocks=[
            b(
                "p",
                BlockKind.PARAGRAPH,
                "word* here",
                attrs={"noterefs": [{"start": 4, "end": 5, "note": "gone"}]},
            )
        ]
    )
    (ch,) = epub.render_chapters(ir)
    assert ch.parts == ["<p>word* here</p>"]


def test_lists_tables_images_escaping(tmp_path: Path) -> None:
    dest, res = _write(tmp_path)
    body = _chapter_text(dest)
    assert "<ul><li>first</li><li>second</li></ul>" in body.replace("\n", "")
    assert "<ol><li>numbered</li></ol>" in body.replace("\n", "")
    assert (
        "<table><caption>Men</caption><thead><tr><th>Name</th><th>Age</th></tr></thead>"
        "<tbody><tr><td>Hyde</td><td>?</td></tr><tr><td>Jekyll</td><td></td></tr></tbody></table>"
    ) in body
    assert '<div class="caption"><p>A caption.</p></div>' in body
    assert (
        '<figure><img src="../media/p0001-01.png" alt="The door"/>'
        "<figcaption>The door</figcaption></figure>"
    ) in body
    assert '<p class="image"><img src="../media/p0001-01.png" alt=""/></p>' in body
    assert res.images == 1  # same image used twice is stored once
    assert "<p>Ctrlchar and spaced text.</p>" in body
    assert "<p>12</p>" in body
    assert PROSE.strip() in body


def test_non_core_image_converted_to_png(tmp_path: Path) -> None:
    tif = write_image(tmp_path / "30_ir" / "images" / "scan.tif", fmt="TIFF")
    ir = BookIR(blocks=[b("i", BlockKind.IMAGE, attrs={"image_path": "30_ir/images/scan.tif"})])
    dest = tmp_path / "book.epub"
    epub.write_epub(
        dest, ir, META, image_source=lambda rel: tif.parents[2] / rel, css=[("a.css", b"")]
    )
    with zipfile.ZipFile(dest) as z:
        assert z.read("EPUB/media/scan.png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert 'media-type="image/png"' in read(dest, "EPUB/content.opf")


def test_extra_css_linked_in_order(tmp_path: Path) -> None:
    dest, _ = _write(tmp_path, css=[("epub.css", b"p{}"), ("extra.css", b"h1{}")])
    ch = read(dest, "EPUB/text/ch001.xhtml")
    assert ch.index("../styles/epub.css") < ch.index("../styles/extra.css")
    assert 'href="styles/extra.css"' in read(dest, "EPUB/nav.xhtml")
    assert read(dest, "EPUB/styles/extra.css") == "h1{}"


def test_cover_page_uses_image_size(tmp_path: Path) -> None:
    dest, _ = _write(tmp_path, cover=write_image(tmp_path / "cover.png", (300, 450)))
    cover = read(dest, "EPUB/text/cover.xhtml")
    assert 'viewBox="0 0 300 450"' in cover and 'xlink:href="../media/cover.png"' in cover
    assert '<meta name="cover" content="cover-image"/>' in read(dest, "EPUB/content.opf")


def test_title_page(tmp_path: Path) -> None:
    dest, _ = _write(tmp_path)
    tp = read(dest, "EPUB/text/title_page.xhtml")
    assert '<h1 class="title">Dr. Jekyll &amp; Mr. Hyde</h1>' in tp
    assert '<p class="author">A. N. Other</p>' in tp


def test_empty_book_is_still_a_valid_container(tmp_path: Path) -> None:
    dest, res = _write(tmp_path, ir=BookIR())
    assert res.chapters == 1
    nav = _parse(dest, "EPUB/nav.xhtml")
    assert len(list(nav.iter(f"{XHTML}li"))) >= 1


def test_empty_heading_is_skipped() -> None:
    ir = BookIR(blocks=[b("h", BlockKind.HEADING, "  ", level=1), b("p", BlockKind.PARAGRAPH, "x")])
    (ch,) = epub.render_chapters(ir)
    assert ch.headings == [] and ch.parts == ["<p>x</p>"]


# --- build stage --------------------------------------------------------------


def _job(tmp_path: Path) -> Job:
    job = Job(tmp_path / "job")
    for stage in ("rasterize", "cleanup", "build"):
        job.dir(stage).mkdir(parents=True)
    write_image(job.dir("rasterize") / "cover.png", (200, 300))
    write_image(job.root / "30_ir" / "images" / "p0001-01.png")
    sample_ir("30_ir/images/p0001-01.png").save(job.clean_ir)
    return job


def test_build_stage_native_needs_no_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    tools.version.cache_clear()
    job = _job(tmp_path)
    extra = tmp_path / "extra.css"
    extra.write_text("p { color: red }")
    cfg = Config.model_validate(
        {"metadata": {"title": "Given", "authors": ["Me"]}, "build": {"css": str(extra)}}
    )
    ctx = StageContext(job=job, cfg=cfg, manifest=job.load_manifest(), console=Console(quiet=True))
    key = STAGE.extra_key(ctx)
    assert key.startswith("native::")
    info = STAGE.run(ctx)
    tools.version.cache_clear()
    assert info["backend"] == "native"
    assert info["title"] == "Given" and info["authors"] == ["Me"]
    assert info["cover"] == "cover.png" and info["images"] == 1
    assert info["chapters"] == 3 and info["footnotes"] == 1
    assert sorted(p.name for p in job.dir("build").iterdir()) == ["book.epub"]
    assert read(job.epub, "EPUB/styles/extra.css") == "p { color: red }"


def test_build_stage_pandoc_backend_requires_pandoc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    tools.version.cache_clear()
    job = _job(tmp_path)
    cfg = Config.model_validate({"build": {"backend": "pandoc"}})
    ctx = StageContext(job=job, cfg=cfg, manifest=job.load_manifest(), console=Console(quiet=True))
    from rebind.errors import ToolMissingError

    with pytest.raises(ToolMissingError, match="pandoc"):
        STAGE.run(ctx)
    tools.version.cache_clear()


def test_pandoc_is_optional_tool() -> None:
    assert not any(t.required for t in tools.TOOLS.values())


@pytest.mark.skipif(tools.which("pandoc") is None, reason="pandoc not installed")
def test_build_stage_pandoc_backend(tmp_path: Path) -> None:
    tools.version.cache_clear()
    job = _job(tmp_path)
    cfg = Config.model_validate({"build": {"backend": "pandoc"}})
    ctx = StageContext(job=job, cfg=cfg, manifest=job.load_manifest(), console=Console(quiet=True))
    assert STAGE.extra_key(ctx).split(":")[1] == tools.version("pandoc")
    info = STAGE.run(ctx)
    assert info["backend"] == "pandoc"
    assert (job.dir("build") / "book.md").is_file()
    assert "Chapter I" in _chapter_text(job.epub)
