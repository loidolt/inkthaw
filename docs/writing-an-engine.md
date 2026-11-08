# Writing an engine

Engines are found through the `inkthaw.engines` entry-point group, so an engine
can live in its own package and be installed next to inkthaw.

## 1. Implement the protocol

The protocol is in [`src/inkthaw/engines/base.py`](../src/inkthaw/engines/base.py).
A complete, tested example is `EchoEngine` in
[`tests/unit/test_engine_protocol.py`](../tests/unit/test_engine_protocol.py).

```python
from pathlib import Path

from inkthaw.config import Config
from inkthaw.engines import Capabilities, EngineContext
from inkthaw.ir import Block, BlockKind, BookIR, Page


class MyEngine:
    name = "myengine"

    @property
    def version(self) -> str:
        return "0.1"  # include the model version: it is part of the cache key

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(layout=True, tables=False, page_furniture=True, confidence=True)

    def available(self) -> tuple[bool, str]:
        # Cheap check only (imports, binaries). Do not load models here.
        return True, "ready"

    def settings_key(self, cfg: Config) -> str:
        # Anything that changes output: model, languages, options.
        return f"{self.version}:{','.join(cfg.ocr_languages())}"

    def prefetch(self, cfg: Config, log) -> Path | None:
        # Download weights into cfg.models_dir if set; return None if you don't.
        return None

    def convert(self, pages: list[Page], cfg: Config, ctx: EngineContext) -> BookIR:
        ir = BookIR(engine=self.name, engine_version=self.version, pages=list(pages))
        for page in pages:
            image = ctx.job_root / page.image_path
            for n, (kind, text, bbox) in enumerate(run_my_model(image), start=1):
                ir.blocks.append(
                    Block(
                        id=f"p{page.index + 1:04d}-b{n:03d}",
                        kind=kind,
                        text=text,
                        page=page.index,
                        bbox=bbox,
                    )
                )
            ctx.advance()  # once per page: drives the progress bar
        return ir
```

## 2. Register it

In your package's `pyproject.toml`:

```toml
[project.entry-points."inkthaw.engines"]
myengine = "my_package.engine:MyEngine"
```

Then `inkthaw engines` lists it and `engine = "myengine"` (or `--engine
myengine`) selects it.

## 3. What inkthaw expects from the output

- **Reading order.** Blocks in the order a person reads them. Put a page's
  running header first and its footer last. The `reading_order` cleanup rule
  fixes single-column pages if your order is off, but only when every block
  on the page has a `bbox`.
- **Coordinates.** `bbox` in pixels of the page image you were given, origin
  top-left: `(x0, y0, x1, y1)`. Several rules use them (reading order, column
  breaks, header detection).
- **Kinds.** Label running headers, footers and page numbers as such if your
  model can; the `running_headers` rule is only a fallback. Use `heading` with
  `level` (1 = top) for titles and chapter headings, `footnote` for notes at
  the foot of the page with their marker kept at the start of the text
  ("12 See ..."), `list_item` with `attrs["enumerated"]`, `table` with
  `attrs["rows"]` (list of rows of cell strings), `image` with
  `attrs["image_path"]` (relative to the job folder; write images into
  `ctx.work_dir`).
- **Text.** Plain text, one block per paragraph. Do not join hyphenated line
  breaks across pages or fix typography: cleanup does that the same way for
  every engine.
- **Confidence.** `page.confidence` and/or `block.confidence` in 0..1 if
  available; the report flags low values.
- **Ids.** Unique within the book and stable between runs for the same input.

## 4. Caching and resuming

`ctx.work_dir` is the OCR stage's folder and is **not** wiped between runs.
Cache per-page results there, keyed by the page image's hash and
`settings_key(cfg)`, so interrupted runs resume (the Docling engine does
this). Call `ctx.warn(...)` for problems the user should see and `ctx.log(...)`
for progress details.

## 5. Check it

- Run the [benchmark](benchmarks.md) with `engine = "myengine"` and compare
  CER, paragraph F1 and the flagged-page counts with the default engine.
- Run `scripts/check_licenses.py` in an environment with your engine
  installed. Engines bundled with inkthaw must be permissively licensed,
  weights included (PLAN.md §2).
