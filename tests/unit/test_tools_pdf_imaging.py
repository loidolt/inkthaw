import struct
import zlib
from pathlib import Path

import pytest

from rebind import tools
from rebind.errors import RebindError, ToolMissingError
from rebind.imaging import png_size, pnm_to_png, write_png


def test_require_missing_tool() -> None:
    with pytest.raises(ToolMissingError, match="not found"):
        tools.require("definitely-not-a-real-tool-xyz")


@pytest.mark.skipif(tools.which("false") is None, reason="no `false` binary")
def test_run_failure_raises() -> None:
    with pytest.raises(RebindError, match="exit 1"):
        tools.run(["false"])


def test_png_write_and_size(tmp_path: Path) -> None:
    p = tmp_path / "a.png"
    write_png(p, 3, 2, 1, bytes(range(6)))
    assert png_size(p) == (3, 2)


def _decode_png_gray(path: Path) -> bytes:
    data = path.read_bytes()
    _w, h = struct.unpack(">II", data[16:24])
    idat = b""
    i = 8
    while i < len(data):
        (length,) = struct.unpack(">I", data[i : i + 4])
        tag = data[i + 4 : i + 8]
        if tag == b"IDAT":
            idat += data[i + 8 : i + 8 + length]
        i += 12 + length
    raw = zlib.decompress(idat)
    stride = len(raw) // h
    return b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(h))


def test_pgm_to_png(tmp_path: Path) -> None:
    src = tmp_path / "a.pgm"
    src.write_bytes(b"P5\n# comment\n3 2\n255\n" + bytes([0, 128, 255, 10, 20, 30]))
    dst = tmp_path / "a.png"
    assert pnm_to_png(src, dst) == (3, 2)
    assert _decode_png_gray(dst) == bytes([0, 128, 255, 10, 20, 30])


def test_ppm_to_png(tmp_path: Path) -> None:
    src = tmp_path / "a.ppm"
    src.write_bytes(b"P6 2 1 255\n" + bytes([1, 2, 3, 4, 5, 6]))
    dst = tmp_path / "a.png"
    assert pnm_to_png(src, dst) == (2, 1)
    assert dst.read_bytes()[25] == 2  # color type RGB


def test_pbm_to_png(tmp_path: Path) -> None:
    src = tmp_path / "a.pbm"
    # 10 px wide -> 2 bytes per row; first row: black, white, black...
    src.write_bytes(b"P4\n10 1\n" + bytes([0b10101010, 0b11000000]))
    dst = tmp_path / "a.png"
    pnm_to_png(src, dst)
    assert _decode_png_gray(dst) == bytes([0, 255, 0, 255, 0, 255, 0, 255, 0, 0])


def test_jar_tools_run_with_java(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jar = tmp_path / "share" / "epubcheck.jar"
    jar.parent.mkdir()
    jar.write_bytes(b"PK")
    jar.chmod(0o755)  # Debian ships it executable
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "fakecheck").symlink_to(jar)
    java = bindir / "java"
    java.write_text("#!/bin/sh\n")
    java.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert tools.command("fakecheck") == [str(java), "-jar", str(jar.resolve())]
    assert tools.command("nope") is None
