"""External command-line tools: discovery, version probing and invocation."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from inkthaw.errors import InkthawError, ToolMissingError


@dataclass(frozen=True)
class Tool:
    name: str
    package: str
    version_args: tuple[str, ...]
    required: bool
    purpose: str
    install_hint: str


# No external tool is required. PDF reading/rendering (PDFium) and page clean-up
# (numpy + Pillow) run in-process since M5, and the EPUB is written in-process
# by inkthaw.epub; everything here is an optional extra.
TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "pandoc",
            "pandoc",
            ("--version",),
            False,
            "optional build backend (build.backend = 'pandoc')",
            "brew install pandoc | apt install pandoc (>= 3.0)",
        ),
        Tool(
            "epubcheck",
            "epubcheck",
            ("--version",),
            False,
            "validate EPUB (skipped if missing)",
            "brew install epubcheck | apt install epubcheck (needs Java)",
        ),
        Tool(
            "java",
            "java",
            ("-version",),
            False,
            "runtime for epubcheck",
            "brew install openjdk | apt install default-jre-headless",
        ),
        Tool(
            "unpaper",
            "unpaper",
            ("--version",),
            False,
            "optional preprocess backend",
            "brew install unpaper | apt install unpaper",
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


def command(name: str) -> list[str] | None:
    """argv prefix to run a tool. Debian installs epubcheck as a bare symlink to a
    .jar (it relies on binfmt_misc), so .jar targets are run with `java -jar`."""
    path = which(name)
    if path is None:
        return None
    real = Path(path).resolve()
    if real.suffix == ".jar":
        java = which("java")
        return [java, "-jar", str(real)] if java else None
    return [path]


@cache
def version(name: str) -> str | None:
    """Return the tool's version string, or None if missing/unknown."""
    cmd = command(name)
    if cmd is None:
        return None
    tool = TOOLS.get(name)
    args = tool.version_args if tool else ("--version",)
    try:
        proc = subprocess.run(
            [*cmd, *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    m = _VERSION_RE.search(out)
    return m.group(1) if m else "unknown"


@cache
def java_works() -> bool:
    """True if `java -version` runs. macOS ships a /usr/bin/java stub that only
    prints "Unable to locate a Java Runtime", so finding it on PATH is not enough."""
    java = which("java")
    if java is None:
        return False
    try:
        proc = subprocess.run(
            [java, "-version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def epubcheck_status() -> tuple[list[str] | None, str]:
    """(argv prefix, "") when EPUBCheck can run, else (None, reason)."""
    cmd = command("epubcheck")
    if cmd is None:
        return None, "EPUBCheck not found on PATH"
    if not java_works():
        return None, "EPUBCheck found but no working Java runtime"
    return cmd, ""


def require(name: str) -> list[str]:
    """argv prefix for a required tool; raises ToolMissingError if absent."""
    cmd = command(name)
    if cmd is None:
        tool = TOOLS.get(name)
        hint = f" Install: {tool.install_hint}." if tool else ""
        raise ToolMissingError(f"Required tool '{name}' not found on PATH.{hint}")
    return cmd


def run(
    args: list[str | Path],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a tool; raise InkthawError with its stderr on non-zero exit."""
    cmd = [*require(str(args[0])), *(str(a) for a in args[1:])]
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
        raise InkthawError(f"{args[0]} timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-15:])
        raise InkthawError(f"{args[0]} failed (exit {proc.returncode}): {tail}")
    return proc
