"""Ground-truth benchmark over tests/corpus/manifest.toml.

    uv run python scripts/corpus.py fetch jekyll-hyde     # download + verify scan and text
    uv run python scripts/corpus.py run jekyll-hyde       # convert with rebind
    uv run python scripts/corpus.py score jekyll-hyde     # CER/WER/paragraph F1 -> results/
    uv run python scripts/corpus.py all                   # every book, all three steps

`score --job DIR` scores an existing job folder instead of the default one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"
DOWNLOADS = CORPUS / "downloads"
JOBS = CORPUS / "jobs"
RESULTS = CORPUS / "results"
USER_AGENT = "rebind-corpus-benchmark"


def load_manifest() -> dict[str, dict[str, Any]]:
    with (CORPUS / "manifest.toml").open("rb") as f:
        return {b["id"]: b for b in tomllib.load(f)["book"]}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected: str | None, strict: bool) -> None:
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    got = sha256(dest)
    if expected and got != expected:
        msg = f"{dest.name}: sha256 {got} != manifest {expected}"
        if strict:
            sys.exit(f"error: {msg}")
        print(f"warning: {msg} (source may have been revised)")


def paths(book: dict[str, Any]) -> dict[str, Path]:
    d = DOWNLOADS / book["id"]
    return {"full": d / "scan-full.pdf", "scan": d / "scan.pdf", "gt": d / "ground_truth.txt"}


def fetch(book: dict[str, Any]) -> None:
    p = paths(book)
    download(book["scan"]["url"], p["full"], book["scan"].get("sha256"), strict=True)
    download(book["ground_truth"]["url"], p["gt"], book["ground_truth"].get("sha256"), strict=False)
    first, last = book["scan"].get("pages", [None, None])
    if first is None:
        p["scan"].write_bytes(p["full"].read_bytes())
    elif not p["scan"].is_file():
        from rebind.pdf import write_subset

        write_subset(p["full"], p["scan"], first, last)
    print(f"{book['id']}: ready ({p['scan']})")


def run(book: dict[str, Any]) -> None:
    p = paths(book)
    args = [
        sys.executable,
        "-m",
        "rebind.cli",
        "run",
        str(p["scan"]),
        "--jobs-dir",
        str(JOBS),
        "--out",
        str(JOBS / "out"),
        "--slug",
        book["id"],
        "--profile",
        book.get("profile", "novel"),
        "--title",
        book["title"],
        "--language",
        book.get("language", "en"),
    ]
    for a in book.get("authors", []):
        args += ["--author", a]
    subprocess.run(args, check=True)


# -- scoring ----------------------------------------------------------------


def gutenberg_paragraphs(text: str) -> list[str]:
    start = re.search(r"^\*\*\* ?START OF.*$", text, re.M)
    end = re.search(r"^\*\*\* ?END OF.*$", text, re.M)
    body = text[start.end() if start else 0 : end.start() if end else len(text)]
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body)]
    return [p for p in paras if p]


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.casefold()).strip()


def cut(paras: list[str], start: str | None, end: str | None, occurrence: int = 1) -> list[str]:
    i0 = 0
    if start:
        hits = [i for i, p in enumerate(paras) if _norm(p).startswith(_norm(start))]
        if len(hits) < occurrence:
            sys.exit(f"error: start marker {start!r} (#{occurrence}) not found")
        i0 = hits[occurrence - 1]
    i1 = len(paras)
    if end:
        for i in range(i0 + 1, len(paras)):
            if _norm(paras[i]).startswith(_norm(end)):
                i1 = i
                break
    return paras[i0:i1]


def output_paragraphs(job: Path) -> list[str]:
    from rebind.ir import BlockKind, BookIR

    keep = {
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.OTHER,
        BlockKind.CAPTION,
        BlockKind.FOOTNOTE,
    }
    ir = BookIR.load(job / "40_ir" / "clean.json")
    return [b.text for b in ir.blocks if b.kind in keep and b.text.strip()]


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def score_book(book: dict[str, Any], job: Path, label: str | None) -> dict[str, Any]:
    from rebind import __version__
    from rebind.metrics import score

    gt_cfg, out_cfg = book["ground_truth"], book.get("output", {})
    ref = cut(
        gutenberg_paragraphs(paths(book)["gt"].read_text(encoding="utf-8")),
        gt_cfg.get("start"),
        gt_cfg.get("end"),
        gt_cfg.get("start_occurrence", 1),
    )
    hyp = cut(output_paragraphs(job), out_cfg.get("start"), out_cfg.get("end"))
    s = score(hyp, ref, out_cfg.get("running_headers", []))

    manifest = json.loads((job / "manifest.json").read_text())
    report = json.loads((job / "60_report" / "report.json").read_text())
    cfg = manifest.get("config", {})
    result = {
        "id": book["id"],
        "label": label,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "rebind_version": __version__,
        "git_commit": git_commit(),
        "engine": cfg.get("engine"),
        "engine_version": manifest["stages"].get("ocr", {}).get("info", {}).get("engine_version"),
        "settings": {
            "dpi": cfg.get("dpi"),
            "preprocess": cfg.get("preprocess"),
            "ocr": cfg.get("ocr"),
        },
        "scores": s.as_dict(),
        "quality_score": (report.get("quality") or {}).get("score"),
        "flagged_pages": (report.get("quality") or {}).get("flagged_pages"),
        "paragraphs": {"output": len(hyp), "ground_truth": len(ref)},
    }
    return result


def write_step_summary(res: dict[str, Any]) -> None:
    """Append a Markdown row to the GitHub Actions job summary, when running in CI."""
    import os

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    s = res["scores"]
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            "| book | CER | WER | paragraph F1 | header leaks | quality score |\n"
            "|---|---|---|---|---|---|\n"
            f"| {res['id']} | {s['cer']:.2%} | {s['wer']:.2%} | {s['paragraph_f1']:.3f} "
            f"| {s['header_leaks']} | {res['quality_score']} |\n"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", choices=["fetch", "run", "score", "all"])
    ap.add_argument("book", nargs="?", help="book id (default: all)")
    ap.add_argument("--job", type=Path, help="score this job folder")
    ap.add_argument("--label", help="free-text label stored with the result (e.g. a setting)")
    ap.add_argument("--no-save", action="store_true", help="print scores, don't write results/")
    args = ap.parse_args()

    books = load_manifest()
    ids = [args.book] if args.book else list(books)
    for bid in ids:
        if bid not in books:
            sys.exit(f"error: unknown book {bid!r} (known: {', '.join(books)})")
        book = books[bid]
        if args.command in ("fetch", "all"):
            fetch(book)
        if args.command in ("run", "all"):
            run(book)
        if args.command in ("score", "all"):
            res = score_book(book, args.job or JOBS / bid, args.label)
            print(json.dumps(res["scores"], indent=1))
            write_step_summary(res)
            if not args.no_save:
                RESULTS.mkdir(parents=True, exist_ok=True)
                out = RESULTS / f"{bid}.json"
                history = json.loads(out.read_text()) if out.is_file() else []
                history.append(res)
                out.write_text(json.dumps(history, indent=1) + "\n")
                print(f"saved to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
