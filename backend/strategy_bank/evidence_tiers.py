"""Evidence tiers: what a strategy's RECORDED evidence allows us to say about it.

A tier is computed from evidence, never from how many signals a strategy produces or from its
deployment status. Deployment (LINKED / EXPERIMENTAL / RESEARCH in strategy_bank.rules, lifecycle in
strategy_bank.qualification) says what the system does with a strategy; the tier says whether there is
any reason to believe it works.

  SUSPENDED     the historical record is significantly NEGATIVE after costs (95% CI of expectancy
                entirely below zero over all periods). Suspension of any alerting is RECOMMENDED; the
                change itself is an owner decision (nothing is switched off automatically).
  EXPERIMENTAL  no credible edge: too few trades, or expectancy <= 0 without being significantly negative.
  RESEARCH      promising but unproven: positive overall after costs, failing one or more validation tests.
  VALIDATED     passes every historical test below; still requires forward evidence before production.
  PRODUCTION    VALIDATED, plus a forward (live, recorded) record that meets the promotion gate of
                strategy_bank.qualification (>= 60 resolved, expectancy >= 0.05R, PF >= 1.10), plus
                deployment approval. A strategy never reaches PRODUCTION by generating signals alone.

Validation tests (historical, simulated with spread, commission, stop slippage and financing):
  sample          >= 100 trades over all periods and >= 30 in the untouched test period
  out-of-sample   expectancy > 0 in the development periods (train + validation) AND in the test period
  significance    lower bound of the all-period 95% bootstrap CI > 0, and Holm-adjusted p < 0.05 across
                  every strategy evaluated together (multiple-testing control)
  costs           expectancy > 0 with doubled costs
  walk-forward    expectancy > 0 in at least 2/3 of the rolling quarterly folds
"""
from __future__ import annotations

from typing import Any

TIERS = ("PRODUCTION", "VALIDATED", "RESEARCH", "EXPERIMENTAL", "SUSPENDED")
MIN_TRADES, MIN_TEST_TRADES = 100, 30
FOLD_SHARE = 2 / 3
ALPHA = 0.05
FORWARD = {"resolved": 60, "expectancy_r": 0.05, "profit_factor": 1.10}


def _e(block: dict[str, Any] | None) -> float | None:
    return None if not block else block.get("expectancy_r")


def checks(perf: dict[str, Any], holm_p: float | None = None) -> dict[str, dict[str, Any]]:
    """Each validation test with pass/fail and the measured value (None when not measurable)."""
    a = perf.get("all_periods") or {}
    dev, test = perf.get("development") or {}, perf.get("test") or {}
    ci = a.get("expectancy_ci95") or [None, None]
    folds = [f.get("expectancy_r") for f in (perf.get("walk_forward") or []) if f.get("trades")]
    pos = sum(1 for x in folds if x is not None and x > 0)
    x2 = _e(perf.get("all_periods_x2_costs"))
    return {
        "sample": {"pass": (a.get("trades") or 0) >= MIN_TRADES and (test.get("trades") or 0) >= MIN_TEST_TRADES,
                   "value": {"all": a.get("trades"), "test": test.get("trades")}},
        "out_of_sample": {"pass": (_e(dev) or 0) > 0 and (_e(test) or 0) > 0, "value": {"development": _e(dev), "test": _e(test)}},
        "significance": {"pass": ci[0] is not None and ci[0] > 0 and holm_p is not None and holm_p < ALPHA,
                         "value": {"ci95": ci, "holm_p": holm_p}},
        "costs": {"pass": x2 is not None and x2 > 0, "value": x2},
        "walk_forward": {"pass": bool(folds) and pos / len(folds) >= FOLD_SHARE, "value": {"positive": pos, "folds": len(folds)}},
    }


def forward_ok(forward: dict[str, Any] | None) -> bool:
    f = forward or {}
    return ((f.get("resolved") or 0) >= FORWARD["resolved"] and (f.get("expectancy_r") or -1) >= FORWARD["expectancy_r"]
            and (f.get("profit_factor") or 0) >= FORWARD["profit_factor"])


def classify(perf: dict[str, Any] | None, holm_p: float | None = None, forward: dict[str, Any] | None = None,
             deployment_approved: bool = False) -> dict[str, Any]:
    """{tier, verdict, checks, reasons}. `perf` is one strategy's historical evaluation."""
    if not perf or not (perf.get("all_periods") or {}).get("trades"):
        return {"tier": "EXPERIMENTAL", "verdict": "Not evaluated", "checks": {}, "reasons": ["no historical evaluation recorded"]}
    c = checks(perf, holm_p)
    a = perf["all_periods"]
    ci = a.get("expectancy_ci95") or [None, None]
    failed = [k for k, v in c.items() if not v["pass"]]
    if (a.get("trades") or 0) >= MIN_TRADES and ci[1] is not None and ci[1] < 0:
        return {"tier": "SUSPENDED", "verdict": "Significantly negative after costs: suspension recommended",
                "checks": c, "reasons": [f"all-period 95% CI {ci} lies below zero"]}
    if (a.get("trades") or 0) < MIN_TRADES:
        return {"tier": "EXPERIMENTAL", "verdict": "Insufficient sample", "checks": c, "reasons": [f"{a.get('trades')} trades < {MIN_TRADES}"]}
    if not failed:
        if forward_ok(forward) and deployment_approved:
            return {"tier": "PRODUCTION", "verdict": "Validated historically and forward", "checks": c, "reasons": []}
        return {"tier": "VALIDATED", "verdict": "Passed every historical test; forward evidence pending", "checks": c,
                "reasons": ["forward record below the promotion gate" if not forward_ok(forward) else "deployment approval pending"]}
    if (a.get("expectancy_r") or 0) > 0:
        return {"tier": "RESEARCH", "verdict": "Promising but unproven", "checks": c, "reasons": [f"failed: {', '.join(failed)}"]}
    return {"tier": "EXPERIMENTAL", "verdict": "No credible edge after costs", "checks": c, "reasons": [f"failed: {', '.join(failed)}"]}
