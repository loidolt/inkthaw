"""Native EPUB 3 writer: BookIR -> XHTML chapters, nav, OPF -> zip.

Standard library only (zipfile, string building with XML escaping) plus
Pillow, which rebind already depends on, to read cover dimensions and to
convert images that are not EPUB core media types. Replaces pandoc (GPL) as
the default build backend so the desktop and iOS apps can ship without it.

Layout of the container (the same paths pandoc uses):

    mimetype                       stored, first
    META-INF/container.xml
    EPUB/content.opf
    EPUB/nav.xhtml                 EPUB 3 navigation (toc + landmarks)
    EPUB/toc.ncx                   EPUB 2 fallback for older readers
    EPUB/styles/*.css
    EPUB/text/cover.xhtml, title_page.xhtml, ch001.xhtml ...
    EPUB/media/*                   cover and figures
"""

from __future__ import annotations

import html
import io
import os
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rebind.ir import Block, BlockKind, BookIR

GENERATOR = "rebind"

# XML 1.0 forbids most C0 controls; OCR occasionally emits form feeds and the like.
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")
_WS = re.compile(r"\s+")
# Docling keeps the bullet/number glyph in list item text; strip a leading one.
_BULLET = re.compile(r"^\s*(?:[•·▪◦–—]|[-+*](?=\s|$)|\d+[.)](?=\s|$))\s*")
_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?)?)?)?$")
_YEAR = re.compile(r"\b(1[5-9]\d{2}|2\d{3})\b")

CORE_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
FRONT_ROLES = ("front_matter", "copyright")


def text(s: str) -> str:
    """Escape character data for XHTML."""
    return html.escape(_XML_INVALID.sub("", s), quote=False)


def attr(s: str) -> str:
    """Escape an attribute value (always written in double quotes)."""
    return html.escape(_XML_INVALID.sub("", s), quote=True)


def squash(s: str) -> str:
    return _WS.sub(" ", s)


# --- body rendering -----------------------------------------------------------


@dataclass
class Heading:
    level: int
    id: str
    text: str


@dataclass
class Chapter:
    name: str
    """File name inside EPUB/text/, e.g. ch001.xhtml."""
    parts: list[str] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    front_only: bool = True
    """Every block in it is front matter (body gets epub:type="frontmatter")."""

    @property
    def empty(self) -> bool:
        return not self.parts and not self.headings

    def title(self, fallback: str) -> str:
        return self.headings[0].text if self.headings else fallback


