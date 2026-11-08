"""Fail if an installed Python package has a copyleft, proprietary or unknown license.

Enforces PLAN.md §2 for everything `uv sync` installs (run it after installing
the extras you ship). Packages verified by hand are listed in REVIEWED.

A package's own license is not the whole story for binary wheels: some bundle
native libraries under other terms. Those are listed in BUNDLES_COPYLEFT and
reported as warnings; `--app` (for desktop/mobile app bundles, where nothing
GPL may ship) turns them into failures.

    uv run python scripts/check_licenses.py [--all] [--app]
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distributions

ALLOWED = re.compile(
    r"\b(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|MPL-2\.0|Mozilla Public License 2\.0|"
    r"Unlicense|CC0|Zlib|HPND|CNRI-Python|0BSD|Public Domain)\b",
    re.IGNORECASE,
)
BLOCKED = re.compile(
    r"\b(A?GPL|LGPL|GNU|Proprietary|SSPL|Commons Clause|NonCommercial|BY-NC)\b", re.IGNORECASE
)

# Packages whose metadata is wrong or missing, checked by reading the LICENSE file.
REVIEWED: dict[str, str] = {
    "locate": "MIT (LICENSE file); PyPI classifier wrongly says Other/Proprietary",
    "inkthaw": "Apache-2.0 (this project)",
}

# Permissively licensed wheels that bundle copyleft native libraries. Fine to
# install alongside inkthaw (CLI, Docker), but not inside app bundles (PLAN.md §2).
BUNDLES_COPYLEFT: dict[str, str] = {
    "opencv-python-headless": (
        "Apache-2.0, but bundles FFmpeg (LGPL-2.1+; the macOS arm64 5.0.0.93 wheel's "
        "libavcodec reports GPL-3.0+, built with x264/x265). Pulled in by rapidocr "
        "(docling extra); not used by inkthaw's own code."
    ),
    "opencv-python": "Apache-2.0, but bundles FFmpeg and Qt (LGPL).",
}

# NVIDIA CUDA runtime wheels pulled in by CUDA torch builds (CUDA image only):
# proprietary but redistributable under the NVIDIA license; documented in
# THIRD_PARTY_LICENSES.md.
NVIDIA = re.compile(r"^nvidia-")


def license_of(dist) -> str:
    m = dist.metadata
    expr = (m.get("License-Expression") or "").strip()
    if expr:
        return expr
    classifiers = [
        c.split("::")[-1].strip()
        for c in (m.get_all("Classifier") or [])
        if c.startswith("License")
    ]
    if classifiers:
        return "; ".join(classifiers)
    text = (m.get("License") or "").strip()
    return text.splitlines()[0][:80] if text else ""


def main() -> int:
    show_all = "--all" in sys.argv
    app = "--app" in sys.argv
    problems = []
    bundled = []
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"].lower().replace("_", "-")
        lic = license_of(dist)
        if name in BUNDLES_COPYLEFT:
            bundled.append((name, dist.version, BUNDLES_COPYLEFT[name]))
        if name in REVIEWED:
            verdict = f"ok (reviewed: {REVIEWED[name]})"
        elif NVIDIA.match(name):
            verdict = "ok (NVIDIA redistributable, CUDA image only)"
        elif BLOCKED.search(lic) or not ALLOWED.search(lic):
            verdict = "PROBLEM"
            problems.append((name, dist.version, lic or "unknown"))
        else:
            verdict = "ok"
        if show_all or verdict == "PROBLEM":
            print(f"{verdict:8s} {name} {dist.version}: {lic or 'unknown'}")
    for name, version, note in bundled:
        level = "PROBLEM" if app else "warning"
        print(f"{level:8s} {name} {version}: {note}")
    if app and bundled:
        problems += bundled
    if problems:
        print(f"\n{len(problems)} package(s) need review (PLAN.md §2).", file=sys.stderr)
        return 1
    print("all licenses permissive or reviewed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
