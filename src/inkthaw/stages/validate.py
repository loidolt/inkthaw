"""validate: epubcheck, per-page quality flags, report.json and report.html."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from inkthaw import quality, tools
from inkthaw.errors import InkthawError, StageError, ToolMissingError
from inkthaw.ir import BookIR
from inkthaw.pipeline import StageContext
from inkthaw.report import write_html

SEVERITIES = ("FATAL", "ERROR", "WARNING", "USAGE", "INFO")


def parse_epubcheck(data: dict[str, Any]) -> dict[str, Any]:
    """Summarise epubcheck's JSON report."""
    messages = []
    counts = {s: 0 for s in SEVERITIES}
    for msg in data.get("messages", []):
        sev = str(msg.get("severity", "INFO")).upper()
        n_loc = max(1, len(msg.get("locations") or []))
        counts[sev] = counts.get(sev, 0) + n_loc
        loc = (msg.get("locations") or [{}])[0]
        messages.append(
            {
                "id": msg.get("ID"),
                "severity": sev,
                "message": msg.get("message"),
                "path": loc.get("path"),
                "line": loc.get("line"),
                "occurrences": n_loc,
            }
        )
    checker = data.get("checker", {})
    return {
        "checker_version": checker.get("checkerVersion"),
        "errors": counts.get("FATAL", 0) + counts.get("ERROR", 0),
        "warnings": counts.get("WARNING", 0),
        "counts": counts,
        "messages": messages,
    }


def skipped(reason: str) -> dict[str, Any]:
    """Report entry when EPUBCheck did not run."""
    return {
        "skipped": True,
        "reason": reason,
        "checker_version": None,
        "errors": None,
        "warnings": None,
        "counts": {},
        "messages": [],
    }


def run_epubcheck(cmd: list[str], epub: Path, out_json: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [*cmd, str(epub), "--json", str(out_json)],
        capture_output=True,
        text=True,
        check=False,
        errors="replace",
    )
    if not out_json.is_file():
        tail = (proc.stderr or proc.stdout).strip()[-1500:]
        raise InkthawError(f"epubcheck produced no report (exit {proc.returncode}): {tail}")
    return parse_epubcheck(json.loads(out_json.read_text(encoding="utf-8")))


class ValidateStage:
    name = "validate"
    version = "3"  # 3: EPUBCheck optional (skipped with a note when missing)
    config_keys: tuple[str, ...] = ("validate", "quality", "metadata")
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        if not ctx.cfg.validate_.epubcheck:
            return "off"
        cmd, _ = tools.epubcheck_status()
        if cmd is None:
            return "missing"
        return tools.version("epubcheck") or ""

    def run(self, ctx: StageContext) -> dict[str, Any]:
        job, cfg = ctx.job, ctx.cfg
        out = job.dir(self.name)
        epub = job.epub
        if not epub.is_file():
            raise InkthawError(f"{epub} missing; re-run the build stage")

        check: dict[str, Any]
        cmd, missing = tools.epubcheck_status()
        if not cfg.validate_.epubcheck:
            check = skipped("turned off (validate.epubcheck = false)")
        elif cmd is None:
            if cfg.validate_.require_epubcheck:
                raise ToolMissingError(
                    f"{missing}; install it ({tools.TOOLS['epubcheck'].install_hint}) "
                    "or set validate.require_epubcheck = false"
                )
            check = skipped(f"{missing}; the EPUB was not validated")
            ctx.warn(f"epubcheck skipped: {missing}")
        else:
            check = run_epubcheck(cmd, epub, out / "epubcheck.json")
            ctx.info(f"epubcheck: {check['errors']} errors, {check['warnings']} warnings")
            for m in check["messages"]:
                if m["severity"] in ("FATAL", "ERROR"):
                    ctx.console.print(
                        f"  [red]{m['severity']}[/] {m['id']}: {m['message']} "
                        f"[dim]({m['path']}:{m['line']})[/]"
                    )

        raw, clean = BookIR.load(job.raw_ir), BookIR.load(job.clean_ir)
        q = quality.assess(raw, clean, cfg, job.root)
        ctx.info(
            f"quality score {q['score']}, {q['flagged_pages']}/{q['pages']} pages flagged"
            + (
                f": {', '.join(f'{k} {n}' for k, n in q['flag_counts'].items())}"
                if q["flag_counts"]
                else ""
            )
        )

        stages = {name: rec.info for name, rec in ctx.manifest.stages.items() if name != self.name}
        report = {
            "slug": job.slug,
            "title": stages.get("build", {}).get("title"),
            "epub": job.rel(epub),
            "epub_bytes": epub.stat().st_size,
            "epubcheck": check,
            "stages": stages,
            "quality": q,
        }
        job.report_json.write_text(json.dumps(report, indent=1), encoding="utf-8")
        html_path = write_html(job)
        ctx.info(f"report: {job.rel(html_path)}")

        if check["errors"] and cfg.validate_.fail_on_error:
            raise StageError(
                f"epubcheck found {check['errors']} error(s); see {job.rel(out / 'epubcheck.json')}"
            )
        return {
            "epubcheck_errors": check["errors"],
            "epubcheck_warnings": check["warnings"],
            "epubcheck_skipped": bool(check.get("skipped")),
            "quality_score": q["score"],
            "flagged_pages": q["flagged_pages"],
        }


STAGE = ValidateStage()
