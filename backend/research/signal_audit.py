"""Read-only audit of every recorded live signal: production confirmations and strategy-bank signals.

Answers "why are signals losing" from the stores the engine actually wrote, without changing them:
  - lifecycle funnel (detected -> confirmed -> resolved), expiry / invalidation rates
  - outcome breakdowns by strategy, instrument, session, direction, score bucket, planned R:R,
    higher-timeframe agreement (production score breakdown) and contradiction count (bank)
  - duplicate pressure: how many bank opportunities were confirmed by several strategies at once
  - outcome-record hygiene (unavailable / pending / revisions)

R values are the recorded hypothetical outcomes (TP = planned R, SL = -1R, time exits as recorded);
they are signal outcomes, not executed trades, and carry no costs beyond the executable entry quote.

    python -m research.signal_audit            # writes data/research/quality/live_audit.json
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from research.metrics import max_drawdown
from storage_config import data_directory

TARGET_SYMBOLS = ("XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "US500", "GER40")
RESOLVED = {"TARGET_HIT", "STOP_HIT", "TIME_EXIT"}


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def session_of(stamp: str | float | datetime) -> str:
    """UTC trading session of an instant (fixed UTC hours; no DST adjustment)."""
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    hour = stamp.hour if isinstance(stamp, datetime) else datetime.fromtimestamp(stamp, timezone.utc).hour
    if hour < 7:
        return "ASIA"
    if hour < 12:
        return "LONDON"
    if hour < 16:
        return "LONDON_NY_OVERLAP"
    if hour < 21:
        return "NEW_YORK"
    return "LATE_US"


def outcome_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Win rate, average win/loss, expectancy, profit factor and drawdown of resolved signal rows (chronological)."""
    resolved = sorted((r for r in rows if r.get("r") is not None), key=lambda r: r["t"])
    rs = [r["r"] for r in resolved]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    n = len(rs)
    gross_loss = -sum(losses)
    return {
        "signals": len(rows), "resolved": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
        "expectancy_r": round(sum(rs) / n, 4) if n else None,
        "profit_factor": round(sum(wins) / gross_loss, 3) if gross_loss else None,
        "total_r": round(sum(rs), 2), "max_drawdown_r": max_drawdown(rs),
        "breakeven_win_rate": round(1 / (1 + (sum(wins) / len(wins))), 4) if wins else None,
        "sufficient": n >= 30,
    }


