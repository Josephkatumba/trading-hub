"""Product-facing strategy evidence tiers, derived only from recorded evidence.

The qualification registry (``strategy_bank.qualification``) tracks the operational lifecycle
(DISCOVERED ... QUALIFIED / APPROVED_EXPERIMENTAL / PRODUCTION / ARCHIVED). Its ``PRODUCTION``
status means "an original strategy that signals live"; it is NOT a claim of a proven edge.
Customers need a separate, honest answer to "has this strategy been shown to work?":

    EXPERIMENTAL  default. Any strategy without recorded forward evidence meeting the criteria,
                  including live-signalling ones (legacy PRODUCTION, APPROVED_EXPERIMENTAL).
    VALIDATED     recorded forward (never backtest) outcomes meet the qualification criteria
                  (>= MIN_FORWARD_SIGNALS resolved, expectancy >= MIN_EXPECTANCY_R, profit factor
                  >= MIN_PROFIT_FACTOR) AND the one-sided lower confidence bound of expectancy is
                  above zero after a Bonferroni correction for every strategy with forward evidence
                  (ALPHA / number tested). Clearing the alert thresholds by noise is not validation.
    PRODUCTION    VALIDATED *and* an explicit approval reference recorded on a QUALIFIED transition.
    ARCHIVED      ARCHIVED or UNSUPPORTED in the registry; results are kept.

The tier can only go up on evidence; a label or status alone never makes a strategy VALIDATED.
This module never writes to the registry.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Iterable

EXPERIMENTAL, VALIDATED, PRODUCTION, ARCHIVED = "EXPERIMENTAL", "VALIDATED", "PRODUCTION", "ARCHIVED"
TIERS = (EXPERIMENTAL, VALIDATED, PRODUCTION, ARCHIVED)

# Kept equal to strategy_bank.qualification (asserted in tests) without importing it at module load.
MIN_FORWARD_SIGNALS, MIN_EXPECTANCY_R, MIN_PROFIT_FACTOR = 60, 0.05, 1.10
ALPHA = 0.05            # family-wise, one-sided

_REJECTED = {"ARCHIVED", "UNSUPPORTED"}


def lower_bound(evidence: dict[str, Any], tested: int) -> float | None:
    """One-sided Bonferroni-corrected lower confidence bound of expectancy (normal approximation)."""
    n, mean, sd = evidence.get("resolved") or 0, evidence.get("expectancy_r"), evidence.get("r_std")
    if n < 2 or mean is None or sd is None or not math.isfinite(sd):
        return None
    z = NormalDist().inv_cdf(1 - ALPHA / max(1, tested))
    return round(mean - z * sd / math.sqrt(n), 4)


def meets_criteria(evidence: dict[str, Any] | None, tested: int = 1) -> tuple[bool, list[str]]:
    """Whether recorded forward statistics meet the validation bar, with the reasons they do not."""
    if not evidence:
        return False, ["no recorded forward evidence"]
    reasons = []
    resolved = evidence.get("resolved") or 0
    exp, pf = evidence.get("expectancy_r"), evidence.get("profit_factor")
    if resolved < MIN_FORWARD_SIGNALS:
        reasons.append(f"{resolved} resolved forward signals (needs >= {MIN_FORWARD_SIGNALS})")
    if exp is None or exp < MIN_EXPECTANCY_R:
        reasons.append(f"expectancy {exp if exp is not None else 'n/a'}R (needs >= {MIN_EXPECTANCY_R}R)")
    if pf is None or pf < MIN_PROFIT_FACTOR:
        reasons.append(f"profit factor {pf if pf is not None else 'n/a'} (needs >= {MIN_PROFIT_FACTOR})")
    bound = lower_bound(evidence, tested)
    if bound is None or bound <= 0:
        reasons.append(f"expectancy not distinguishable from zero: corrected lower bound "
                       f"{bound if bound is not None else 'n/a'}R across {max(1, tested)} strategies tested")
    return not reasons, reasons


def classify(status: str | None, evidence: dict[str, Any] | None = None,
             approval: str | None = None, tested: int = 1) -> dict[str, Any]:
    """Evidence tier for one strategy from its registry status, recorded forward evidence and approval."""
    if status in _REJECTED:
        return {"tier": ARCHIVED, "reasons": [f"registry status {status}"]}
    ok, reasons = meets_criteria(evidence, tested)
    if not ok:
        if status == "PRODUCTION":
            reasons = ["registry label PRODUCTION means live signalling, not a validated edge", *reasons]
        return {"tier": EXPERIMENTAL, "reasons": reasons}
    if status == "QUALIFIED" and approval and str(approval).strip():
        return {"tier": PRODUCTION, "reasons": ["forward criteria met", "approval recorded"]}
    return {"tier": VALIDATED, "reasons": ["forward criteria met", "no production approval recorded"]}


def catalogue(rows: Iterable[dict[str, Any]], evidence_for) -> list[dict[str, Any]]:
    """Classify registry rows (latest transition per key). ``evidence_for(key)`` returns forward stats."""
    latest: dict[str, dict[str, Any]] = {}
    approvals: dict[str, str] = {}
    for row in rows:
        latest[row["key"]] = row
        if row.get("to") == "QUALIFIED" and row.get("approval"):
            approvals[row["key"]] = row["approval"]
    found = {key: (None if row.get("to") in _REJECTED else evidence_for(key)) for key, row in latest.items()}
    # Every strategy that produced resolved forward outcomes counts as a test, archived ones included.
    tested = sum(1 for key in latest if (found[key] or evidence_for(key) or {}).get("resolved"))
    out = []
    for key, row in sorted(latest.items()):
        status, evidence = row.get("to"), found[key]
        result = classify(status, evidence, approvals.get(key), tested)
        out.append({"key": key, "name": row.get("name") or key, "source": row.get("source"),
                    "registry_status": status, "status_since": row.get("at"), "evidence": evidence, **result})
    return out


def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {tier: 0 for tier in TIERS}
    for item in items:
        counts[item["tier"]] += 1
    return {"counts": counts, "total": len(items),
            "criteria": {"min_forward_signals": MIN_FORWARD_SIGNALS, "min_expectancy_r": MIN_EXPECTANCY_R,
                         "min_profit_factor": MIN_PROFIT_FACTOR, "family_alpha": ALPHA,
                         "significance": "Bonferroni-corrected one-sided lower bound of expectancy > 0",
                         "basis": "recorded forward outcomes only"},
            "statement": ("No strategy has demonstrated a validated edge." if not counts[VALIDATED] + counts[PRODUCTION]
                          else f"{counts[VALIDATED] + counts[PRODUCTION]} strategies meet the forward criteria.")}


RESOLVED = ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")


def forward_stats(signals: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-strategy forward statistics; same formula as ``qualification.forward_evidence`` but one pass."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for s in signals:
        grouped.setdefault(s.get("strategy_key"), []).append(s)
    out = {}
    for key, rows in grouped.items():
        resolved = [float(s.get("r_multiple") or 0) for s in rows if s.get("outcome_status") in RESOLVED]
        gains, losses = sum(r for r in resolved if r > 0), -sum(r for r in resolved if r < 0)
        mean = sum(resolved) / len(resolved) if resolved else None
        sd = (math.sqrt(sum((r - mean) ** 2 for r in resolved) / (len(resolved) - 1)) if len(resolved) > 1 else None)
        out[key] = {"signals": len(rows), "resolved": len(resolved),
                    "expectancy_r": round(mean, 4) if mean is not None else None,
                    "profit_factor": round(gains / losses, 3) if losses else None,
                    "r_std": round(sd, 4) if sd is not None else None}
    return out


def live_catalogue() -> dict[str, Any]:
    """Read the real qualification registry and bank store once (read-only)."""
    from strategy_bank import engine, qualification
    stats = forward_stats(engine.BankStore().signals.values())
    empty = {"signals": 0, "resolved": 0, "expectancy_r": None, "profit_factor": None, "r_std": None}
    items = catalogue(qualification.history(), lambda key: stats.get(key, empty))
    return {**summary(items), "strategies": items}
