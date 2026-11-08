"""report.html: each flagged page's image next to its extracted text."""

from __future__ import annotations

import html
import json
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from rebind.ir import FURNITURE_KINDS, BookIR
from rebind.job import Job
from rebind.quality import FLAG_HELP


def _esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _score_class(score: float) -> str:
    return "score-good" if score >= 90 else "score-warn" if score >= 75 else "score-bad"


def _page_text(raw: BookIR, page: int, marks: list[str]) -> str:
    paras = []
    for b in raw.blocks:
        if b.page != page or b.kind in FURNITURE_KINDS or not b.text:
            continue
        t = _esc(b.text)
        for m in marks:
            t = t.replace(_esc(m), f"<mark>{_esc(m)}</mark>")
        prefix = f"[{b.kind.value}] " if b.kind.value != "paragraph" else ""
        paras.append(f"<p>{_esc(prefix)}{t}</p>")
    return "".join(paras) or "<p><em>(no text)</em></p>"


def render_html(job: Job, report: dict[str, Any], raw: BookIR) -> str:
    quality = report.get("quality") or {}
    details = quality.get("page_details", [])
    check = report.get("epubcheck") or {}
    title = report.get("title") or job.slug
    score = quality.get("score", 0.0)

    stats = [
        (f'<b class="{_score_class(score)}">{score}</b>', "quality score (0-100)"),
        (f"<b>{quality.get('flagged_pages', 0)} / {quality.get('pages', 0)}</b>", "pages flagged"),
        (f"<b>{check.get('errors', '-')}</b>", "epubcheck errors"),
        (f"<b>{check.get('warnings', '-')}</b>", "epubcheck warnings"),
    ]
    stats_html = "".join(f'<div class="stat">{v}<span>{_esc(k)}</span></div>' for v, k in stats)

    counts: dict[str, int] = quality.get("flag_counts", {})
    filters = ['<button data-flag="all" aria-pressed="true">all flagged</button>']
    filters += [
        f'<button data-flag="{_esc(code)}" aria-pressed="false" '
        f'title="{_esc(FLAG_HELP.get(code, ""))}">{_esc(code)} ({n})</button>'
        for code, n in counts.items()
    ]

    cards = []
    for d in details:
        if not d["flags"]:
            continue
        codes = " ".join(f["code"] for f in d["flags"])
        flags = "".join(
            f'<li title="{_esc(FLAG_HELP.get(f["code"], ""))}"><code>{_esc(f["code"])}</code> '
            f"{_esc(f['detail'])}</li>"
            for f in d["flags"]
        )
        marks = [
            run
            for f in d["flags"]
            if f["code"] == "garbled_text"
            for run in f["detail"].split(" | ")
        ]
        src = f" (PDF page {d['source_page']})" if d.get("source_page") else ""
        img = "../" + d["image"]
        cards.append(
            f'<section class="page" data-flags="{_esc(codes)}" id="p{d["index"] + 1}">'
            f'<a href="{_esc(img)}"><img loading="lazy" src="{_esc(img)}" '
            f'alt="Scan of page {d["index"] + 1}"></a>'
            f"<div><h2>Page {d['index'] + 1}{_esc(src)} · score {d['score']:.2f}</h2>"
            f'<ul class="flags">{flags}</ul>'
            f'<div class="text">{_page_text(raw, d["index"], marks)}</div></div></section>'
        )
    if not cards:
        cards.append("<p>No pages flagged.</p>")

    def fmt(v: float | None, digits: int) -> str:
        return "" if v is None else f"{v:.{digits}f}"

    rows = "".join(
        f'<tr><td><a href="#p{d["index"] + 1}">{d["index"] + 1}</a></td><td>{d["chars"]}</td>'
        f"<td>{fmt(d['confidence'], 2)}</td><td>{fmt(d['dictionary_ratio'], 3)}</td>"
        f"<td>{_esc(', '.join(f['code'] for f in d['flags']))}</td></tr>"
        for d in details
    )
    table = (
        "<table><thead><tr><th>page</th><th>chars</th><th>confidence</th>"
        f"<th>dictionary</th><th>flags</th></tr></thead><tbody>{rows}</tbody></table>"
    )
    subtitle = f"{job.slug} · median {quality.get('median_chars', 0):.0f} characters per page" + (
        "" if quality.get("dictionary_checks", True) else " · dictionary checks off (language)"
    )
    tpl = Template(files("rebind.assets").joinpath("report.html").read_text(encoding="utf-8"))
    return tpl.substitute(
        title=_esc(title),
        subtitle=_esc(subtitle),
        stats=stats_html,
        filters="".join(filters),
        pages="\n".join(cards),
        table=table,
    )


def write_html(job: Job) -> Path:
    report = json.loads(job.report_json.read_text(encoding="utf-8"))
    raw = BookIR.load(job.raw_ir)
    out = job.dir("validate") / "report.html"
    out.write_text(render_html(job, report, raw), encoding="utf-8")
    return out
