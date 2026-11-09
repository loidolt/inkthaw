# pyright: reportPrivateImportUsage=false
"""Docling engine (MIT): layout analysis + OCR, mapped onto BookIR.

Pages are converted one image at a time so results can be cached per page:
an interrupted OCR run resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import warnings
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from inkthaw.config import Config
from inkthaw.engines.base import Capabilities, EngineContext
from inkthaw.engines.devices import available_devices, resolve_device
from inkthaw.errors import InkthawError
from inkthaw.ir import Block, BlockKind, BookIR, Page
from inkthaw.text import is_page_number

CACHE_VERSION = "1"
MODELS_MARKER = ".inkthaw-models.json"


def _quiet(record: logging.LogRecord) -> bool:
    return record.levelno >= logging.ERROR


_LABEL_KIND: dict[str, BlockKind] = {
    "title": BlockKind.HEADING,
    "section_header": BlockKind.HEADING,
    "text": BlockKind.PARAGRAPH,
    "paragraph": BlockKind.PARAGRAPH,
    "reference": BlockKind.PARAGRAPH,
    "handwritten_text": BlockKind.PARAGRAPH,
    "footnote": BlockKind.FOOTNOTE,
    "caption": BlockKind.CAPTION,
    "table": BlockKind.TABLE,
    "document_index": BlockKind.TABLE,
    "picture": BlockKind.IMAGE,
    "chart": BlockKind.IMAGE,
    "list_item": BlockKind.LIST_ITEM,
    "page_header": BlockKind.PAGE_HEADER,
    "page_footer": BlockKind.PAGE_FOOTER,
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def classify(label: str, text: str) -> BlockKind:
    kind = _LABEL_KIND.get(label, BlockKind.OTHER)
    if kind in (BlockKind.PAGE_HEADER, BlockKind.PAGE_FOOTER) and is_page_number(text):
        return BlockKind.PAGE_NUMBER
    return kind


class DoclingEngine:
    name = "docling"

    @property
    def version(self) -> str:
        try:
            return pkg_version("docling")
        except PackageNotFoundError:
            return "not-installed"

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            layout=True,
            tables=True,
            pictures=True,
            footnotes=True,
            page_furniture=True,
            confidence=True,
            devices=tuple(available_devices()),
        )

    def available(self) -> tuple[bool, str]:
        if importlib.util.find_spec("docling") is None:
            return False, "docling is not installed (pip install 'inkthaw[docling]')"
        return True, f"docling {self.version}"

    def settings_key(self, cfg: Config) -> str:
        return json.dumps(
            {
                "cache": CACHE_VERSION,
                "docling": self.version,
                "ocr": cfg.ocr.model_dump(mode="json"),
                "languages": cfg.ocr_languages(),
            },
            sort_keys=True,
        )

    # -- conversion ---------------------------------------------------------

    # -- model weights ------------------------------------------------------

    def artifacts_dir(self, cfg: Config) -> Path | None:
        return Path(cfg.models_dir) / "docling" if cfg.models_dir is not None else None

    def prefetch(self, cfg: Config, log: Callable[[str], None] = lambda _m: None) -> Path | None:
        """Download the weights this config needs into models_dir (no-op if present).

        Without models_dir, Docling and RapidOCR download into their own caches
        on first use instead.
        """
        target = self.artifacts_dir(cfg)
        if target is None:
            return None
        marker = target / MODELS_MARKER
        wanted = self._model_set(cfg)
        if marker.is_file() and json.loads(marker.read_text()) == wanted:
            return target
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        from docling.utils.model_downloader import download_models

        log(f"downloading model weights into {target} (one-time, about 700 MB)")
        try:
            target.mkdir(parents=True, exist_ok=True)
            self._download(target, cfg, wanted, download_models)
        except Exception as e:
            raise InkthawError(f"model download into {target} failed: {e}") from e
        marker.write_text(json.dumps(wanted))
        return target

    @staticmethod
    def _download(target: Path, cfg: Config, wanted: dict[str, Any], download_models: Any) -> None:
        download_models(
            output_dir=target,
            with_layout=True,
            with_tableformer=True,
            with_code_formula=False,
            with_picture_classifier=False,
            with_rapidocr=cfg.ocr.docling_ocr == "rapidocr",
            rapidocr_models=wanted["rapidocr"] or None,
        )

    def _model_set(self, cfg: Config) -> dict[str, Any]:
        rapid = (
            [f"{cfg.ocr.rapidocr_backend}:iso:{lang}" for lang in cfg.ocr_languages()]
            if cfg.ocr.docling_ocr == "rapidocr"
            else []
        )
        return {"docling": self.version, "rapidocr": rapid}

    def _converter(self, cfg: Config, ctx: EngineContext) -> Any:
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        artifacts = self.prefetch(cfg, ctx.log)
        # OCR back-ends reset their own logger level on init, so filter instead.
        for name in ("docling", "rapidocr", "RapidOCR", "easyocr"):
            logger = logging.getLogger(name)
            if _quiet not in logger.filters:
                logger.addFilter(_quiet)

        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            EasyOcrOptions,
            OcrAutoOptions,
            OcrMacOptions,
            OcrMode,
            PdfPipelineOptions,
            RapidOcrOptions,
            TesseractCliOcrOptions,
        )
        from docling.document_converter import DocumentConverter, ImageFormatOption

        ocr_cls = {
            "auto": OcrAutoOptions,
            "easyocr": EasyOcrOptions,
            "rapidocr": RapidOcrOptions,
            "tesseract": TesseractCliOcrOptions,
            "ocrmac": OcrMacOptions,
        }[cfg.ocr.docling_ocr]
        langs = [f"iso:{lang}" for lang in cfg.ocr_languages()]
        device = resolve_device(cfg.device)
        ctx.log(f"docling {self.version}, OCR={cfg.ocr.docling_ocr}, device={device}")

        opts = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=cfg.ocr.tables,
            generate_picture_images=cfg.ocr.pictures,
            images_scale=min(cfg.dpi / 72, 4.0),
        )
        if artifacts is not None:
            opts.artifacts_path = artifacts
        ocr_kwargs: dict[str, Any] = {"lang": langs, "mode": OcrMode.FULL_PAGE}
        if cfg.ocr.docling_ocr == "rapidocr":
            ocr_kwargs["backend"] = cfg.ocr.rapidocr_backend
            if cfg.ocr.rapidocr_params:
                ocr_kwargs["rapidocr_params"] = dict(cfg.ocr.rapidocr_params)
        opts.ocr_options = ocr_cls(**ocr_kwargs)
        opts.accelerator_options = AcceleratorOptions(
            device=device, num_threads=min(8, os.cpu_count() or 4)
        )
        return DocumentConverter(
            allowed_formats=[InputFormat.IMAGE],
            format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts)},
        )

    def convert(self, pages: list[Page], cfg: Config, ctx: EngineContext) -> BookIR:
        cache_dir = ctx.work_dir / "cache"
        raw_dir = ctx.work_dir / "docling"
        img_dir = ctx.work_dir / "images"
        for d in (cache_dir, raw_dir, img_dir):
            d.mkdir(parents=True, exist_ok=True)

        settings = self.settings_key(cfg)
        keys: dict[int, str] = {}
        cached: dict[int, dict[str, Any]] = {}
        todo: list[Page] = []
        for page in pages:
            key = hashlib.sha256(
                (settings + _sha256(ctx.job_root / page.image_path)).encode()
            ).hexdigest()[:20]
            keys[page.index] = key
            entry = self._read_cache(cache_dir / f"p{page.index + 1:04d}.json", key)
            if entry is not None:
                cached[page.index] = entry
                ctx.advance()
            else:
                todo.append(page)

        if cached:
            ctx.log(f"{len(cached)} pages from cache, {len(todo)} to convert")

        if todo:
            converter = self._converter(cfg, ctx)
            paths = [ctx.job_root / p.image_path for p in todo]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                results = converter.convert_all(paths, raises_on_error=False)
                for page, res in zip(todo, results, strict=True):
                    entry = self._error_entry(page, res, ctx) or self._page_entry(
                        page, res, img_dir, raw_dir, ctx
                    )
                    entry["key"] = keys[page.index]
                    if "engine_error" not in entry["page_attrs"]:
                        # A failed page is not cached, so the next run retries it.
                        (cache_dir / f"p{page.index + 1:04d}.json").write_text(
                            json.dumps(entry), encoding="utf-8"
                        )
                    cached[page.index] = entry
                    ctx.advance()

        ir = BookIR(engine=self.name, engine_version=self.version)
        ir.meta.language = cfg.metadata.language
        for page in pages:
            entry = cached[page.index]
            ir.pages.append(
                page.model_copy(
                    update={
                        "confidence": entry.get("confidence"),
                        "attrs": {**page.attrs, **entry.get("page_attrs", {})},
                    }
                )
            )
            ir.blocks.extend(Block.model_validate(b) for b in entry["blocks"])
        return ir

    @staticmethod
    def _read_cache(path: Path, key: str) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if entry.get("key") != key:
            return None
        if "engine_error" in (entry.get("page_attrs") or {}):
            return None  # written by an older version; retry the page
        return entry

    @staticmethod
    def _error_entry(page: Page, res: Any, ctx: EngineContext) -> dict[str, Any] | None:
        """The entry for a page Docling failed on, or None if it succeeded."""
        status = getattr(res.status, "value", res.status)
        if status in ("success", "partial_success"):
            return None
        errs = "; ".join(str(e.error_message) for e in (res.errors or []))
        ctx.warn(f"page {page.index + 1}: docling status {status} {errs}")
        return {"blocks": [], "confidence": None, "page_attrs": {"engine_error": errs}}

    def _page_entry(
        self, page: Page, res: Any, img_dir: Path, raw_dir: Path, ctx: EngineContext
    ) -> dict[str, Any]:
        from docling_core.types.doc import (
            ContentLayer,
            ListItem,
            PictureItem,
            SectionHeaderItem,
            TableItem,
        )

        doc = res.document
        stem = f"p{page.index + 1:04d}"
        try:
            (raw_dir / f"{stem}.json").write_text(
                json.dumps(doc.export_to_dict()), encoding="utf-8"
            )
        except Exception as e:  # debugging aid only
            ctx.warn(f"page {page.index + 1}: could not save raw docling JSON: {e}")

        confidence = None
        page_attrs: dict[str, Any] = {}
        conf = getattr(res, "confidence", None)
        if conf is not None and conf.pages:
            pc = next(iter(conf.pages.values()))
            scores = {
                k: getattr(pc, k, None)
                for k in ("ocr_score", "layout_score", "table_score", "mean_score")
            }
            page_attrs["scores"] = {
                k: (round(v, 4) if isinstance(v, float) and v == v else None)
                for k, v in scores.items()
            }
            ocr = page_attrs["scores"].get("ocr_score")
            confidence = ocr if ocr is not None else page_attrs["scores"].get("mean_score")

        dl_page = doc.pages.get(1) or next(iter(doc.pages.values()), None)
        page_w = dl_page.size.width if dl_page else page.width
        page_h = dl_page.size.height if dl_page else page.height
        sx, sy = page.width / page_w, page.height / page_h

        def bbox_of(item: Any) -> tuple[float, float, float, float] | None:
            if not getattr(item, "prov", None):
                return None
            bb = item.prov[0].bbox.to_top_left_origin(page_h)
            return (
                round(bb.l * sx, 1),
                round(bb.t * sy, 1),
                round(bb.r * sx, 1),
                round(bb.b * sy, 1),
            )

        header: list[dict[str, Any]] = []
        body: list[dict[str, Any]] = []
        footer: list[dict[str, Any]] = []
        n = 0
        for layer in (ContentLayer.FURNITURE, ContentLayer.BODY):
            for item, _depth in doc.iterate_items(included_content_layers={layer}):
                label = str(getattr(item.label, "value", item.label))
                text = (getattr(item, "text", "") or "").strip()
                kind = classify(label, text)
                attrs: dict[str, Any] = {"label": label}
                level: int | None = None
                if layer == ContentLayer.FURNITURE:
                    attrs["layer"] = "furniture"
                if kind == BlockKind.HEADING:
                    level = (
                        1
                        if label == "title"
                        else int(
                            getattr(item, "level", 1) if isinstance(item, SectionHeaderItem) else 1
                        )
                    )
                if isinstance(item, ListItem):
                    attrs["enumerated"] = bool(getattr(item, "enumerated", False))
                    if getattr(item, "marker", None):
                        attrs["marker"] = item.marker
                if isinstance(item, TableItem):
                    try:
                        attrs["rows"] = [[cell.text for cell in row] for row in item.data.grid]
                    except Exception:
                        attrs["rows"] = []
                    caption = item.caption_text(doc) if hasattr(item, "caption_text") else ""
                    if caption:
                        attrs["caption"] = caption
                if isinstance(item, PictureItem):
                    caption = item.caption_text(doc) if hasattr(item, "caption_text") else ""
                    if caption:
                        attrs["caption"] = caption
                    try:
                        img = item.get_image(doc)
                    except Exception:
                        img = None
                    if img is not None:
                        n_img = len(list(img_dir.glob(f"{stem}-*.png")))
                        out = img_dir / f"{stem}-{n_img + 1:02d}.png"
                        img.save(out)
                        attrs["image_path"] = (
                            out.resolve().relative_to(ctx.job_root.resolve()).as_posix()
                        )
                if not text and kind not in (BlockKind.IMAGE, BlockKind.TABLE):
                    continue
                n += 1
                block = Block(
                    id=f"{stem}-b{n:03d}",
                    kind=kind,
                    level=level,
                    text=text,
                    page=page.index,
                    bbox=bbox_of(item),
                    confidence=confidence,
                    attrs=attrs,
                ).model_dump(mode="json")
                if kind in (BlockKind.PAGE_HEADER, BlockKind.PAGE_FOOTER, BlockKind.PAGE_NUMBER):
                    top = block["bbox"][1] if block["bbox"] else 0
                    (header if top < page.height / 2 else footer).append(block)
                else:
                    body.append(block)
        return {
            "blocks": header + body + footer,
            "confidence": confidence,
            "page_attrs": page_attrs,
        }
