"""cleanup: ordered IR -> IR rules, each switchable and change-recording.

Rules are pure functions `(BookIR, Config) -> (BookIR, list[Change])`. They must
not mutate their input.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from inkthaw.config import Config
from inkthaw.ir import BookIR
from inkthaw.pipeline import StageContext
from inkthaw.stages.cleanup.base import Change, Rule, RuleFn

__all__ = ["Change", "Rule", "RuleFn", "apply_rules", "registry"]


def registry() -> list[Rule]:
    from inkthaw.stages.cleanup import (
        chapters,
        footnotes,
        frontmatter,
        furniture,
        headers,
        hyphenation,
        paragraphs,
        reading_order,
        typography,
    )

    # Order matters: drop furniture first, fix text before merging across
    # pages, link footnotes on final text (offsets), shape structure last.
    return [
        Rule("furniture", furniture.drop_furniture, lambda c: c.cleanup.drop_furniture),
        Rule("reading_order", reading_order.fix_reading_order, lambda c: c.cleanup.reading_order),
        Rule("headers", headers.drop_running_headers, lambda c: c.cleanup.running_headers),
        Rule("typography", typography.normalize_typography, lambda c: c.cleanup.typography),
        Rule("hyphenation", hyphenation.join_hyphenation, lambda c: c.cleanup.hyphenation),
        Rule("paragraphs", paragraphs.merge_paragraphs, lambda c: c.cleanup.merge_paragraphs),
        Rule("footnotes", footnotes.link_footnotes, lambda c: c.cleanup.footnotes),
        Rule("chapters", chapters.structure_chapters, lambda c: c.cleanup.chapters),
        Rule("front_matter", frontmatter.mark_front_matter, lambda c: c.cleanup.front_matter),
    ]


def apply_rules(ir: BookIR, cfg: Config) -> tuple[BookIR, list[Change], list[str]]:
    changes: list[Change] = []
    applied: list[str] = []
    for rule in registry():
        if not rule.enabled(cfg):
            continue
        ir, rule_changes = rule.fn(ir, cfg)
        changes.extend(rule_changes)
        applied.append(rule.name)
    return ir, changes, applied


class CleanupStage:
    name = "cleanup"
    version = "3"  # 3: review fixes (paragraph merge, suspended hyphens, headings)
    config_keys: tuple[str, ...] = ("cleanup", "metadata")
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        from importlib.metadata import version

        try:
            wf = version("wordfreq")
        except Exception:
            wf = "none"
        return ",".join(r.name for r in registry()) + f";wordfreq={wf}"

    def run(self, ctx: StageContext) -> dict[str, Any]:
        job, cfg = ctx.job, ctx.cfg
        ir = BookIR.load(job.raw_ir)
        before = len(ir.blocks)
        ir, changes, applied = apply_rules(ir, cfg)
        ir.save(job.clean_ir)
        (job.dir(self.name) / "changes.json").write_text(
            json.dumps([asdict(c) for c in changes], indent=1), encoding="utf-8"
        )
        by_rule: dict[str, int] = {}
        for c in changes:
            by_rule[c.rule] = by_rule.get(c.rule, 0) + 1
        ctx.info(f"rules: {', '.join(applied) or 'none'}; {len(changes)} changes")
        return {
            "rules": applied,
            "changes": by_rule,
            "blocks_before": before,
            "blocks_after": len(ir.blocks),
        }


STAGE = CleanupStage()
