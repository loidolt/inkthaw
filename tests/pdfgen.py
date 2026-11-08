"""Minimal stdlib-only PDF writer for test fixtures (image-only "scanned" pages)."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Image:
    width: int
    height: int
    data: bytes
    filter: str = "FlateDecode"  # or "DCTDecode" for JPEG bytes
    colorspace: str = "DeviceGray"


@dataclass
class PageSpec:
    width_pt: float
    height_pt: float
    image: Image | None = None


def gray_image(width: int, height: int, painter=None) -> Image:
    """Build a Flate-compressed 8-bit gray image. painter(x, y) -> 0..255 (default white)."""
    rows = bytearray()
    for y in range(height):
        if painter is None:
            rows += b"\xff" * width
        else:
            rows += bytes(painter(x, y) for x in range(width))
    return Image(width, height, zlib.compress(bytes(rows)))


def jpeg_size(data: bytes) -> tuple[int, int, int]:
    """Return (width, height, components) from JPEG SOF marker."""
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h, data[i + 9]
        i += 2 + length
    raise ValueError("no SOF marker")


def jpeg_image(data: bytes) -> Image:
    w, h, comps = jpeg_size(data)
    return Image(w, h, data, "DCTDecode", "DeviceGray" if comps == 1 else "DeviceRGB")


def write_pdf(path: Path, pages: list[PageSpec], info: dict[str, str] | None = None) -> None:
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog = add(b"")  # placeholder, filled below
    pages_obj = add(b"")
    kids = []
    for spec in pages:
        resources = b"<< >>"
        content = b""
        if spec.image is not None:
            im = spec.image
            img_obj = add(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace /%s /BitsPerComponent 8 /Filter /%s /Length %d >>\nstream\n"
                % (im.width, im.height, im.colorspace.encode(), im.filter.encode(), len(im.data))
                + im.data
                + b"\nendstream"
            )
            resources = b"<< /XObject << /Im0 %d 0 R >> >>" % img_obj
            content = b"q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % (spec.width_pt, spec.height_pt)
        content_obj = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                b"/Resources %s /Contents %d 0 R >>"
                % (pages_obj, spec.width_pt, spec.height_pt, resources, content_obj)
            )
        )
    objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
    objs[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    info_obj = None
    if info:
        entries = b" ".join(
            b"/%s (%s)" % (k.encode(), v.replace("(", r"\(").replace(")", r"\)").encode("latin-1"))
            for k, v in info.items()
        )
        info_obj = add(b"<< " + entries + b" >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    trailer = b"<< /Size %d /Root %d 0 R" % (len(objs) + 1, catalog)
    if info_obj:
        trailer += b" /Info %d 0 R" % info_obj
    out += b"trailer\n" + trailer + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref
    Path(path).write_bytes(bytes(out))
