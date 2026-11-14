"""Offline policy engine: rule file (YAML, versioned, with source) -> GO/HOLD/REWORK per case.

Rule DSL: `when` = {all: [cond,...]} | {any: [cond,...]}; cond = {field, op, value}.
Precedence: HOLD > REWORK > GO. Rules whose effective_date is after `as_of_date` are
advisory only (reported, never change the decision). Learning tool, not legal advice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

PRECEDENCE = {"GO": 0, "REWORK": 1, "HOLD": 2}
OPS = {"eq", "ne", "in", "not_in", "is_null", "not_null", "truthy", "falsy", "gt", "contains"}


@dataclass
class Policy:
    version: str
    as_of: date
    reason_codes: list[str]
    defaults: dict
    rules: list[dict]


@dataclass
class Result:
    case_id: str
    decision: str
    reason_codes: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    needs_legal_review: bool = False


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _validate_cond(c: dict, rid: str) -> None:
    if "all" in c or "any" in c:
        for sub in c.get("all", []) + c.get("any", []):
            _validate_cond(sub, rid)
        return
    if c.get("op") not in OPS or "field" not in c:
        raise ValueError(f"rule {rid}: invalid condition {c}")


def load_policy(path: str | Path, as_of: str | date | None = None) -> Policy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    codes = list(raw.get("reason_codes") or [])
    seen = set()
    for r in raw.get("rules", []):
        rid = r.get("id")
        if not rid or rid in seen:
            raise ValueError(f"rule id missing or duplicated: {rid!r}")
        seen.add(rid)
        if not r.get("source") or not r["source"].get("doc"):
            raise ValueError(f"rule {rid}: `source` is mandatory (rule without a cited source)")
        if r.get("decision") not in PRECEDENCE or r["decision"] == "GO":
            raise ValueError(f"rule {rid}: decision must be HOLD or REWORK")
        if r.get("reason_code") not in codes:
            raise ValueError(f"rule {rid}: unknown reason_code {r.get('reason_code')!r}")
        _validate_cond(r.get("when") or {}, rid)
    return Policy(str(raw.get("policy_version")), _as_date(as_of or raw["as_of_date"]), codes,
                  raw.get("defaults") or {}, raw["rules"])


def _get(case: dict, path: str):
    cur = case
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _eval_cond(c: dict, case: dict, params: dict) -> bool:
    if "all" in c:
        return all(_eval_cond(s, case, params) for s in c["all"])
    if "any" in c:
        return any(_eval_cond(s, case, params) for s in c["any"])
    v = _get(case, c["field"])
    ref = c.get("value")
    if isinstance(ref, str) and ref.startswith("$"):
        ref = params[ref[1:]]
    op = c["op"]
    if op == "eq":
        return v == ref
    if op == "ne":
        return v != ref
    if op == "in":
        return v in ref
    if op == "not_in":
        return v not in ref
    if op == "is_null":
        return v is None
    if op == "not_null":
        return v is not None
    if op == "truthy":
        return bool(v)
    if op == "falsy":
        return not v
    if op == "gt":
        return v is not None and v > ref
    if op == "contains":
        return v is not None and ref in v
    raise ValueError(op)


def evaluate_case(case: dict, policy: Policy, params: dict | None = None) -> Result:
    params = {**policy.defaults, **(params or {})}
    market = case.get("market")
    res = Result(case_id=case["case_id"], decision="GO")
    for r in policy.rules:
        if "*" not in r["markets"] and market not in r["markets"]:
            continue
        if not _eval_cond(r["when"], case, params):
            continue
        src = r["source"]
        tag = f"{r['id']}: {src.get('doc')} {src.get('ref', '')}".strip()
        eff = r.get("effective_date")
        if eff and _as_date(eff) > policy.as_of:
            res.advisory.append(f"{r['id']}:{r['reason_code']} (effective {_as_date(eff)}, not yet in force)")
            continue
        res.rule_ids.append(r["id"])
        res.sources.append(tag)
        if r["reason_code"] not in res.reason_codes:
            res.reason_codes.append(r["reason_code"])
        res.needs_legal_review |= bool(r.get("needs_legal_review"))
        if PRECEDENCE[r["decision"]] > PRECEDENCE[res.decision]:
            res.decision = r["decision"]
    return res


def load_cases(cases_dir: str | Path) -> list[dict]:
    files = sorted(Path(cases_dir).glob("CASE-*.json"))
    if not files:
        raise FileNotFoundError(f"no CASE-*.json in {cases_dir}")
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]
