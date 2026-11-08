"""Tiny stdlib-only image helpers (PNG size, PNM -> PNG).

unpaper reads PNG but always writes PNM; engines want PNG. Converting here keeps
the core free of an imaging dependency.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        head = f.read(24)
    if head[:8] != PNG_SIG or head[12:16] != b"IHDR":
        raise ValueError(f"{path}: not a PNG file")
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, channels: int, pixels: bytes) -> None:
    """Write 8-bit gray (channels=1) or RGB (channels=3) pixels as PNG."""
    color_type = {1: 0, 3: 2}[channels]
    stride = width * channels
    if len(pixels) != stride * height:
        raise ValueError("pixel buffer size mismatch")
    raw = bytearray()
    for y in range(height):
        raw += b"\x00"
        raw += pixels[y * stride : (y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    data = PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    path.write_bytes(data + _chunk(b"IEND", b""))


def _read_pnm_header(data: bytes) -> tuple[bytes, list[int], int]:
    """Return (magic, numeric fields, offset of pixel data)."""
    magic = data[:2]
    need = 2 if magic == b"P4" else 3
    vals: list[int] = []
    i = 2
    while len(vals) < need:
        c = data[i : i + 1]
        if c == b"#":
            i = data.index(b"\n", i) + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while not data[j : j + 1].isspace():
                j += 1
            vals.append(int(data[i:j]))
            i = j
    return magic, vals, i + 1  # exactly one whitespace byte after the last field


def pnm_to_png(src: Path, dst: Path) -> tuple[int, int]:
    """Convert binary PBM/PGM/PPM (P4/P5/P6) to PNG. Returns (width, height)."""
    data = src.read_bytes()
    magic, vals, off = _read_pnm_header(data)
    if magic == b"P4":
        w, h = vals
        row_bytes = (w + 7) // 8
        out = bytearray(w * h)
        for y in range(h):
            row = data[off + y * row_bytes : off + (y + 1) * row_bytes]
            bits = int.from_bytes(row, "big")
            total = row_bytes * 8
            base = y * w
            for x in range(w):
                # PBM: 1 = black
                out[base + x] = 0 if (bits >> (total - 1 - x)) & 1 else 255
        write_png(dst, w, h, 1, bytes(out))
        return w, h
    if magic not in (b"P5", b"P6"):
        raise ValueError(f"{src}: unsupported PNM type {magic!r}")
    w, h, maxval = vals
    channels = 1 if magic == b"P5" else 3
    n = w * h * channels
    if maxval < 256:
        pixels = data[off : off + n]
        if maxval != 255:
            pixels = bytes(min(255, p * 255 // maxval) for p in pixels)
    else:
        words = struct.unpack(f">{n}H", data[off : off + 2 * n])
        pixels = bytes(v * 255 // maxval for v in words)
    write_png(dst, w, h, channels, pixels)
    return w, h
