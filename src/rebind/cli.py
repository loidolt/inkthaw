"""rebind command-line interface."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from rebind import __version__, tools
from rebind.config import PROFILES, load_config
from rebind.errors import RebindError
from rebind.job import Job, slugify
from rebind.pipeline import STAGE_NAMES, run_pipeline

app = typer.Typer(
    name="rebind",
    help="Turn scanned PDFs into clean, reflowable EPUBs.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
err_console = Console(stderr=True)


def _fail(msg: str, code: int = 1) -> typer.Exit:
    err_console.print(f"[bold red]error:[/] {msg}")
    return typer.Exit(code)


def _version_cb(value: bool) -> None:
    if value:
        console.print(f"rebind {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_cb, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    pass


@app.command()
def run(
    pdf: Annotated[
        Path,
        typer.Argument(help="Scanned PDF to convert.", exists=True, dir_okay=False, readable=True),
    ],
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file (default: ./rebind.toml).")
    ] = None,
    profile: Annotated[str | None, typer.Option(help=f"Preset: {', '.join(PROFILES)}.")] = None,
    title: Annotated[str | None, typer.Option(help="Book title.")] = None,
    author: Annotated[list[str] | None, typer.Option(help="Author (repeatable).")] = None,
    language: Annotated[str | None, typer.Option(help="BCP-47 language, e.g. en, de.")] = None,
    cover: Annotated[Path | None, typer.Option(help="Cover image.")] = None,
    engine: Annotated[str | None, typer.Option(help="OCR/layout engine.")] = None,
    device: Annotated[str | None, typer.Option(help="auto | cpu | cuda | mps.")] = None,
    dpi: Annotated[int | None, typer.Option(help="Rasterization DPI.")] = None,
    from_stage: Annotated[
        str | None, typer.Option("--from", help=f"Re-run from: {', '.join(STAGE_NAMES)}.")
    ] = None,
    to_stage: Annotated[str | None, typer.Option("--to", help="Stop after this stage.")] = None,
    out: Annotated[Path, typer.Option(help="Where the finished EPUB is copied.")] = Path("out"),
    jobs_dir: Annotated[Path, typer.Option(help="Where job folders live.")] = Path("jobs"),
    slug: Annotated[
        str | None, typer.Option(help="Job folder name (default: from file name).")
    ] = None,
) -> None:
    """Convert a scanned PDF to EPUB (resumes an existing job when possible)."""
    overrides: dict[str, Any] = {
        "profile": profile,
        "engine": engine,
        "device": device,
        "dpi": dpi,
    }
    meta = {"title": title, "authors": author or None, "language": language, "cover": cover}
    meta = {k: v for k, v in meta.items() if v is not None}
    if meta:
        overrides["metadata"] = meta
    try:
        cfg = load_config(config, overrides)
        job = Job((jobs_dir / (slug or slugify(pdf.stem))).resolve())
        console.print(
            f"[bold]rebind[/] {__version__}: {pdf.name} -> {job.root} "
            f"[dim](profile {cfg.profile}, engine {cfg.engine}, {cfg.dpi} dpi)[/]"
        )
        ctx = run_pipeline(
            job,
            cfg,
            input_pdf=pdf.resolve(),
            from_stage=from_stage,
            to_stage=to_stage,
            console=console,
        )
    except RebindError as e:
        raise _fail(str(e)) from None
    except KeyboardInterrupt:
        raise _fail("interrupted; re-run the same command to resume", 130) from None

    if job.epub.is_file() and (to_stage is None or to_stage in ("build", "validate")):
        out.mkdir(parents=True, exist_ok=True)
        final = out / f"{job.slug}.epub"
        shutil.copyfile(job.epub, final)
        console.print(f"\n[bold green]EPUB:[/] {final}")
        if job.report_json.is_file():
            console.print(f"[bold]Report:[/] {job.report_json}")
    if ctx.warnings:
        console.print(f"[yellow]{len(ctx.warnings)} warning(s)[/] (see output above)")


@app.command()
def watch(
    inbox: Annotated[Path, typer.Argument(help="Folder to watch for PDFs.")],
    out: Annotated[Path, typer.Option(help="Where finished EPUBs go.")] = Path("outbox"),
    jobs_dir: Annotated[Path, typer.Option(help="Where job folders live.")] = Path("jobs"),
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file (default: ./rebind.toml).")
    ] = None,
    interval: Annotated[float, typer.Option(help="Seconds between polls.")] = 5.0,
    once: Annotated[
        bool, typer.Option("--once", help="Convert the PDFs already there, then exit.")
    ] = False,
) -> None:
    """Convert every PDF dropped into INBOX. A `<name>.toml` next to a PDF adds
    per-book settings (title, authors, profile)."""
    import signal

    from rebind.watch import Watcher

    def _stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)  # `docker stop` sends SIGTERM
    try:
        cfg = load_config(config)  # fail fast on a bad global config
        if cfg.models_dir is not None:
            from rebind.engines import get_engine

            get_engine(cfg.engine).prefetch(cfg, console.print)
        Watcher(inbox, out, jobs_dir, config, interval, console).run(once=once)
    except RebindError as e:
        raise _fail(str(e)) from None
    except KeyboardInterrupt:
        console.print("stopped; unfinished jobs resume on the next start")


@app.command()
def models(
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file (default: ./rebind.toml).")
    ] = None,
    models_dir: Annotated[
        Path | None,
        typer.Option(
            help="Where to store weights (default: config models_dir or $REBIND_MODELS_DIR)."
        ),
    ] = None,
) -> None:
    """Download the engine's model weights now, so conversions can run offline."""
    from rebind.engines import get_engine

    try:
        overrides: dict[str, Any] = {"models_dir": models_dir} if models_dir else {}
        cfg = load_config(config, overrides)
        if cfg.models_dir is None:
            raise RebindError("Set --models-dir, models_dir in rebind.toml, or REBIND_MODELS_DIR")
        engine = get_engine(cfg.engine)
        target = engine.prefetch(cfg, console.print)
    except RebindError as e:
        raise _fail(str(e)) from None
    console.print(f"[green]models ready[/] in {target}")