class _Renderer:
    def __init__(
        self,
        ir: BookIR,
        split_level: int,
        image_href: Callable[[str], str],
    ) -> None:
        self.split_level = split_level
        self.image_href = image_href
        self.chapters: list[Chapter] = []
        self.notes = {
            b.id: b for b in ir.blocks if b.kind == BlockKind.FOOTNOTE and b.attrs.get("linked")
        }
        # Notes that some prose block points at are written at the end of the
        # chapter holding that reference, not where they sit in reading order.
        self.referenced = {
            r["note"]
            for b in ir.blocks
            for r in b.attrs.get("noterefs") or []
            if r.get("note") in self.notes
        }
        self.note_numbers: dict[str, int] = {}
        self.ref_count = 0
        self.heading_count = 0
        self.list_tag: str | None = None
        self.in_front = False
        self.blocks = ir.blocks
        self._new_chapter()

    # chapter / container state

    @property
    def ch(self) -> Chapter:
        return self.chapters[-1]

    def _new_chapter(self) -> None:
        self.chapters.append(Chapter(f"ch{len(self.chapters) + 1:03d}.xhtml"))

    def _close_list(self) -> None:
        if self.list_tag:
            self.ch.parts.append(f"</{self.list_tag}>")
            self.list_tag = None

    def _set_front(self, front: bool) -> None:
        if front == self.in_front:
            return
        self._close_list()
        self.ch.parts.append('<div class="front-matter">' if front else "</div>")
        self.in_front = front

    def _end_chapter(self) -> None:
        self._close_list()
        self._set_front(False)
        if self.ch.notes:
            self.ch.parts.append('<section class="footnotes" epub:type="footnotes">')
            self.ch.parts.extend(self.ch.notes)
            self.ch.parts.append("</section>")
            self.ch.notes = []

    # inline text

    def prose(self, block: Block, start: int = 0) -> str:
        """Escaped block text with EPUB 3 noterefs inserted."""
        s = block.text
        out: list[str] = []
        pos = start
        for r in sorted(block.attrs.get("noterefs") or [], key=lambda r: r["start"]):
            if r["start"] < pos:
                continue
            out.append(text(squash(s[pos : r["start"]])))
            out.append(self._noteref(r["note"], s[r["start"] : r["end"]]))
            pos = r["end"]
        out.append(text(squash(s[pos:])))
        return "".join(out).strip()

    def _noteref(self, note_id: str, marker: str) -> str:
        note = self.notes.get(note_id)
        if note is None:
            return text(marker)  # the note was dropped; keep the marker as text
        self.ref_count += 1
        ref_id = f"fnref{self.ref_count}"
        n = self.note_numbers.get(note_id)
        if n is None:
            n = self.note_numbers[note_id] = len(self.note_numbers) + 1
            body = text(squash(note.text).strip())
            self.ch.notes.append(
                f'<aside id="fn{n}" epub:type="footnote" role="doc-footnote">'
                f'<p><a href="#{ref_id}" role="doc-backlink">{n}.</a> {body}</p></aside>'
            )
        return (
            f'<a href="#fn{n}" id="{ref_id}" class="footnote-ref" '
            f'epub:type="noteref" role="doc-noteref">{n}</a>'
        )

    # blocks

    def render(self) -> list[Chapter]:
        for b in self.blocks:
            self.block(b)
        self._end_chapter()
        chapters = [c for c in self.chapters if not c.empty]
        if not chapters:
            chapters = [Chapter("ch001.xhtml")]
        for i, c in enumerate(chapters, 1):
            c.name = f"ch{i:03d}.xhtml"
        return chapters

    def block(self, b: Block) -> None:
        front = b.attrs.get("role") in FRONT_ROLES
        if b.kind == BlockKind.HEADING:
            level = min(max(b.level or 1, 1), 6)
            title = squash(b.text).strip()
            if not title:
                return
            if level <= self.split_level and not self.ch.empty:
                self._end_chapter()
                self._new_chapter()
            self._set_front(front)
            self._close_list()
            self.heading_count += 1
            hid = f"h{self.heading_count}"
            self.ch.headings.append(Heading(level, hid, title))
            self.ch.parts.append(f'<h{level} id="{hid}">{text(title)}</h{level}>')
            self.ch.front_only = self.ch.front_only and front
            return

        html_out = self._body_block(b)
        if html_out is None:
            return
        self._set_front(front)
        self.ch.front_only = self.ch.front_only and front
        if b.kind == BlockKind.LIST_ITEM:
            tag = "ol" if b.attrs.get("enumerated") else "ul"
            if self.list_tag != tag:
                self._close_list()
                self.ch.parts.append(f"<{tag}>")
                self.list_tag = tag
        else:
            self._close_list()
        self.ch.parts.append(html_out)

    def _body_block(self, b: Block) -> str | None:
        """XHTML for a non-heading block, or None to drop it."""
        k = b.kind
        if k == BlockKind.LIST_ITEM:
            m = _BULLET.match(b.text)
            body = self.prose(b, m.end() if m else 0)
            return f"<li>{body}</li>" if body else None
        if k == BlockKind.TABLE:
            return self._table(b)
        if k == BlockKind.IMAGE:
            return self._image(b)
        if k == BlockKind.FOOTNOTE:
            if b.id in self.referenced:
                return None  # written at the end of the referencing chapter
            body = text(squash(b.text).strip())
            return f'<div class="footnote-text"><p>{body}</p></div>' if body else None
        if k == BlockKind.CAPTION:
            body = self.prose(b)
            return f'<div class="caption"><p>{body}</p></div>' if body else None
        # paragraph, other, and any furniture a profile chose to keep
        body = self.prose(b)
        return f"<p>{body}</p>" if body else None

    def _table(self, b: Block) -> str | None:
        rows: list[list[str]] = [
            [str(c) for c in r] for r in b.attrs.get("rows") or [] if any(str(c).strip() for c in r)
        ]
        if not rows:
            body = self.prose(b)
            return f"<p>{body}</p>" if body else None
        width = max(len(r) for r in rows)

        def row(cells: list[str], tag: str) -> str:
            cells = cells + [""] * (width - len(cells))
            return (
                "<tr>"
                + "".join(f"<{tag}>{text(squash(c).strip())}</{tag}>" for c in cells)
                + "</tr>"
            )

        out = ["<table>"]
        if caption := squash(b.attrs.get("caption") or "").strip():
            out.append(f"<caption>{text(caption)}</caption>")
        out.append("<thead>" + row(rows[0], "th") + "</thead>")
        if len(rows) > 1:
            out.append("<tbody>" + "".join(row(r, "td") for r in rows[1:]) + "</tbody>")
        out.append("</table>")
        return "".join(out)

    def _image(self, b: Block) -> str | None:
        path = b.attrs.get("image_path")
        caption = squash(b.attrs.get("caption") or b.text or "").strip()
        if not path:
            return f"<p>{text(caption)}</p>" if caption else None
        src = "../" + self.image_href(path)
        if caption:
            return (
                f'<figure><img src="{attr(src)}" alt="{attr(caption)}"/>'
                f"<figcaption>{text(caption)}</figcaption></figure>"
            )
        return f'<p class="image"><img src="{attr(src)}" alt=""/></p>'


