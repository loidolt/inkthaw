"""PDF access with pypdfium2 (PDFium): page geometry, embedded images, text layer, rendering.

PDFium is not thread-safe, not even across separate documents, so every call
into it holds one process-wide lock. Rendering a page takes tens of
milliseconds; PNG encoding, the slow part, happens outside the lock.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

from rebind.errors import RebindError

_LOCK = threading.RLock()

# Document-info keys worth keeping (same names pdfinfo printed).
METADATA_KEYS = ("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate")

# PDFium colour-space ids (FPDF_COLORSPACE_*) -> short names like pdfimages used.
_COLORSPACES = {
    1: "gray",  # DeviceGray
    2: "rgb",  # DeviceRGB
    3: "cmyk",  # DeviceCMYK
    4: "gray",  # CalGray
    5: "rgb",  # CalRGB
    6: "lab",
    7: "icc",
    8: "sep",
    9: "devn",
    10: "index",
    11: "pattern",
}
_ENCODINGS = {
    "DCTDecode": "jpeg",
    "JPXDecode": "jpx",
    "JBIG2Decode": "jbig2",
    "CCITTFaxDecode": "ccitt",
}


def versions() -> dict[str, str]:
    """pypdfium2 and PDFium build versions (recorded in the manifest, part of stage keys)."""
    return {"pypdfium2": str(pdfium.PYPDFIUM_INFO), "pdfium": str(pdfium.PDFIUM_INFO)}


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


@contextmanager
def _open(pdf: Path) -> Iterator[pdfium.PdfDocument]:
    with _LOCK:
        try:
            doc = pdfium.PdfDocument(pdf)
        except pdfium.PdfiumError as e:
            raise RebindError(f"{pdf}: cannot open PDF ({e})") from e
        try:
            yield doc
        finally:
            doc.close()


def _image_info(obj: pdfium.PdfImage) -> EmbeddedImage:
    md = obj.get_metadata()
    filters = obj.get_filters()
    encoding = next((_ENCODINGS[f] for f in filters if f in _ENCODINGS), "image")
    return EmbeddedImage(
        width=int(md.width),
        height=int(md.height),
        color=_COLORSPACES.get(int(md.colorspace), "unknown"),
        x_ppi=round(float(md.horizontal_dpi), 1),
        y_ppi=round(float(md.vertical_dpi), 1),
        encoding=encoding,
    )


def _images(page: pdfium.PdfPage) -> list[pdfium.PdfImage]:
    # Soft masks are attached to their image, not separate objects, so this
    # matches the "image" rows of `pdfimages -list`. Images inside form
    # XObjects are included.
    return [
        o
        for o in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE])
        if isinstance(o, pdfium.PdfImage)
    ]


def inspect(pdf: Path) -> tuple[dict[str, str], list[PdfPage]]:
    """Document metadata and per-page geometry plus embedded images."""
    with _open(pdf) as doc:
        meta = doc.get_metadata_dict(skip_empty=True)
        fields = {k: v.strip() for k, v in meta.items() if k in METADATA_KEYS and v.strip()}
        pages: list[PdfPage] = []
        for i in range(len(doc)):
            page = doc[i]
            try:
                rotate = page.get_rotation() % 360
                w, h = page.get_size()  # PDFium reports the size after /Rotate
                if rotate % 180 == 90:
                    w, h = h, w
                pages.append(
                    PdfPage(
                        number=i + 1,
                        width_pt=round(float(w), 2),
                        height_pt=round(float(h), 2),
                        rotate=rotate,
                        images=[_image_info(o) for o in _images(page)],
                    )
                )
            finally:
                page.close()
    return fields, pages


def text_chars_per_page(pdf: Path) -> list[int]:
    """Non-whitespace character count of the existing text layer, per page."""
    counts: list[int] = []
    with _open(pdf) as doc:
        for i in range(len(doc)):
            page = doc[i]
            try:
                textpage = page.get_textpage()
                try:
                    counts.append(len(re.sub(r"\s+", "", textpage.get_text_range())))
                finally:
                    textpage.close()
            finally:
                page.close()
    return counts


def render_image(pdf: Path, page: int, *, dpi: int, gray: bool) -> Image.Image:
    """Render one page (1-based) at dpi, honouring /Rotate. Returns an L or RGB image."""
    with _open(pdf) as doc:
        p = doc[page - 1]
        try:
            bitmap = p.render(scale=dpi / 72, grayscale=gray)  # pyright: ignore[reportArgumentType]
            img = bitmap.to_pil().copy()  # detach from PDFium's buffer before closing
            bitmap.close()
        finally:
            p.close()
    want = "L" if gray else "RGB"
    return img if img.mode == want else img.convert(want)


def render_page(
    pdf: Path,
    page: int,
    out_png: Path,
    *,
    dpi: int,
    gray: bool,
    crop: tuple[int, int, int, int] | None = None,
) -> Path:
    """Render one page to PNG. crop = (x, y, w, h) in output pixels."""
    img = render_image(pdf, page, dpi=dpi, gray=gray)
    if crop is not None:
        x, y, w, h = crop
        img = img.crop((x, y, min(x + w, img.width), min(y + h, img.height)))
    img.save(out_png, format="PNG", compress_level=6)
    return out_png


def extract_page_image(pdf: Path, page: int, out_png: Path, *, gray: bool = True) -> Path | None:
    """Save the single embedded image of a page at native resolution as PNG.

    None if the page does not have exactly one image (or PDFium cannot decode it).
    Like `pdfimages`, this ignores soft masks and the image's placement.
    """
    with _open(pdf) as doc:
        p = doc[page - 1]
        try:
            imgs = _images(p)
            if len(imgs) != 1:
                return None
            try:
                bitmap = imgs[0].get_bitmap(render=False)
            except pdfium.PdfiumError:
                return None
            img = bitmap.to_pil().copy()
            bitmap.close()
        finally:
            p.close()
    want = "L" if gray else "RGB"
    if img.mode != want:
        img = img.convert(want)
    img.save(out_png, format="PNG", compress_level=6)
    return out_png


def write_subset(src: Path, dst: Path, first: int, last: int) -> None:
    """Write pages first..last (1-based, inclusive) of src to a new PDF."""
    with _open(src) as doc:
        out = pdfium.PdfDocument.new()
        try:
            out.import_pages(doc, list(range(first - 1, last)))
            out.save(dst)
        finally:
            out.close()
