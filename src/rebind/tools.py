"""External command-line tools: discovery, version probing and invocation."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from rebind.errors import RebindError, ToolMissingError


@dataclass(frozen=True)
class Tool:
    name: str
    package: str
    version_args: tuple[str, ...]
    required: bool
    purpose: str
    install_hint: str


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "pdfinfo",
            "poppler",
            ("-v",),
            True,
            "ingest: page count, sizes",
            "brew install poppler | apt install poppler-utils",
        ),
        Tool(
            "pdfimages",
            "poppler",
            ("-v",),
            True,
            "ingest: embedded image DPI",
            "brew install poppler | apt install poppler-utils",
        ),
        Tool(
            "pdftotext",
            "poppler",
            ("-v",),
            True,
            "ingest: text-layer detection",
            "brew install poppler | apt install poppler-utils",
        ),
        Tool(
            "pdftoppm",
            "poppler",
            ("-v",),
            True,
            "rasterize pages",
            "brew install poppler | apt install poppler-utils",
        ),
        Tool(
            "unpaper",
            "unpaper",
            ("--version",),
            True,
            "preprocess: deskew, borders",
            "brew install unpaper | apt install unpaper",
        ),
        Tool(
            "pandoc",
            "pandoc",
            ("--version",),
            True,
            "build EPUB",
            "brew install pandoc | apt install pandoc (>= 3.0)",
        ),
        Tool(
            "epubcheck",
            "epubcheck",
            ("--version",),
            True,
            "validate EPUB",
            "brew install epubcheck | apt install epubcheck (needs Java)",
        ),
        Tool(
            "java",
            "java",
            ("-version",),
            True,
            "runtime for epubcheck",
            "brew install openjdk | apt install default-jre-headless",
        ),
        Tool(
            "ebook-convert",
            "calibre",
            ("--version",),
            False,
            "optional AZW3 output",
            "install Calibre",
        ),
    ]
}

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")


def which(name: str) -> str | None:
    return shutil.which(name)


@cache
def version(name: str) -> str | None:
    """Return the tool's version string, or None if missing/unknown."""
    path = which(name)
    if path is None:
        return None
    tool = TOOLS.get(name)
    args = tool.version_args if tool else ("--version",)
    try:
        proc = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    m = _VERSION_RE.search(out)
    return m.group(1) if m else "unknown"


def require(name: str) -> str:
    path = which(name)
    if path is None:
        tool = TOOLS.get(name)
        hint = f" Install: {tool.install_hint}." if tool else ""
        raise ToolMissingError(f"Required tool '{name}' not found on PATH.{hint}")
    return path


def run(
    args: list[str | Path],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a tool; raise RebindError with its stderr on non-zero exit."""
    exe = require(str(args[0]))
    cmd = [exe, *(str(a) for a in args[1:])]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise RebindError(f"{args[0]} timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-15:])
        raise RebindError(f"{args[0]} failed (exit {proc.returncode}): {tail}")
    return proc
