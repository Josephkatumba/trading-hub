"""Read-only intelligence endpoints: strategy evidence, ICT market context and strategy confluence.

  GET /api/intelligence/strategies        historical evaluation (intel.json) + live forward record + evidence tier
  GET /api/intelligence/market?symbol=X   ICT context and stage reports for one instrument + confluence
  GET /api/intelligence/overview          compact ICT stages and confluence for every watched instrument
  GET /api/intelligence/participation     strategy participation, funnel, regime, diversification and allocation
                                          report (research.participation -> participation.json; ?label=before)

Nothing here scans for signals, records anything, alerts or trades. Market context is computed from
CLOSED MT5 bars (the forming bar is dropped) fetched under the scanner lock; if MT5 is unavailable
the endpoints say so (503) instead of guessing.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
LOGGER = logging.getLogger("trading_hub.intelligence")
COUNTS = {"M15": 400, "H1": 400, "H4": 300}
_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()
TTL = 60.0


def _intel() -> dict[str, Any] | None:
    from strategy_bank import engine
    path = engine.bank_dir() / "intel.json"
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    hit = _CACHE.get("intel")
    if hit and hit[0] == mtime:
        return hit[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _CACHE["intel"] = (mtime, data)
    return data


def tier_map() -> dict[str, str]:
    data = _intel() or {}
    return {k: (v.get("evidence") or {}).get("tier") for k, v in (data.get("strategies") or {}).items()}


def _forward(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rs = [float(r.get("r_multiple") or 0) for r in rows if r.get("outcome_status") in ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")]
    gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); dd = max(dd, peak - eq)
    return {"signals": len(rows), "resolved": len(rs), "open": sum(1 for r in rows if r.get("outcome_status") in (None, "PENDING")),
            "wins": sum(1 for r in rs if r > 0), "losses": sum(1 for r in rs if r <= 0),
            "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4) if rs else None,
            "expectancy_r": round(sum(rs) / len(rs), 4) if rs else None, "total_r": round(sum(rs), 2) if rs else None,
            "profit_factor": round(gains / losses, 3) if losses else None, "max_drawdown_r": round(dd, 2) if rs else None}


@router.get("/api/intelligence/participation")
def participation(label: str = Query("", max_length=32, pattern=r"^[a-z0-9_-]*$")):
    """The latest strategy participation report (or a frozen copy, e.g. label=before). Read-only."""
    from strategy_bank import engine
    path = engine.bank_dir() / (f"participation_{label}.json" if label else "participation.json")
    if not path.exists():
        return {"available": False, "reason": "No participation report recorded yet. Run: python -m research.participation"}
    key = f"participation:{label}"
    mtime = path.stat().st_mtime
    hit = _CACHE.get(key)
    if not hit or hit[0] != mtime:
        hit = (mtime, json.loads(path.read_text(encoding="utf-8")))
        _CACHE[key] = hit
    frozen = sorted(p.stem.removeprefix("participation_") for p in engine.bank_dir().glob("participation_*.json"))
    return {"available": True, **hit[1], "frozen_reports": frozen}


@router.get("/api/intelligence/strategies")
def strategies():
    """Every strategy with its deployment status, historical evaluation, live forward record and evidence tier."""
    from strategy_bank import engine, evidence_tiers, qualification, rules
    rules.load_expansion()
    data = _intel()
    store = engine.BankStore()
    by_key: dict[str, list] = {}
    for s in store.signals.values():
        by_key.setdefault(s["strategy_key"], []).append(s)
    try:
        linked = engine.linked_production_rows()
    except Exception:
        LOGGER.exception("linked production rows unavailable")
        linked = {}
    hist = (data or {}).get("strategies") or {}
    rows = []
    for spec in rules.SPECS:
        h = hist.get(spec["key"]) or {}
        fwd = _forward(linked.get(spec["key"], []) if spec["status"] == rules.LINKED else by_key.get(spec["key"], []))
        q = qualification.current_status(spec["key"])
        ev = evidence_tiers.classify(h.get("performance"), h.get("holm_p"), fwd, deployment_approved=q in qualification.SIGNALLING)
        rows.append({"key": spec["key"], "n": spec.get("n"), "name": spec["name"], "deployment": spec["status"],
                     "alerting": rules.alerting(spec), "qualification": q, "timeframe": spec["timeframe"],
                     "family": spec.get("family") or ("PRODUCTION-LINKED" if spec["status"] == rules.LINKED else "T-034 BANK"),
                     "group": spec.get("group"), "evidence_family": __import__("confluence").family_of(spec["key"]),
                     "replaces": spec.get("replaces"), "hypothesis": spec.get("hypothesis"), "version": spec.get("version"),
                     "instruments": list(spec["instruments"]),
                     "rules": {k: spec.get(k) for k in ("entry", "confirmation", "stop", "take_profit", "invalidation", "min_rr", "indicators")},
                     "unsupported_reason": spec.get("unsupported_reason"),
                     "historical": h.get("performance"), "technical": h.get("technical"), "holm_p": h.get("holm_p"),
                     "forward": fwd, "evidence": ev,
                     "suspension_recommended": ev["tier"] == "SUSPENDED" and rules.alerting(spec)})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["evidence"]["tier"]] = counts.get(r["evidence"]["tier"], 0) + 1
    return {"generated_at": (data or {}).get("generated_at"), "label": (data or {}).get("label"),
            "periods": (data or {}).get("periods"), "development": (data or {}).get("development"), "folds": (data or {}).get("folds"),
            "costs": (data or {}).get("costs"), "protocol": (data or {}).get("protocol"), "tiers": list(evidence_tiers.TIERS),
            "tier_rules": evidence_tiers.__doc__, "counts": counts, "strategies": rows,
            "available": data is not None,
            "notes": ["Historical results are simulations with modelled costs; forward results are hypothetical signal outcomes.",
                      "A tier is computed from evidence only. SUSPENDED is a recommendation; nothing is switched off automatically."]}


# ----- live market context ----------------------------------------------------------------------------------

def _frames(symbol: str) -> dict[str, list]:
    import main
    from research.history import basis
    from strategy_bank import worker
    if symbol not in main.WATCHLIST:
        raise HTTPException(422, "Unknown instrument")
    with main._SCAN_LOCK:
        connected, _ = main.ensure_mt5()
        if not connected:
            raise HTTPException(503, "Market feed unavailable")
        broker = main.resolve_mt5_symbol(symbol)
        info = main.mt5.symbol_info(broker) if broker else None
        if not broker or info is None:
            raise HTTPException(503, "Instrument unavailable")
        frames = {}
        for tf, n in COUNTS.items():
            bars = worker.closed_bars(main.mt5, broker, tf, n, basis(), float(info.point))
            if not bars:
                raise HTTPException(503, f"{tf} history unavailable or time basis unverified")
            frames[tf] = bars
    return frames


def _market_row(symbol: str) -> dict[str, Any] | None:
    import main
    markets, _, _ = main.latest_scan()
    return next((m for m in markets or [] if m.get("symbol") == symbol), None)


def _bank_open(symbol: str) -> list[dict[str, Any]]:
    from strategy_bank import engine
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    out = []
    for s in engine.BankStore().signals.values():
        try:
            recent = datetime.fromisoformat(str(s.get("confirmed_at"))) >= cutoff
        except ValueError:
            recent = False
        if s.get("symbol") == symbol and recent and s.get("outcome_status") in (None, "PENDING") and s.get("alert") != "no trade (quality gate)":
            out.append(s)
    return out


def market_context(symbol: str) -> dict[str, Any]:
    import confluence
    from strategy_bank import ict, rules
    key = "mkt:" + symbol
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    ctx = rules.Ctx(symbol, _frames(symbol))
    snap = ict.snapshot(ctx)
    tiers = tier_map()
    for s in snap["setups"]:
        s["tier"] = tiers.get(s["key"])
    market = _market_row(symbol)
    items = confluence.contributors(market, snap["setups"], _bank_open(symbol), tiers)
    result = {"symbol": symbol, "ict": snap, "confluence": confluence.assess(symbol, items, snap["bias"]),
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "mode": "research (shadow): ICT setups are recorded and measured, never alerted or traded"}
    with _LOCK:
        _CACHE[key] = (time.time(), result)
    return result


@router.get("/api/intelligence/market")
def market(symbol: str = Query("XAUUSD", max_length=32)):
    return market_context(symbol)


@router.get("/api/intelligence/overview")
def overview():
    """Compact per-instrument intelligence for the Market Radar (cached for a minute per instrument)."""
    import main
    rows, errors = [], {}
    for symbol in main.WATCHLIST:
        try:
            m = market_context(symbol)
        except HTTPException as exc:
            errors[symbol] = exc.detail
            continue
        except Exception as exc:                       # one instrument failing never hides the others
            LOGGER.exception("intelligence overview failed for %s", symbol)
            errors[symbol] = type(exc).__name__
            continue
        snap = m["ict"]
        rows.append({"symbol": symbol, "bias": snap["bias"], "structure": snap["structure"], "kill_zone": snap["kill_zone"],
                     "ny_time": snap["ny_time"], "dealing_zone": (snap.get("dealing_range") or {}).get("zone"),
                     "dealing_position": (snap.get("dealing_range") or {}).get("position"),
                     "setups": [{k: s.get(k) for k in ("key", "name", "stage", "direction", "missing", "tier", "blocked")}
                                for s in snap["setups"] if s["stage"] != "NONE"],
                     "nearest_liquidity": sorted([p for p in snap["liquidity"] if not p["swept"] and p["distance_atr"] is not None],
                                                 key=lambda p: abs(p["distance_atr"]))[:3],
                     "confluence": {k: m["confluence"][k] for k in ("direction", "classification", "independent_families", "opposing_families",
                                                                    "entry_confirmed", "explanation", "caveat")}})
    return {"markets": rows, "errors": errors, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "basis": "Closed MT5 bars; ICT stages are research (shadow) only."}
