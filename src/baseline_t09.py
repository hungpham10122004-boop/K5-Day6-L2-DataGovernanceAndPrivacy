"""Baseline T09 (intentionally wrong): "has consent -> GO, otherwise HOLD".

    python -m src.main --track t09 --pipeline src.baseline_t09 --output out/baseline --run-name baseline --offline --seed 42
Trivial baseline "HOLD everything" (critical-miss 0 but fails the false-HOLD guardrail): src.baseline_t09_hold_all
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .policy_engine import load_cases


def _write(ctx: RunContext, decide) -> None:
    rows = [{"case_id": c["case_id"], "decision": decide(c), "reason_codes": "BASELINE"} for c in load_cases(ctx.input_dir / "cases")]
    ctx.stats["n_items"] = len(rows)
    pd.DataFrame(rows).to_csv(ctx.out("decisions.csv"), index=False)


def run(ctx: RunContext) -> None:
    if ctx.track != "t09":
        raise NotImplementedError("baseline_t09 supports T09 only")
    _write(ctx, lambda c: "GO" if c["consent"]["obtained"] else "HOLD")
