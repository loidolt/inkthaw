"""Poppler wrappers: page geometry, embedded images, text layer, rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rebind import tools


@dataclass
class EmbeddedImage:
    width: int
    height: int
    color: str
    x_ppi: float
    y_ppi: float
    encoding: str


@dataclass
class PdfPage:
    number: int  # 1-based
    width_pt: float
    height_pt: float
    rotate: int = 0
    images: list[EmbeddedImage] = field(default_factory=list)

    @property
    def display_size(self) -> tuple[float, float]:
        """Size after applying /Rotate (what a viewer shows)."""
        if self.rotate % 180 == 90:
            return self.height_pt, self.width_pt
        return self.width_pt, self.height_pt

    @property
    def aspect(self) -> float:
        w, h = self.display_size
        return w / h if h else 0.0

    @property
    def scan_ppi(self) -> float | None:
        """PPI of the dominant embedded image, if the page looks like a scan."""
        imgs = [i for i in self.images if i.x_ppi > 0]
        if not imgs:
            return None
        big = max(imgs, key=lambda i: i.width * i.height)
        return round((big.x_ppi + big.y_ppi) / 2, 1)


_PAGE_SIZE_RE = re.compile(r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts")
_PAGE_ROT_RE = re.compile(r"^Page\s+(\d+)\s+rot:\s+(-?\d+)")


def parse_pdfinfo(text: str) -> tuple[dict[str, str], dict[int, PdfPage]]:
    """Parse `pdfinfo -f 1 -l N` output into (document fields, pages by number)."""
    fields: dict[str, str] = {}
    pages: dict[int, PdfPage] = {}
    for line in text.splitlines():
        if m := _PAGE_SIZE_RE.match(line):
            n = int(m.group(1))
            pages[n] = PdfPage(n, float(m.group(2)), float(m.group(3)))
        elif m := _PAGE_ROT_RE.match(line):
            n = int(m.group(1))
            if n in pages:
                pages[n].rotate = int(m.group(2)) % 360
        elif ":" in line and not line.startswith("Page "):
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, pages


def parse_pdfimages_list(text: str) -> dict[int, list[EmbeddedImage]]:
    """Parse `pdfimages -list` output, keeping only real images (not masks)."""
    out: dict[int, list[EmbeddedImage]] = {}
    for line in text.splitlines()[2:]:
        cols = line.split()
        if len(cols) < 14 or cols[2] != "image":
            continue
        try:
            page = int(cols[0])
            img = EmbeddedImage(
                width=int(cols[3]),
                height=int(cols[4]),
                color=cols[5],
                encoding=cols[8],
                x_ppi=float(cols[12]),
                y_ppi=float(cols[13]),
            )
        except ValueError:
            continue
        out.setdefault(page, []).append(img)
    return out


def inspect(pdf: Path) -> tuple[dict[str, str], list[PdfPage]]:
    head = tools.run(["pdfinfo", "-enc", "UTF-8", pdf]).stdout
    fields, _ = parse_pdfinfo(head)
    try:
        count = int(fields.get("Pages", "0"))
    except ValueError:
        count = 0
    if count == 0:
        return fields, []
    detail = tools.run(["pdfinfo", "-f", "1", "-l", str(count), pdf]).stdout
    _, pages = parse_pdfinfo(detail)
    images = parse_pdfimages_list(tools.run(["pdfimages", "-list", pdf]).stdout)
    for n, page in pages.items():
        page.images = images.get(n, [])
    return fields, [pages[n] for n in sorted(pages)]


def text_chars_per_page(pdf: Path) -> list[int]:
    """Non-whitespace character count of the existing text layer, per page."""
    out = tools.run(["pdftotext", "-enc", "UTF-8", pdf, "-"]).stdout
    chunks = out.split("\f")
    if chunks and not chunks[-1].strip():
        chunks = chunks[:-1]
    return [len(re.sub(r"\s+", "", c)) for c in chunks]


def render_page(
    pdf: Path,
    page: int,
    out_png: Path,
    *,
    dpi: int,
    gray: bool,
    crop: tuple[int, int, int, int] | None = None,
) -> Path:
    """Render one page to PNG with pdftoppm. crop = (x, y, w, h) in output pixels."""
    prefix = out_png.with_suffix("")
    args: list[str | Path] = ["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page)]
    if gray:
        args.append("-gray")
    if crop is not None:
        x, y, w, h = crop
        args += ["-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h)]
    args += ["-png", "-singlefile", pdf, prefix]
    tools.run(args)
    return out_png


def extract_page_image(pdf: Path, page: int, out_png: Path) -> Path | None:
    """Extract the single embedded image of a page as PNG. None if not exactly one."""
    prefix = out_png.with_name(out_png.stem + "-x")
    tools.run(["pdfimages", "-f", str(page), "-l", str(page), "-png", pdf, prefix])
    produced = sorted(prefix.parent.glob(prefix.name + "-*.png"))
    if len(produced) != 1:
        for p in produced:
            p.unlink(missing_ok=True)
        return None
    produced[0].replace(out_png)
    return out_png