def render_chapters(
    ir: BookIR, split_level: int = 1, image_href: Callable[[str], str] | None = None
) -> list[Chapter]:
    """Split the book into chapters at headings of level <= split_level.

    image_href maps an IR image path to an href relative to EPUB/ (e.g.
    "media/p0001-01.png"); chapters live in EPUB/text/.
    """
    return _Renderer(ir, split_level, image_href or (lambda p: p)).render()


# --- navigation ---------------------------------------------------------------


@dataclass
class NavPoint:
    level: int
    href: str
    label: str
    children: list[NavPoint] = field(default_factory=list)


def toc_tree(chapters: list[Chapter], toc_depth: int, book_title: str) -> list[NavPoint]:
    """Nested TOC entries for headings with level <= toc_depth.

    A chapter without a heading (the material before the first one) is listed
    under the book title, as pandoc does. Levels that skip (h1 -> h3) nest
    under the nearest shallower entry.
    """
    flat: list[NavPoint] = []
    for c in chapters:
        href = f"text/{c.name}"
        if not c.headings:
            flat.append(NavPoint(1, href, book_title))
        for h in c.headings:
            if h.level <= toc_depth:
                flat.append(NavPoint(h.level, f"{href}#{h.id}", h.text))
    if not flat:  # e.g. toc_depth 1 but the book only has level-2 headings
        flat = [NavPoint(1, f"text/{c.name}", c.title(book_title)) for c in chapters]

    roots: list[NavPoint] = []
    stack: list[NavPoint] = []
    for p in flat:
        while stack and stack[-1].level >= p.level:
            stack.pop()
        (stack[-1].children if stack else roots).append(p)
        stack.append(p)
    return roots


def _nav_ol(points: list[NavPoint], depth: int = 0) -> str:
    pad = "  " * depth
    out = [f"{pad}<ol>" if depth else f'{pad}<ol class="toc">']
    for p in points:
        link = f'<a href="{attr(p.href)}">{text(p.label)}</a>'
        if p.children:
            out.append(f"{pad}  <li>{link}")
            out.append(_nav_ol(p.children, depth + 2))
            out.append(f"{pad}  </li>")
        else:
            out.append(f"{pad}  <li>{link}</li>")
    out.append(f"{pad}</ol>")
    return "\n".join(out)


def _ncx_points(points: list[NavPoint], counter: list[int], depth: int = 1) -> str:
    out = []
    pad = "  " * depth
    for p in points:
        counter[0] += 1
        n = counter[0]
        out.append(
            f'{pad}<navPoint id="navPoint-{n}" playOrder="{n}">'
            f"<navLabel><text>{text(p.label)}</text></navLabel>"
            f'<content src="{attr(p.href)}"/>'
        )
        if p.children:
            out.append(_ncx_points(p.children, counter, depth + 1))
        out.append(f"{pad}</navPoint>")
    return "\n".join(out)


def _depth(points: list[NavPoint]) -> int:
    return 1 + max((_depth(p.children) for p in points if p.children), default=0)


# --- documents ----------------------------------------------------------------


