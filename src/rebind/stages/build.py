"""build: BookIR -> EPUB 3.

The default 'native' backend writes the EPUB directly (rebind.epub); the
optional 'pandoc' backend renders Pandoc Markdown and calls pandoc."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Any

from rebind import epub, markdown, tools
from rebind.config import Config
from rebind.errors import RebindError
from rebind.ir import BlockKind, BookIR
from rebind.pipeline import StageContext

MIN_PANDOC = (3, 0)

# PDF producer strings that are not real titles.
_JUNK_TITLE = re.compile(
    r"^(untitled|microsoft|scan|document\d*|img|\d+)$|\.(pdf|tiff?|jpe?g)$", re.I
)


def _pdf_metadata(ctx: StageContext) -> dict[str, str]:
    info_path = ctx.job.source_info
    if not info_path.is_file():
        return {}
    return json.loads(info_path.read_text(encoding="utf-8")).get("pdf_metadata", {})


def resolve_metadata(
    ir: BookIR, cfg: Config, pdf_meta: dict[str, str], slug: str
) -> dict[str, Any]:
    """Config > PDF metadata > first heading > slug."""
    m = cfg.metadata
    title = m.title
    if not title:
        t = (pdf_meta.get("Title") or "").strip()
        if t and not _JUNK_TITLE.search(t):
            title = t
    if not title:
        first = next((b for b in ir.blocks if b.kind == BlockKind.HEADING and b.text.strip()), None)
        title = first.text.strip().title() if first else None
    if not title:
        title = slug.replace("-", " ").title()

    authors = list(m.authors)
    if not authors and (a := (pdf_meta.get("Author") or "").strip()):
        authors = [s.strip() for s in re.split(r";|\band\b", a) if s.strip()]

    meta: dict[str, Any] = {
        "title": title,
        "lang": m.language or ir.meta.language or "en",
    }
    if authors:
        meta["author"] = authors
    if m.isbn:
        meta["identifier"] = [{"scheme": "ISBN", "text": m.isbn}]
    else:
        seed = f"rebind:{slug}:{title}"
        meta["identifier"] = [
            {"scheme": "UUID", "text": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"}
        ]
    for key in ("publisher", "date", "rights"):
        if val := getattr(m, key):
            meta[key] = val
    return meta


def _check_pandoc() -> None:
    v = tools.version("pandoc") or "0"
    parts = tuple(int(x) for x in re.findall(r"\d+", v)[:2])
    if parts < MIN_PANDOC:
        raise RebindError(f"pandoc >= {MIN_PANDOC[0]}.{MIN_PANDOC[1]} required (found {v})")


def _file_hash(path: Path | None) -> str:
    if path is None or not Path(path).is_file():
        return ""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _bundled_css() -> bytes:
    return files("rebind.assets").joinpath("epub.css").read_bytes()


def _css_sources(cfg: Config) -> list[tuple[str, bytes]]:
    """(file name, content): the bundled stylesheet, then build.css if set."""
    css = [("epub.css", _bundled_css())]
    if cfg.build.css is not None:
        if not cfg.build.css.is_file():
            raise RebindError(f"build.css not found: {cfg.build.css}")
        css.append(("extra.css", cfg.build.css.read_bytes()))
    return css


def _cover_source(ctx: StageContext) -> Path | None:
    """metadata.cover, else the rendered first page when build.cover is on."""
    cfg = ctx.cfg
    if cfg.metadata.cover is not None:
        if not cfg.metadata.cover.is_file():
            raise RebindError(f"metadata.cover not found: {cfg.metadata.cover}")
        return cfg.metadata.cover
    if cfg.build.cover:
        candidate = ctx.job.dir("rasterize") / "cover.png"
        if candidate.is_file():
            return candidate
    return None


class BuildStage:
    name = "build"
    version = "3"  # 3: native EPUB writer (pandoc optional)
    config_keys: tuple[str, ...] = ("metadata", "build")
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        cfg = ctx.cfg
        return ":".join(
            [
                cfg.build.backend,
                (tools.version("pandoc") or "") if cfg.build.backend == "pandoc" else "",
                _file_hash(cfg.build.css),
                _file_hash(cfg.metadata.cover),
                hashlib.sha256(_bundled_css()).hexdigest()[:16],
            ]
        )

    def run(self, ctx: StageContext) -> dict[str, Any]:
        job, cfg = ctx.job, ctx.cfg
        backend = cfg.build.backend
        if backend == "pandoc":
            tools.require("pandoc")
            _check_pandoc()
        out = job.dir(self.name)
        ir = BookIR.load(job.clean_ir)
        meta = resolve_metadata(ir, cfg, _pdf_metadata(ctx), job.slug)
        css = _css_sources(cfg)
        cover = _cover_source(ctx)

        if backend == "native":
            res = epub.write_epub(
                job.epub,
                ir,
                meta,
                image_source=job.abs,
                css=css,
                cover=cover,
                split_level=cfg.build.split_level,
                toc_depth=cfg.build.toc_depth,
            )
            for w in res.warnings:
                ctx.warn(w)
            n_images = res.images
            extra: dict[str, Any] = {
                "chapters": res.chapters,
                "footnotes": res.notes,
                "toc_entries": res.nav_entries,
            }
        else:
            n_images = _build_pandoc(ctx, ir, meta, css, cover)
            extra = {}

        if cfg.build.azw3:
            if tools.which("ebook-convert"):
                tools.run(["ebook-convert", "book.epub", "book.azw3"], cwd=out)
            else:
                ctx.warn("build.azw3 requested but Calibre's ebook-convert is not installed")

        size_kib = job.epub.stat().st_size // 1024
        ctx.info(f"{job.rel(job.epub)} ({size_kib} KiB, {backend}), title: {meta['title']!r}")
        return {
            "backend": backend,
            "title": meta["title"],
            "authors": meta.get("author", []),
            "epub_bytes": job.epub.stat().st_size,
            "images": n_images,
            "cover": cover.name if cover else None,
            **extra,
        }


def _build_pandoc(
    ctx: StageContext,
    ir: BookIR,
    meta: dict[str, Any],
    css: list[tuple[str, bytes]],
    cover_src: Path | None,
) -> int:
    """BookIR -> Pandoc Markdown -> EPUB 3 with the pandoc binary. Returns the
    number of images."""
    job, cfg = ctx.job, ctx.cfg
    out = job.dir("build")

    # Images referenced by blocks are copied next to the Markdown.
    img_out = out / "images"
    copied: dict[str, str] = {}

    def image_href(rel: str) -> str:
        if rel not in copied:
            src = job.abs(rel)
            img_out.mkdir(exist_ok=True)
            dst = img_out / src.name
            shutil.copyfile(src, dst)
            copied[rel] = f"images/{dst.name}"
        return copied[rel]

    md = markdown.render(ir, image_href)
    (out / "book.md").write_text(md, encoding="utf-8")
    # JSON is valid YAML, and avoids any quoting surprises.
    (out / "metadata.yaml").write_text(
        json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    for name, data in css:
        (out / name).write_bytes(data)
    cover: Path | None = None
    if cover_src is not None:
        cover = out / ("cover" + cover_src.suffix.lower())
        shutil.copyfile(cover_src, cover)

    args: list[str | Path] = [
        "pandoc",
        "book.md",
        "--from",
        "markdown-smart",
        "--to",
        "epub3",
        "--output",
        "book.epub",
        "--metadata-file",
        "metadata.yaml",
        "--toc",
        f"--toc-depth={cfg.build.toc_depth}",
        f"--split-level={cfg.build.split_level}",
        "--resource-path",
        ".",
    ]
    for name, _ in css:
        args += ["--css", name]
    if cover is not None:
        args += ["--epub-cover-image", cover.name]
    proc = tools.run(args, cwd=out)
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines()[:20]:
            ctx.warn(f"pandoc: {line}")
    return len(copied)


STAGE = BuildStage()
