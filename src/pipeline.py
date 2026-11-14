"""PoC pipeline for T09 - Multi-Market Privacy Decision Gate (offline, rule-based, human-in-the-loop).

01 load     cases + manifest sha256 check + versioned policy file
02 process  policy engine -> decision per case (HOLD > REWORK > GO), reason codes, rule ids, sources
03 rank     review queue (riskiest first) -> out/review_queue.csv
04 review   reviewer decisions (out/review_queue_reviewed.csv) -> overrides + audit_log.jsonl
05 decide   batch-level decision with reason_code + owner -> decision.json / decision_log.csv

Learning tool, not legal advice. Final decision belongs to the DPO / legal owner.
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, canonical_status, write_decision
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track
from .policy_engine import PRECEDENCE, evaluate_case, load_cases, load_policy

DEFAULT_POLICY = "configs/policy/privacy_policy_v1.yaml"


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    policy = load_policy(ctx.param("policy_file", DEFAULT_POLICY), ctx.param("as_of_date"))
    ctx.stats.update(policy_version=policy.version, as_of_date=str(policy.as_of))
    return {"cases": load_cases(ctx.input_dir / "cases"), "policy": policy}


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    params = {"max_retention_days": ctx.param("max_retention_days")}
    params = {k: v for k, v in params.items() if v is not None}
    rows = []
    for case in data["cases"]:
        r = evaluate_case(case, data["policy"], params)
        score = PRECEDENCE[r.decision] + 0.1 * len(r.rule_ids) + (0.05 if r.advisory else 0)
        rows.append({
            "case_id": r.case_id, "decision": r.decision, "reason_codes": ";".join(r.reason_codes),
            "market": case.get("market"), "rule_ids": ";".join(r.rule_ids), "sources": " | ".join(r.sources),
            "advisory": " | ".join(r.advisory), "needs_legal_review": r.needs_legal_review,
            "final_source": "policy", "score": round(score, 3), "reason": ";".join(r.reason_codes) or "no_rule_fired",
            "evidence_path": f"cases/{r.case_id}.json",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    budget = int(ctx.param("budget", len(scored)))
    q = make_review_queue(scored, "case_id", "score", budget, reason_col="reason", action_col="decision",
                          slice_col="market", evidence_col="evidence_path")
    write_review_queue(q, ctx.out("review_queue.csv"))
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Apply human decisions. approve/skip = log only; escalate = force HOLD;
    edit/reject + override_value = set decision (GO over a non-GO needs a review_note)."""
    path = ctx.output_dir / "review_queue_reviewed.csv"
    if not path.exists():
        return scored
    reviewed = load_review_decisions(path)
    ctx.stats["n_reviewed"] = len(reviewed)
    final = scored.copy()
    current = dict(zip(final.case_id, final.decision))
    for r in reviewed.itertuples(index=False):
        if r.item_id not in current:
            raise ValueError(f"reviewed row for unknown case {r.item_id!r}")
        if r.reviewer_decision in {"approve", "skip"}:
            ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=r.item_id,
                          before=current[r.item_id], after=current[r.item_id], reason=r.review_note)
        elif r.reviewer_decision == "escalate":
            final.loc[final.case_id == r.item_id, ["decision", "final_source"]] = ["HOLD", "human:escalate"]
            ctx.audit.log(actor=r.reviewer, action="review:escalate", item_id=r.item_id,
                          before=current[r.item_id], after="HOLD", reason=r.review_note)
        else:  # edit / reject
            if not str(r.override_value).strip():
                raise ValueError(f"{r.item_id}: {r.reviewer_decision} needs override_value (GO/HOLD/REWORK)")
            new = canonical_status(r.override_value)
            if new == "GO" and current[r.item_id] != "GO" and not r.review_note.strip():
                raise ValueError(f"{r.item_id}: overriding {current[r.item_id]} -> GO requires a review_note")
            final = apply_overrides(final, reviewed[reviewed.item_id == r.item_id].assign(override_value=new),
                                    "case_id", "decision", ctx.audit)
            final.loc[final.case_id == r.item_id, "final_source"] = f"human:{r.reviewer_decision}"
    return final


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    counts = final.decision.value_counts().to_dict()
    owner = ctx.config.get("owner", "TODO-owner")
    if counts.get("HOLD"):
        status, code, why = "HOLD", "CASES_ON_HOLD", f"{counts['HOLD']} case(s) HOLD: DPO/legal must resolve before release"
    elif counts.get("REWORK"):
        status, code, why = "REWORK", "CASES_NEED_REWORK", f"{counts['REWORK']} case(s) need rework before release"
    else:
        status, code, why = "GO", "ALL_CASES_CLEARED", "no case blocked by the policy (still needs legal sign-off)"
    return Decision(status=status, reason_code=code, reason=why, owner=owner, scope=ctx.track,
                    evidence=["decisions.csv", "review_queue.csv", "audit_log.jsonl"], metrics=counts)


def run(ctx: RunContext) -> None:
    if ctx.track != "t09":
        raise NotImplementedError(f"src/pipeline.py implements T09 only (got {ctx.track})")
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    cols = spec.pred_columns + ["reason_codes", "market", "rule_ids", "sources", "advisory", "needs_legal_review", "final_source"]
    final[cols].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