def breakdown(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[str(key(r))].append(r)
    out = {k: outcome_stats(v) for k, v in groups.items()}
    return dict(sorted(out.items(), key=lambda kv: -(kv[1]["resolved"])))


def _bucket(value: float | None, edges: tuple[float, ...]) -> str:
    if value is None:
        return "unknown"
    for lo, hi in zip(edges, edges[1:]):
        if lo <= value < hi:
            return f"{lo:g}-{hi:g}"
    return f">={edges[-1]:g}" if value >= edges[-1] else f"<{edges[0]:g}"


# ----- production (scanner) confirmations -------------------------------------------------------

def production_rows(folder: Path) -> list[dict[str, Any]]:
    confirmations = {r["confirmation_event_id"]: r for r in _rows(folder / "setup_confirmations.jsonl")}
    latest: dict[str, dict[str, Any]] = {}
    for r in _rows(folder / "signal_outcomes.jsonl"):
        key = r.get("confirmation_event_id")
        if key and (key not in latest or r.get("revision", 0) >= latest[key].get("revision", 0)):
            latest[key] = r
    rows = []
    for key, o in latest.items():
        c = confirmations.get(key, {})
        breakdown_ = c.get("score_breakdown") or {}
        entry, sl, tp = o.get("entry"), o.get("stop_loss"), o.get("take_profit")
        planned = abs(tp - entry) / abs(entry - sl) if None not in (entry, sl, tp) and entry != sl else None
        status = o.get("status")
        rows.append({
            "t": o.get("confirmed_at") or "", "source": "production", "strategy": o.get("strategy_id"),
            "version": o.get("strategy_version"), "symbol": o.get("symbol"), "direction": o.get("direction"),
            "score": o.get("score"), "setup_type": c.get("setup_type"), "status": status,
            "r": o.get("r_multiple") if status in RESOLVED else None, "planned_rr": planned,
            "htf_points": breakdown_.get("higher_timeframe"), "momentum_points": breakdown_.get("momentum"),
            "shadow": bool(o.get("shadow")), "revision": o.get("revision", 1),
        })
    return rows


def lifecycle_funnel(folder: Path) -> dict[str, Any]:
    final: dict[str, str] = {}
    reached: dict[str, set] = defaultdict(set)
    reasons: Counter = Counter()
    for r in _rows(folder / "setup_lifecycle.jsonl"):
        sid = r.get("setup_id")
        final[sid] = r.get("to_state")
        reached[sid].add(r.get("to_state"))
        if r.get("to_state") in ("EXPIRED", "INVALIDATED"):
            reasons[f"{r.get('to_state')}:{r.get('reason_code')}"] += 1
    setups = len(final)
    states = Counter(final.values())
    ever = Counter(s for v in reached.values() for s in v)
    return {
        "setups": setups, "final_state": dict(states), "ever_reached": dict(ever),
        "confirm_rate": round(ever.get("ACTIVE", 0) / setups, 4) if setups else None,
        "expired_share": round(states.get("EXPIRED", 0) / setups, 4) if setups else None,
        "invalidated_share": round(states.get("INVALIDATED", 0) / setups, 4) if setups else None,
        "top_close_reasons": dict(reasons.most_common(12)),
    }


# ----- strategy-bank signals ---------------------------------------------------------------------

def bank_rows(folder: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for r in _rows(folder / "strategy_bank" / "signals.jsonl"):
        sid = r.get("signal_id")
        if sid:
            latest[sid] = {**latest.get(sid, {}), **r}
    rows = []
    for r in latest.values():
        status = r.get("outcome_status")
        rows.append({
            "t": r.get("confirmed_at") or "", "source": "bank", "strategy": r.get("strategy_key"),
            "symbol": r.get("symbol"), "direction": r.get("direction"), "timeframe": r.get("timeframe"),
            "status": status, "r": r.get("r_multiple") if status in RESOLVED else None,
            "planned_rr": r.get("rr"), "contradictions": len(r.get("contradictions") or []),
            "alert": r.get("alert"), "opportunity_id": r.get("opportunity_id"),
            "spread_risk": (r.get("spread") or 0) / r["risk"] if r.get("risk") else None,
        })
    return rows


def opportunity_overlap(folder: Path, bank: list[dict[str, Any]]) -> dict[str, Any]:
    by_opp: dict[str, list] = defaultdict(list)
    for r in bank:
        if r.get("opportunity_id"):
            by_opp[r["opportunity_id"]].append(r)
    sizes = Counter(min(len(v), 4) for v in by_opp.values())
    multi = [r for v in by_opp.values() if len(v) > 1 for r in v]
    single = [r for v in by_opp.values() if len(v) == 1 for r in v]
    return {"opportunities": len(by_opp), "strategies_per_opportunity": {f"{k}{'+' if k == 4 else ''}": v for k, v in sorted(sizes.items())},
            "signals_in_shared_opportunities": len(multi),
            "shared_opportunity_outcomes": outcome_stats(multi), "single_strategy_outcomes": outcome_stats(single)}


def audit(folder: Path | None = None) -> dict[str, Any]:
    folder = folder or data_directory()
    prod = production_rows(folder)
    bank = bank_rows(folder)
    prod_live = [r for r in prod if not r["shadow"]]
    every = prod_live + bank
    target = [r for r in every if r["symbol"] in TARGET_SYMBOLS]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": "LIVE SIGNAL RECORDS (hypothetical outcomes, not executed trades)",
        "window": {"first": min((r["t"] for r in every if r["t"]), default=None),
                   "last": max((r["t"] for r in every if r["t"]), default=None)},
        "lifecycle": lifecycle_funnel(folder),
        "record_hygiene": {
            "production_status": dict(Counter(r["status"] for r in prod)),
            "production_revised": sum(1 for r in prod if r["revision"] > 1),
            "bank_status": dict(Counter(r["status"] for r in bank)),
        },
        "overall": {"production": outcome_stats(prod_live), "bank": outcome_stats(bank), "all": outcome_stats(every),
                    "target_instruments": outcome_stats(target)},
        "production": {
            "by_strategy": breakdown(prod_live, lambda r: r["strategy"]),
            "by_version": breakdown(prod_live, lambda r: r["version"]),
            "by_symbol": breakdown(prod_live, lambda r: r["symbol"]),
            "by_session": breakdown(prod_live, lambda r: session_of(r["t"])),
            "by_setup_type": breakdown(prod_live, lambda r: f"{r['strategy']}:{r['setup_type']}"),
            "by_score": breakdown(prod_live, lambda r: _bucket(r["score"], (0, 70, 80, 90, 101))),
            "by_planned_rr": breakdown(prod_live, lambda r: _bucket(r["planned_rr"], (0, 1.5, 2, 3, 5))),
            "by_htf_points": breakdown(prod_live, lambda r: r["htf_points"]),
            "by_momentum_points": breakdown(prod_live, lambda r: r["momentum_points"]),
            "by_direction": breakdown(prod_live, lambda r: r["direction"]),
        },
        "bank": {
            "by_strategy": breakdown(bank, lambda r: r["strategy"]),
            "by_symbol": breakdown(bank, lambda r: r["symbol"]),
            "by_session": breakdown(bank, lambda r: session_of(r["t"])),
            "by_contradictions": breakdown(bank, lambda r: min(r["contradictions"], 3)),
            "by_alert": breakdown(bank, lambda r: r["alert"]),
            "by_spread_share_of_risk": breakdown(bank, lambda r: _bucket(r["spread_risk"], (0, 0.05, 0.1, 0.25))),
            "by_direction": breakdown(bank, lambda r: r["direction"]),
            "overlap": opportunity_overlap(folder, bank),
        },
        "target_instruments": {
            "by_symbol": breakdown(target, lambda r: r["symbol"]),
            "by_symbol_strategy": breakdown(target, lambda r: f"{r['symbol']}:{r['strategy']}"),
        },
    }


def main() -> None:
    result = audit()
    out = data_directory() / "research" / "quality" / "live_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    o = result["overall"]
    for k, v in o.items():
        print(f"{k:20} resolved={v['resolved']} WR={v['win_rate']} E={v['expectancy_r']} PF={v['profit_factor']} total={v['total_r']}")
    print(f"written {out}")


if __name__ == "__main__":
    main()