@app.command()
def report(
    job_dir: Annotated[Path, typer.Argument(help="Job folder, e.g. jobs/<slug>.")],
    open_html: Annotated[
        bool, typer.Option("--open/--no-open", help="Open report.html in a browser.")
    ] = False,
) -> None:
    """Show a job's stage status, rebuild report.html, optionally open it."""
    from rebind.report import write_html

    job = Job(job_dir.resolve())
    if not job.manifest_path.is_file():
        raise _fail(f"{job_dir} is not a rebind job folder (no manifest.json)")
    manifest = job.load_manifest()
    table = Table(title=f"{job.slug}", show_lines=False)
    for col in ("stage", "status", "time", "summary"):
        table.add_column(col)
    for name in STAGE_NAMES:
        rec = manifest.stages.get(name)
        if rec is None:
            table.add_row(name, "pending", "", "")
            continue
        summary = ", ".join(
            f"{k}={v}" for k, v in rec.info.items() if not isinstance(v, list | dict)
        )
        style = {"done": "green", "failed": "red", "running": "yellow"}.get(rec.status, "")
        dur = f"{rec.duration_s:.1f}s" if rec.duration_s is not None else ""
        table.add_row(
            name,
            f"[{style}]{rec.status}[/]" if style else rec.status,
            dur,
            rec.error.splitlines()[0][:80] if rec.error else summary[:100],
        )
    console.print(table)
    if not job.report_json.is_file():
        console.print("[yellow]no report yet: the validate stage has not run[/]")
        return
    data = json.loads(job.report_json.read_text(encoding="utf-8"))
    chk = data.get("epubcheck")
    if chk and chk.get("skipped"):
        console.print(f"[yellow]epubcheck skipped:[/] {escape(str(chk.get('reason')))}")
    elif chk:
        console.print(
            f"epubcheck {chk.get('checker_version')}: "
            f"{chk['errors']} errors, {chk['warnings']} warnings"
        )
    q = data.get("quality") or {}
    if q:
        console.print(
            f"quality score [bold]{q['score']}[/], {q['flagged_pages']}/{q['pages']} pages flagged"
        )
        for code, n in q.get("flag_counts", {}).items():
            console.print(f"  {code}: {n}")
    html_path = write_html(job)
    console.print(f"[bold]Report:[/] {html_path}")
    if open_html:
        import webbrowser

        webbrowser.open(html_path.as_uri())


