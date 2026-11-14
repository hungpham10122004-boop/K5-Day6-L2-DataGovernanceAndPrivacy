"""Tests for the T09 policy engine + pipeline (no ground truth needed)."""
import copy
import json

import pandas as pd
import pytest
import yaml

from src import main as runner
from src.policy_engine import evaluate_case, load_cases, load_policy

POLICY = "configs/policy/privacy_policy_v1.yaml"
FX = "fixtures/t09_privacy_gate"


def _clean_case(market="EU"):
    return {
        "case_id": "X", "market": market, "lawful_basis": "legitimate_interest", "ambiguity_notes": "",
        "consent": {"obtained": False, "granular": False, "withdrawable": False, "record_available": False},
        "notice_given": True, "storage": {"raw_retained": False, "location": "on_device", "encryption_at_rest": True},
        "transfer": {"cross_border": False, "mechanism": None, "transfer_impact_assessment": False},
        "retention_days": 90, "dpia_done": True, "minors_possible": False,
    }


def _run(tmp_path, name="poc", extra=()):
    out = tmp_path / name
    rc = runner.main(["--config", "configs/lab.yaml", "--track", "t09", "--output", str(out), "--offline", "--seed", "42", *extra])
    return rc, out


def test_pipeline_end_to_end_success(tmp_path):
    rc, out = _run(tmp_path)
    assert rc == 0
    d = pd.read_csv(out / "decisions.csv").set_index("case_id")
    assert len(d) == 12 and set(d.decision) <= {"GO", "HOLD", "REWORK"}
    assert d.loc["CASE-01", "decision"] == "HOLD" and "NO_LAWFUL_BASIS" in d.loc["CASE-01", "reason_codes"]
    assert d.loc["CASE-02", "decision"] == "HOLD"          # consent present but no transfer mechanism
    assert (d.rule_ids.notna() | (d.decision == "GO")).all()  # every non-GO has a rule trace
    assert (out / "review_queue.csv").exists() and (out / "decision.json").exists()


def test_precedence_hold_over_rework_over_go():
    p = load_policy(POLICY)
    c = _clean_case()
    assert evaluate_case(c, p).decision == "GO"
    c["notice_given"] = False                               # REWORK rule
    assert evaluate_case(c, p).decision == "REWORK"
    c["transfer"].update(cross_border=True, mechanism="unknown")   # HOLD rule joins
    assert evaluate_case(c, p).decision == "HOLD"


def test_future_effective_rule_is_advisory_only():
    p = load_policy(POLICY)
    c = _clean_case("IN")
    c.update(lawful_basis="consent", minors_possible=True)
    r = evaluate_case(c, p)
    assert r.decision == "GO" and r.advisory                # DPDP not in force yet -> note, not a violation
    later = evaluate_case(c, load_policy(POLICY, as_of="2027-06-01"))
    assert later.decision != "GO"                           # once effective it bites


def test_vn_has_no_legitimate_interest_but_eu_has():
    p = load_policy(POLICY)
    assert evaluate_case(_clean_case("VN"), p).decision == "HOLD"
    assert evaluate_case(_clean_case("EU"), p).decision == "GO"


def test_rule_without_source_is_rejected(tmp_path):
    raw = yaml.safe_load(open(POLICY, encoding="utf-8"))
    bad = copy.deepcopy(raw)
    del bad["rules"][0]["source"]
    f = tmp_path / "bad.yaml"
    f.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="source"):
        load_policy(f)


def test_baseline_consent_only_misses_risky_cases(tmp_path):
    rc, out = _run(tmp_path, "baseline", ["--pipeline", "src.baseline_t09"])
    assert rc == 0
    d = pd.read_csv(out / "decisions.csv").set_index("case_id")
    assert d.loc["CASE-02", "decision"] == "GO" and d.loc["CASE-07", "decision"] == "GO"   # false GO: cross-border ignored


def test_review_override_to_go_requires_note_and_is_audited(tmp_path):
    rc, out = _run(tmp_path)
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    i = q.index[q.item_id == "CASE-09"][0]
    q.loc[i, ["reviewer", "reviewer_decision", "override_value"]] = ["Dr. A (DPO)", "edit", "GO"]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)
    assert _run_again(out) == 2                              # GO override without note -> clear failure
    q.loc[i, "review_note"] = "DPDP chua hieu luc den 2027-05-13; chap nhan rui ro"
    q.to_csv(out / "review_queue_reviewed.csv", index=False)
    assert _run_again(out) == 0
    d = pd.read_csv(out / "decisions.csv").set_index("case_id")
    assert d.loc["CASE-09", "decision"] == "GO" and d.loc["CASE-09", "final_source"] == "human:edit"
    log = [json.loads(x) for x in (out / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["action"] == "override:edit" and e["item_id"] == "CASE-09" and e["actor"] == "Dr. A (DPO)" for e in log)


def _run_again(out):
    return runner.main(["--config", "configs/lab.yaml", "--track", "t09", "--output", str(out), "--offline", "--seed", "42"])


def test_missing_cases_folder_fails_clearly(tmp_path):
    rc = runner.main(["--config", "configs/lab.yaml", "--track", "t09", "--input", str(tmp_path), "--output", str(tmp_path / "o"), "--offline"])
    assert rc == 2
