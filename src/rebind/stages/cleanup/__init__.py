"""cleanup: ordered IR -> IR rules, each switchable and change-recording.

Rules are pure functions `(BookIR, Config) -> (BookIR, list[Change])`. They must
not mutate their input.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from rebind.config import Config
from rebind.ir import BookIR
from rebind.pipeline import StageContext
from rebind.stages.cleanup.base import Change, Rule, RuleFn

__all__ = ["Change", "Rule", "RuleFn", "apply_rules", "registry"]


def registry() -> list[Rule]:
    from rebind.stages.cleanup import furniture

    # Order matters. M2 adds: headers, hyphenation, paragraphs, typography,
    # footnotes, chapters, front matter.
    return [
        Rule("furniture", furniture.drop_furniture, lambda c: c.cleanup.drop_furniture),
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
    version = "1"
    config_keys: tuple[str, ...] = ("cleanup",)
    clean_dir = True

    def extra_key(self, ctx: StageContext) -> str:
        return ",".join(r.name for r in registry())

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