@app.command("config")
def show_config(
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Config file (default: ./rebind.toml).")
    ] = None,
    profile: Annotated[str | None, typer.Option(help="Profile to apply.")] = None,
) -> None:
    """Print the effective configuration as TOML (defaults < profile < file)."""
    from rebind.config import to_toml

    try:
        cfg = load_config(config, {"profile": profile})
    except RebindError as e:
        raise _fail(str(e)) from None
    typer.echo(to_toml(cfg), nl=False)


@app.command()
def profiles() -> None:
    """List the built-in profiles and what each one changes."""
    from rebind.config import PROFILE_HELP

    for name, overrides in PROFILES.items():
        console.print(f"[bold]{name}[/]: {PROFILE_HELP.get(name, '')}")
        for section, values in overrides.items():
            for key, value in values.items():
                console.print(f"  [dim]{section}.{key} = {value!r}[/]")


@app.command()
def engines() -> None:
    """List installed engines and available devices."""
    from rebind.engines import list_engines
    from rebind.engines.devices import available_devices

    table = Table()
    for col in ("engine", "version", "status", "capabilities"):
        table.add_column(col)
    for name, ep in sorted(list_engines().items()):
        try:
            eng = ep.load()()
            ok, reason = eng.available()
            caps = eng.capabilities if ok else None
            capstr = ""
            if caps is not None:
                capstr = ", ".join(
                    k
                    for k in ("tables", "pictures", "footnotes", "page_furniture", "confidence")
                    if getattr(caps, k)
                )
            status = "[green]ok[/]" if ok else f"[red]{escape(reason)}[/]"
            table.add_row(name, eng.version, status, capstr)
        except Exception as e:
            table.add_row(name, "?", f"[red]load error: {escape(str(e))}[/]", "")
    console.print(table)
    console.print(f"devices: {', '.join(available_devices())}")


@app.command()
def doctor() -> None:
    """Check libraries, external tools and engines."""
    from rebind import pdf

    missing_required: list[str] = []

    libs = Table(title="built in (Python packages)")
    for col in ("library", "version", "used for"):
        libs.add_column(col)
    v = pdf.versions()
    import numpy
    import PIL

    libs.add_row("pypdfium2", v["pypdfium2"], "read and render PDFs")
    libs.add_row("PDFium", v["pdfium"], "")
    libs.add_row("Pillow", PIL.__version__, "page images")
    libs.add_row("numpy", numpy.__version__, "preprocess: borders, despeckle, deskew")
    console.print(libs)

    table = Table(title="external tools")
    for col in ("tool", "status", "version", "used for"):
        table.add_column(col)
    for t in tools.TOOLS.values():
        path = tools.which(t.name)
        hint = f"[dim]({escape(t.install_hint)})[/]"
        if path:
            status = "[green]ok[/]"
            ver = tools.version(t.name) or "?"
            if t.name == "pandoc" and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) < 3:
                status = "[red]too old (need >= 3.0)[/]"
                missing_required.append(t.name)
            elif t.name == "java" and not tools.java_works():
                status = f"[yellow]not working (optional)[/] {hint}"
                ver = ""
        else:
            ver = ""
            if t.required:
                status = f"[red]missing[/] {hint}"
                missing_required.append(t.name)
            else:
                status = f"[yellow]missing (optional)[/] {hint}"
        table.add_row(t.name, status, ver, t.purpose)
    console.print(table)
    _, epubcheck_missing = tools.epubcheck_status()
    if epubcheck_missing:
        console.print(f"[yellow]note:[/] {epubcheck_missing}; EPUBs will not be validated")

    from rebind.engines import list_engines

    eng_ok = False
    for name, ep in sorted(list_engines().items()):
        try:
            ok, reason = ep.load()().available()
        except Exception as e:
            ok, reason = False, str(e)
        eng_ok = eng_ok or ok
        mark = "[green]ok[/]" if ok else "[red]unavailable[/]"
        console.print(f"engine {name}: {mark} [dim]{escape(reason)}[/]")
    if not eng_ok:
        missing_required.append("engine")

    py = sys.version_info
    console.print(f"python {py.major}.{py.minor}.{py.micro}, rebind {__version__}")
    if missing_required:
        console.print(f"[bold red]missing:[/] {', '.join(missing_required)}")
        raise typer.Exit(1)
    console.print("[bold green]all required tools found[/]")


if __name__ == "__main__":
    app()
