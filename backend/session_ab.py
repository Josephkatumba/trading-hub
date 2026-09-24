"""Phase 9 A/B harness: LEGACY vs CORRECTED session time for the trendline scanner.

Pure and read-only. For one sample (an M15 window, its H1 window and the real
scan instant) it builds both session contexts (session_time.py), runs the
unchanged scanner.analyze_symbol with each, and reports which fields differ.

The scanner reads only `session` and `session_alignment` from the context, so
when both are equal the two scans are identical by construction; the scanner is
then run once. Entry, stop loss, take profit, direction and setup family do not
read session data; they are compared anyway.

Counterfactual outcomes (samples whose confirmation eligibility flips) are
market-path labels from the unchanged outcome engine on real, basis-normalized
bars. They are computed in memory for comparison and never persisted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from outcomes import DEFAULT_HORIZONS, resolve_due_market_outcomes
from scanner import analyze_symbol
from session_time import compute_session_context
from strategy_lab import classify_outcome

CONTEXT_FIELDS = ("london_high", "london_low", "london_range", "london_date", "london_complete", "session_alignment")
SCAN_FIELDS = ("session_score", "score", "state", "direction", "setup_family", "entry", "stop_loss", "take_profit",
               "invalidation_hint", "strategy_valid")


def _context_view(context: dict[str, Any]) -> dict[str, Any]:
    return {**context, "london_range": round(context["london_high"] - context["london_low"], 10)}


def _scan_view(scan: dict[str, Any]) -> dict[str, Any]:
    # trendline_gate / confirmation_alignment are context for explaining state results, not compared fields.
    return {"session_score": scan.get("score_breakdown", {}).get("session"), **{k: scan.get(k) for k in SCAN_FIELDS if k != "session_score"},
            "trendline_gate": scan.get("trendline_gate"), "confirmation_alignment": scan.get("confirmation_alignment")}


def run_pair(symbol: str, rows: Sequence[dict[str, Any]], higher_rows: Sequence[dict[str, Any]], now_utc: datetime,
             legacy_time: Callable, corrected_time: Callable, spread: float = 0.0) -> dict[str, Any]:
    price = float(rows[-1]["close"])
    legacy_ctx = compute_session_context(rows, price, now_utc, legacy_time)
    corrected_ctx = compute_session_context(rows, price, now_utc, corrected_time)
    legacy_scan = analyze_symbol(symbol, list(rows), spread=spread, session_context=legacy_ctx, higher_rows=list(higher_rows))
    scanner_inputs_equal = (legacy_ctx["session"], legacy_ctx["session_alignment"]) == (corrected_ctx["session"], corrected_ctx["session_alignment"])
    corrected_scan = legacy_scan if scanner_inputs_equal else analyze_symbol(
        symbol, list(rows), spread=spread, session_context=corrected_ctx, higher_rows=list(higher_rows))
    a_ctx, b_ctx = _context_view(legacy_ctx), _context_view(corrected_ctx)
    a_scan, b_scan = _scan_view(legacy_scan), _scan_view(corrected_scan)
    return {"symbol": symbol, "now": now_utc.isoformat(), "session": legacy_ctx["session"],
            "legacy": {"context": a_ctx, "scan": a_scan}, "corrected": {"context": b_ctx, "scan": b_scan},
            "context_changed": sorted(k for k in CONTEXT_FIELDS if a_ctx[k] != b_ctx[k]),
            "scan_changed": sorted(k for k in SCAN_FIELDS if a_scan[k] != b_scan[k]),
            "reason_changed": legacy_scan.get("reason") != corrected_scan.get("reason")}


def counterfactual_outcome(symbol: str, scan: dict[str, Any], observed: datetime, bars: list[dict[str, Any]],
                           now: datetime, horizons: tuple[str, ...] = DEFAULT_HORIZONS) -> tuple[str, str | None]:
    """Market-path label of a confirmed plan (entry/SL/TP) from `observed` on, via the unchanged engine."""
    stamp = observed.astimezone(timezone.utc).isoformat()
    oid = "ab-" + symbol + "-" + stamp
    snapshot = {"record_type": "setup_snapshot", "setup_id": oid, "observation_id": oid, "observed_at": stamp,
                "source_timestamp": stamp, "symbol": symbol, "direction": scan["direction"], "timeframe": "M15",
                "reference_price": scan["entry"], "proposed_entry": scan["entry"], "proposed_stop_loss": scan["stop_loss"],
                "proposed_take_profit": scan["take_profit"], "invalidation_price": scan["invalidation_hint"],
                "rule_evidence": {"strategy_valid": True},
                "time_provenance": {"timezone_normalization_status": "VERIFIED"},
                "data_quality": {"timestamp_quality": "VERIFIED", "flags": []}}
    confirmation = {"setup_id": oid, "observation_id": oid, "symbol": symbol, "confirmed_at": stamp}
    outcomes = resolve_due_market_outcomes([confirmation], {oid: snapshot}, {symbol: bars}, [], horizons, now=now)
    return classify_outcome(confirmation, outcomes, snapshot, horizons)
