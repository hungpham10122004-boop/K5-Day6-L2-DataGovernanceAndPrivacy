"""Trivial baseline T09: HOLD every case (shows why the guardrail on false HOLD exists)."""
from __future__ import annotations

from .baseline_t09 import _write
from .common.context import RunContext


def run(ctx: RunContext) -> None:
    if ctx.track != "t09":
        raise NotImplementedError("baseline_t09_hold_all supports T09 only")
    _write(ctx, lambda c: "HOLD")
