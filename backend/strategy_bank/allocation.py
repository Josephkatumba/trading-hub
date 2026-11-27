"""Strategy allocation: which evidence class a strategy has EARNED, and the attention weight that follows.

ADVISORY ONLY. Nothing here enables, disables, promotes, alerts, sizes or executes anything: the
live scanner registry (strategies.REGISTRY), the bank deployment statuses (strategy_bank.rules) and
every execution permission stay exactly as they are. This module reads evidence and reports a class;
any change of deployment is an owner decision.

Allocation classes (lowest to highest), and what each requires:
  RESEARCH      default. Runs in research/shadow, or has no credible edge, or its record is
                significantly negative (then `suspension_recommended` is set).
  EXPERIMENTAL  positive after costs over all historical periods, but fails at least one validation
                test (evidence tier RESEARCH = "promising but unproven"). May be watched forward.
  VALIDATED     passes every historical validation test of strategy_bank.evidence_tiers (sample,
                out-of-sample, Holm-adjusted significance, doubled costs, walk-forward).
  PRODUCTION    VALIDATED, plus a recorded forward record meeting evidence_tiers.FORWARD, plus explicit
                owner approval listed in the policy file.

Signal VOLUME never enters any rule: a strategy producing thousands of signals with no edge stays
RESEARCH; one producing a few dozen with a validated edge can be VALIDATED.

Weight: only VALIDATED and PRODUCTION strategies receive weight, proportional to the LOWER bound of
the all-period 95% expectancy CI (a conservative edge estimate), capped per strategy, and shared out
within a diversification cluster (near-duplicate strategies split one allocation instead of each
taking a full one). If nothing qualifies, every weight is zero and the report says so.

The thresholds live in allocation_policy.json next to this file (configurable, versioned with the code).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CLASSES = ("RESEARCH", "EXPERIMENTAL", "VALIDATED", "PRODUCTION")
POLICY_PATH = Path(__file__).with_name("allocation_policy.json")
DEFAULT_POLICY: dict[str, Any] = {
    "version": "allocation-policy-v1",
    "max_weight_per_strategy": 0.25,
    "min_ci_lower_r": 0.0,
    "production_approved": [],
    "notes": "Advisory. Edit production_approved only with an owner decision; it never changes the live engine by itself.",
}


def policy() -> dict[str, Any]:
    try:
        return {**DEFAULT_POLICY, **json.loads(POLICY_PATH.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT_POLICY)


def classify(evidence: dict[str, Any] | None, forward: dict[str, Any] | None, key: str,
             pol: dict[str, Any] | None = None) -> dict[str, Any]:
    """{class, suspension_recommended, blockers} from an evidence_tiers.classify() result."""
    from strategy_bank import evidence_tiers
    pol = pol or policy()
    tier = (evidence or {}).get("tier") or "EXPERIMENTAL"
    checks = (evidence or {}).get("checks") or {}
    blockers = [f"historical test failed: {name}" for name, c in checks.items() if not c.get("pass")]
    if not checks:
        blockers.append("no historical evaluation")
    if tier in ("VALIDATED", "PRODUCTION"):
        fwd_ok = evidence_tiers.forward_ok(forward)
        approved = key in (pol.get("production_approved") or [])
        if fwd_ok and approved:
            return {"class": "PRODUCTION", "suspension_recommended": False, "blockers": []}
        return {"class": "VALIDATED", "suspension_recommended": False,
                "blockers": (["forward record below the promotion gate"] if not fwd_ok else []) +
                            (["owner approval not recorded"] if not approved else [])}
    if tier == "RESEARCH":
        return {"class": "EXPERIMENTAL", "suspension_recommended": False, "blockers": blockers}
    return {"class": "RESEARCH", "suspension_recommended": tier == "SUSPENDED", "blockers": blockers}


def weights(rows: list[dict[str, Any]], clusters: dict[str, int] | None = None, pol: dict[str, Any] | None = None) -> dict[str, float]:
    """Attention weights over rows of {key, class, ci_lower}. Zero for everything below VALIDATED."""
    pol = pol or policy()
    cap, floor = float(pol["max_weight_per_strategy"]), float(pol["min_ci_lower_r"])
    raw: dict[str, float] = {}
    for r in rows:
        lo = r.get("ci_lower")
        if r.get("class") in ("VALIDATED", "PRODUCTION") and lo is not None and lo > floor:
            raw[r["key"]] = float(lo)
    if clusters:
        size: dict[int, int] = {}
        for k in raw:
            size[clusters.get(k, -1)] = size.get(clusters.get(k, -1), 0) + 1
        raw = {k: v / size[clusters.get(k, -1)] for k, v in raw.items()}
    total = sum(raw.values())
    out = {r["key"]: 0.0 for r in rows}
    if total > 0:
        for k, v in raw.items():
            out[k] = round(min(cap, v / total), 4)
    return out
