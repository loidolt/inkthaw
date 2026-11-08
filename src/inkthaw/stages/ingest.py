"""ingest: copy the PDF into the job, hash it, record geometry and scan DPI."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from typing import Any

from inkthaw import pdf
from inkthaw.errors import InkthawError
from inkthaw.job import sha256_file
from inkthaw.pipeline import StageContext

# A page "has text" if its text layer has at least this many non-space chars.
TEXT_PAGE_MIN_CHARS = 200
TEXT_LAYER_PAGE_FRACTION = 0.5


class IngestStage:
    name = "ingest"
    version = "2"  # 2: read with PDFium instead of poppler
    config_keys: tuple[str, ...] = ()
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        pdfium = pdf.versions()["pdfium"]
        if ctx.input_pdf is not None:
            return f"{sha256_file(ctx.input_pdf)};pdfium={pdfium}"
        if ctx.manifest.input_sha256:
            return f"{ctx.manifest.input_sha256};pdfium={pdfium}"
        raise InkthawError("No input PDF given and the job has not been ingested yet")

    def run(self, ctx: StageContext) -> dict[str, Any]:
        src = ctx.input_pdf
        if src is None:
            raise InkthawError("ingest needs the input PDF path")
        if not src.is_file():
            raise InkthawError(f"Input not found: {src}")
        dst = ctx.job.source_pdf
        shutil.copyfile(src, dst)
        digest = sha256_file(dst)

        fields, pages = pdf.inspect(dst)
        if not pages:
            raise InkthawError(f"{src}: no pages found (is it a valid PDF?)")

        chars = pdf.text_chars_per_page(dst)
        text_pages = sum(1 for c in chars if c >= TEXT_PAGE_MIN_CHARS)
        has_text_layer = text_pages >= TEXT_LAYER_PAGE_FRACTION * len(pages)
        if has_text_layer:
            ctx.warn(
                f"PDF already has a text layer on {text_pages}/{len(pages)} pages. "
                "inkthaw will OCR the page images anyway."
            )

        ppis = [p.scan_ppi for p in pages if p.scan_ppi]
        median_ppi = sorted(ppis)[len(ppis) // 2] if ppis else None
        no_image_pages = sum(1 for p in pages if not p.images)
        if no_image_pages == len(pages):
            ctx.warn("No embedded images found: this may be a born-digital PDF, not a scan.")

        info = {
            "source_name": src.name,
            "sha256": digest,
            "page_count": len(pages),
            "pdf_metadata": {
                k: v
                for k, v in fields.items()
                if k
                in {"Title", "Author", "Subject", "Creator", "Producer", "CreationDate", "Keywords"}
            },
            "median_scan_ppi": median_ppi,
            "text_layer": {
                "pages_with_text": text_pages,
                "chars_per_page": chars,
                "usable": has_text_layer,
            },
            "pages": [
                {**asdict(p), "aspect": round(p.aspect, 4), "scan_ppi": p.scan_ppi} for p in pages
            ],
        }
        ctx.job.source_info.write_text(json.dumps(info, indent=1), encoding="utf-8")
        ctx.manifest.input_sha256 = digest
        ctx.manifest.source_name = src.name
        ctx.info(
            f"{len(pages)} pages, scan ppi ~{median_ppi or '?'}, "
            f"text layer: {'yes' if has_text_layer else 'no'}"
        )
        return {
            "page_count": len(pages),
            "median_scan_ppi": median_ppi,
            "has_text_layer": has_text_layer,
            "warnings": list(ctx.warnings),
        }


STAGE = IngestStage()