def xhtml(
    title: str,
    body: str,
    lang: str,
    css: Iterable[str],
    *,
    body_attrs: str = "",
    css_prefix: str = "../",
) -> str:
    links = "".join(
        f'\n<link rel="stylesheet" type="text/css" href="{attr(css_prefix + c)}"/>' for c in css
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
        f' lang="{attr(lang)}" xml:lang="{attr(lang)}">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        f'<meta name="generator" content="{GENERATOR}"/>\n'
        f"<title>{text(title)}</title>{links}\n"
        "</head>\n"
        f"<body{body_attrs}>\n{body}\n</body>\n"
        "</html>\n"
    )


def epub_date(value: str) -> str | None:
    """A W3CDTF date for dc:date: '1886', '1886-01', '1886-01-05'... else the
    first plausible year in the string, else None."""
    v = value.strip()
    if _DATE.match(v):
        return v
    m = _YEAR.search(v)
    return m.group(1) if m else None


def identifier(meta: dict[str, Any]) -> str:
    ident = (meta.get("identifier") or [{}])[0]
    scheme = str(ident.get("scheme", "")).upper()
    value = str(ident.get("text", "")).strip()
    if scheme == "ISBN":
        digits = re.sub(r"[^0-9Xx]", "", value).upper()
        return f"urn:isbn:{digits}"
    return value or "urn:uuid:00000000-0000-0000-0000-000000000000"


def modified_now() -> datetime:
    """Build time, or SOURCE_DATE_EPOCH for reproducible builds."""
    if epoch := os.environ.get("SOURCE_DATE_EPOCH"):
        try:
            return datetime.fromtimestamp(int(epoch), UTC)
        except ValueError:
            pass
    return datetime.now(UTC).replace(microsecond=0)


@dataclass
class Item:
    id: str
    href: str
    media_type: str
    data: bytes
    properties: str = ""


def opf(
    meta: dict[str, Any],
    items: list[Item],
    spine: list[tuple[str, bool]],
    modified: datetime,
    cover_id: str | None,
    warnings: list[str],
) -> str:
    lang = str(meta.get("lang") or "en")
    m = [
        f'<dc:identifier id="pub-id">{text(identifier(meta))}</dc:identifier>',
        f"<dc:title>{text(str(meta['title']))}</dc:title>",
        f"<dc:language>{text(lang)}</dc:language>",
    ]
    for i, author in enumerate(meta.get("author") or [], 1):
        m.append(f'<dc:creator id="creator{i}">{text(str(author))}</dc:creator>')
        m.append(f'<meta refines="#creator{i}" property="role" scheme="marc:relators">aut</meta>')
    if publisher := meta.get("publisher"):
        m.append(f"<dc:publisher>{text(str(publisher))}</dc:publisher>")
    if date := meta.get("date"):
        if (d := epub_date(str(date))) is not None:
            m.append(f"<dc:date>{text(d)}</dc:date>")
            if d != str(date).strip():
                warnings.append(f"metadata.date {date!r} written as {d!r} (W3CDTF)")
        else:
            warnings.append(f"metadata.date {date!r} is not a date; left out of the EPUB")
    if rights := meta.get("rights"):
        m.append(f"<dc:rights>{text(str(rights))}</dc:rights>")
    m.append(f'<meta property="dcterms:modified">{modified:%Y-%m-%dT%H:%M:%SZ}</meta>')
    if cover_id:
        m.append(f'<meta name="cover" content="{cover_id}"/>')
    has_images = any(it.media_type.startswith("image/") for it in items)
    m += [
        '<meta property="schema:accessMode">textual</meta>',
        *(['<meta property="schema:accessMode">visual</meta>'] if has_images else []),
        '<meta property="schema:accessModeSufficient">textual</meta>',
        '<meta property="schema:accessibilityFeature">structuralNavigation</meta>',
        '<meta property="schema:accessibilityFeature">tableOfContents</meta>',
        '<meta property="schema:accessibilityFeature">readingOrder</meta>',
        '<meta property="schema:accessibilityHazard">none</meta>',
    ]
    manifest = []
    for it in items:
        props = f' properties="{it.properties}"' if it.properties else ""
        manifest.append(
            f'<item id="{it.id}" href="{attr(it.href)}" media-type="{it.media_type}"{props}/>'
        )
    spine_xml = [
        f'<itemref idref="{idref}"' + ("" if linear else ' linear="no"') + "/>"
        for idref, linear in spine
    ]
    nl = "\n    "
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="pub-id" xml:lang="{attr(lang)}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"    {nl.join(m)}\n"
        "  </metadata>\n"
        "  <manifest>\n"
        f"    {nl.join(manifest)}\n"
        "  </manifest>\n"
        '  <spine toc="ncx">\n'
        f"    {nl.join(spine_xml)}\n"
        "  </spine>\n"
        "</package>\n"
    )


CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    "  <rootfiles>\n"
    '    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>\n'
    "  </rootfiles>\n"
    "</container>\n"
)


def _image_data(src: Path) -> tuple[bytes, str, str]:
    """(bytes, extension, media type); non-core formats are converted to PNG."""
    ext = src.suffix.lower()
    if ext in CORE_IMAGE_TYPES:
        return src.read_bytes(), ".jpg" if ext == ".jpeg" else ext, CORE_IMAGE_TYPES[ext]
    from PIL import Image

    with Image.open(src) as im:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    return buf.getvalue(), ".png", "image/png"


def _image_size(data: bytes) -> tuple[int, int] | None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


@dataclass
class EpubResult:
    chapters: int
    images: int
    notes: int
    nav_entries: int
    warnings: list[str] = field(default_factory=list)


def write_epub(
    dest: Path,
    ir: BookIR,
    meta: dict[str, Any],
    *,
    image_source: Callable[[str], Path],
    css: list[tuple[str, bytes]],
    cover: Path | None = None,
    split_level: int = 1,
    toc_depth: int = 2,
    modified: datetime | None = None,
) -> EpubResult:
    """Write an EPUB 3 file for `ir`.

    meta: as returned by build.resolve_metadata (title, lang, author,
    identifier, publisher, date, rights). image_source maps an IR image path to
    the file on disk. css: (file name, content) pairs, linked in order.
    """
    title = str(meta["title"])
    lang = str(meta.get("lang") or "en")
    modified = modified or modified_now()
    warnings: list[str] = []
    items: list[Item] = []
    used_names: set[str] = set()

    def media_name(stem: str, ext: str) -> str:
        name, n = f"{stem}{ext}", 1
        while name in used_names:
            n += 1
            name = f"{stem}-{n}{ext}"
        used_names.add(name)
        return name

    images: dict[str, str] = {}

    def image_href(rel: str) -> str:
        if rel not in images:
            data, ext, mt = _image_data(image_source(rel))
            stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(rel).stem) or "image"
            href = f"media/{media_name(stem, ext)}"
            items.append(Item(f"img{len(images) + 1}", href, mt, data))
            images[rel] = href
        return images[rel]

    chapters = render_chapters(ir, split_level, image_href)
    css_names = [f"styles/{name}" for name, _ in css]
    for i, (name, data) in enumerate(css, 1):
        items.append(Item(f"css{i}", f"styles/{name}", "text/css", data))

    spine: list[tuple[str, bool]] = []
    landmarks: list[tuple[str, str, str]] = []
    docs: list[Item] = []

    cover_id = None
    if cover is not None:
        data, ext, mt = _image_data(cover)
        href = f"media/{media_name('cover', ext)}"
        cover_id = "cover-image"
        items.append(Item(cover_id, href, mt, data, "cover-image"))
        size = _image_size(data)
        if size:
            w, h = size
            body = (
                '<div id="cover-image">\n'
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
                f' version="1.1" width="100%" height="100%" viewBox="0 0 {w} {h}"'
                ' preserveAspectRatio="xMidYMid">\n'
                f'<image width="{w}" height="{h}" xlink:href="../{attr(href)}"/>\n'
                "</svg>\n</div>"
            )
            props = "svg"
        else:
            body = f'<div id="cover-image"><img src="../{attr(href)}" alt="Cover"/></div>'
            props = ""
        docs.append(
            Item(
                "cover",
                "text/cover.xhtml",
                "application/xhtml+xml",
                xhtml(title, body, lang, css_names, body_attrs=' id="cover"').encode(),
                props,
            )
        )
        spine.append(("cover", True))
        landmarks.append(("text/cover.xhtml", "cover", "Cover"))

    authors = [str(a) for a in meta.get("author") or []]
    tp = [
        '<section epub:type="titlepage" class="titlepage">',
        f'<h1 class="title">{text(title)}</h1>',
    ]
    tp += [f'<p class="author">{text(a)}</p>' for a in authors]
    tp.append("</section>")
    docs.append(
        Item(
            "title-page",
            "text/title_page.xhtml",
            "application/xhtml+xml",
            xhtml(
                title, "\n".join(tp), lang, css_names, body_attrs=' epub:type="frontmatter"'
            ).encode(),
        )
    )
    spine.append(("title-page", True))
    landmarks.append(("text/title_page.xhtml", "titlepage", "Title Page"))

    toc = toc_tree(chapters, toc_depth, title)
    landmarks.append(("nav.xhtml#toc", "toc", "Table of Contents"))
    if body_ch := next((c for c in chapters if not c.front_only), None):
        landmarks.append((f"text/{body_ch.name}", "bodymatter", "Start of Content"))
    lm = "\n".join(
        f'    <li><a epub:type="{t}" href="{attr(h)}">{text(label)}</a></li>'
        for h, t, label in landmarks
    )
    nav_body = (
        '<nav epub:type="toc" role="doc-toc" id="toc">\n'
        f'<h1 id="toc-title">{text(title)}</h1>\n'
        f"{_nav_ol(toc)}\n"
        "</nav>\n"
        '<nav epub:type="landmarks" id="landmarks" hidden="hidden">\n'
        f"  <ol>\n{lm}\n  </ol>\n"
        "</nav>"
    )
    nav = Item(
        "nav",
        "nav.xhtml",
        "application/xhtml+xml",
        xhtml(
            title, nav_body, lang, css_names, body_attrs=' epub:type="frontmatter"', css_prefix=""
        ).encode(),
        "nav",
    )
    docs.append(nav)
    spine.append(("nav", True))

    for i, c in enumerate(chapters, 1):
        etype = "frontmatter" if c.front_only else "bodymatter"
        docs.append(
            Item(
                f"ch{i:03d}",
                f"text/{c.name}",
                "application/xhtml+xml",
                xhtml(
                    c.title(title),
                    "\n".join(c.parts),
                    lang,
                    css_names,
                    body_attrs=f' epub:type="{etype}"',
                ).encode(),
            )
        )
        spine.append((f"ch{i:03d}", True))

    uid = identifier(meta)
    ncx = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="{attr(uid)}"/>\n'
        f'    <meta name="dtb:depth" content="{_depth(toc)}"/>\n'
        '    <meta name="dtb:totalPageCount" content="0"/>\n'
        '    <meta name="dtb:maxPageNumber" content="0"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{text(title)}</text></docTitle>\n"
        "  <navMap>\n"
        f"{_ncx_points(toc, [0], 2)}\n"
        "  </navMap>\n"
        "</ncx>\n"
    )
    ncx_item = Item("ncx", "toc.ncx", "application/x-dtbncx+xml", ncx.encode())

    all_items = [ncx_item, *docs, *items]
    package = opf(meta, all_items, spine, modified, cover_id, warnings)

    stamp = modified.timetuple()[:6]
    if stamp[0] < 1980:
        stamp = (1980, 1, 1, 0, 0, 0)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as z:

        def add(name: str, data: bytes, compress: bool = True) -> None:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)

        add("mimetype", b"application/epub+zip", compress=False)
        add("META-INF/container.xml", CONTAINER_XML.encode())
        add("EPUB/content.opf", package.encode())
        for it in all_items:
            # PNG/JPEG/GIF are already compressed.
            add(f"EPUB/{it.href}", it.data, compress=it.media_type not in _COMPRESSED)
    tmp.replace(dest)

    def count(points: list[NavPoint]) -> int:
        return sum(1 + count(p.children) for p in points)

    return EpubResult(
        chapters=len(chapters),
        images=len(images),
        notes=sum(1 for _ in _notes_in(chapters)),
        nav_entries=count(toc),
        warnings=warnings,
    )


_COMPRESSED = frozenset({"image/png", "image/jpeg", "image/gif"})


def _notes_in(chapters: list[Chapter]) -> Iterable[str]:
    for c in chapters:
        for p in c.parts:
            if p.startswith("<aside "):
                yield p
