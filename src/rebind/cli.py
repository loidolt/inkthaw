"""rebind command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from rebind import __version__, tools

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
    pdf: Annotated[Path, typer.Argument(help="Scanned PDF to convert.")],
) -> None:
    """Convert a scanned PDF to EPUB. (Milestone M1.)"""
    raise _fail("run is not implemented yet (milestone M1)", 2)


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
            table.add_row(name, eng.version, "[green]ok[/]" if ok else f"[red]{reason}[/]", capstr)
        except Exception as e:
            table.add_row(name, "?", f"[red]load error: {e}[/]", "")
    console.print(table)
    console.print(f"devices: {', '.join(available_devices())}")


@app.command()
def doctor() -> None:
    """Check external tools and engines."""
    table = Table(title="external tools")
    for col in ("tool", "status", "version", "used for"):
        table.add_column(col)
    missing_required = []
    for t in tools.TOOLS.values():
        path = tools.which(t.name)
        if path:
            status = "[green]ok[/]"
            ver = tools.version(t.name) or "?"
            if t.name == "pandoc" and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) < 3:
                status = "[red]too old (need >= 3.0)[/]"
                missing_required.append(t.name)
        else:
            ver = ""
            if t.required:
                status = f"[red]missing[/] [dim]({t.install_hint})[/]"
                missing_required.append(t.name)
            else:
                status = f"[yellow]missing (optional)[/] [dim]({t.install_hint})[/]"
        table.add_row(t.name, status, ver, t.purpose)
    console.print(table)

    from rebind.engines import list_engines

    eng_ok = False
    for name, ep in sorted(list_engines().items()):
        try:
            ok, reason = ep.load()().available()
        except Exception as e:
            ok, reason = False, str(e)
        eng_ok = eng_ok or ok
        mark = "[green]ok[/]" if ok else "[red]unavailable[/]"
        console.print(f"engine {name}: {mark} [dim]{reason}[/]")
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
