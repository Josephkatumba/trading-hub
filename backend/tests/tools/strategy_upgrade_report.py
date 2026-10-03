"""Developer tool: TradeDen Strategy Upgrade Phase 1 replay (read-only, deterministic).

Usage (from backend/, MT5 terminal running):  python tests/tools/strategy_upgrade_report.py OUT.json [DAYS]

Walks every M15 bar of the last DAYS (default 90) for every scanned instrument, with
exactly the bars the live collector would have had when that bar opened (stop_ab.market_at:
closed bars + a flat forming bar at the bar's open). Per bar it evaluates:
  S/R        sr-levels-v1 (before) and sr-levels-v2 (after: + candle confirmation)
  Trendline  trendline-first-v5 (before) and trendline-first-v5.1 (after: break + retest rejection)
  SMC        smc-confluence-v1 (new)
A confirmation (strategy_valid) opens a simulated setup unless the same model already has
one open in that direction (it would be the same live episode); it is resolved on the M15
path by stop_ab.resolve (TARGET / STOP / AMBIGUOUS / EXPIRED / OPEN; no costs). This is a
detection comparison, not a performance claim: nothing is tuned to the results.
Writes nothing except OUT.json.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import stop_ab  # noqa: E402
from strategies import smc, support_resistance as sr  # noqa: E402
from strategies.trendline import TrendlineV51Strategy, TrendlineV5Strategy  # noqa: E402

BASIS = "America/New_York+07:00"          # the verified MT5 time basis (.env), for the trendline session context
MODELS = ("sr_v1", "sr_v2", "tl_v5", "tl_v51", "smc")
HISTORY = {"M15": 400, "H1": 200, "H4": 220, "D1": 220}   # bars of warm-up before the replay window


def load(symbol: str, now: datetime, days: int):
    import MetaTrader5 as mt5
    import main
    broker = main.mt5_symbol(symbol)
    if not broker:
        return None
    start = now - timedelta(days=days)
    span = {"M15": timedelta(minutes=15), "H1": timedelta(hours=1), "H4": timedelta(hours=4), "D1": timedelta(days=1)}
    frames = {}
    for tf, warm in HISTORY.items():
        since = start - span[tf] * warm * 1.6          # weekends / closed hours
        rates = mt5.copy_rates_range(broker, getattr(mt5, "TIMEFRAME_" + tf), since, now)
        if rates is None or not len(rates):
            return None
        frames[tf] = [{"time": float(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                       "low": float(r["low"]), "close": float(r["close"])} for r in rates]
    return frames, start.timestamp()


def _brief(result: dict) -> dict:
    return {key: result.get(key) for key in ("state", "direction", "setup_family", "strategy_valid", "entry", "stop_loss",
                                             "take_profit", "rr", "score")}


def work(args):
    symbol, frames, start_time = args
    import bisect
    started = time.perf_counter()
    times = {tf: [float(bar["time"]) for bar in rows] for tf, rows in frames.items()}
    m15 = frames["M15"]
    # stop_ab.market_at's MT5 server times are fine here: the replay compares versions on identical inputs.
    first = max(stop_ab.WINDOW["M15"], bisect.bisect_left(times["M15"], start_time))
    tl5, tl51 = TrendlineV5Strategy(BASIS), TrendlineV51Strategy(BASIS)
    open_until: dict[tuple[str, str], int] = {}
    setups = {m: [] for m in MODELS}
    confirming = {m: 0 for m in MODELS}
    sr_rejected, sr_retained, tl_removed, tl_added, smc_examples = [], [], [], [], []
    for k in range(first, len(m15)):
        market = stop_ab.market_at(symbol, frames, times, k)
        out = {}
        out["sr_v1"] = sr.analyze_support_resistance(market, sr.LEGACY_VERSION)
        # v2 only adds a gate to v1's CONFIRMING branch: below CONFIRMING both versions agree.
        out["sr_v2"] = sr.analyze_support_resistance(market, sr.STRATEGY_VERSION) if out["sr_v1"]["state"] == "CONFIRMING" else out["sr_v1"]
        out["tl_v5"] = tl5.evaluate(market)
        out["tl_v51"] = tl51.evaluate(market)
        out["smc"] = smc.analyze_smc(market)
        when = datetime.fromtimestamp(m15[k]["time"], timezone.utc).strftime("%Y-%m-%d %H:%M")   # MT5 server time
        for model, result in out.items():
            if result["state"] == "CONFIRMING":
                confirming[model] += 1
            if not result["strategy_valid"]:
                continue
            key = (model, result["direction"])
            if open_until.get(key, -1) >= k:
                continue
            outcome = stop_ab.resolve(result["direction"], result["entry"], result["stop_loss"], result["take_profit"], m15[k:])
            open_until[key] = k + outcome["bars"] - 1
            setups[model].append({"symbol": symbol, "k": k, "time": when, "direction": result["direction"],
                                  "family": result.get("setup_family"), "rr": result["rr"], **outcome})
        v1, v2 = out["sr_v1"], out["sr_v2"]
        if v1["strategy_valid"]:
            candle = (v2.get("strategy_evidence") or {}).get("candle_confirmation") or {}
            row = {"symbol": symbol, "time": when, "direction": v1["direction"], "family": v1["setup_family"],
                   "level": ((v1.get("strategy_evidence") or {}).get("level") or {}).get("price"),
                   "close_position": ((v1.get("strategy_evidence") or {}).get("rejection") or {}).get("close_position"),
                   "touch_bars_ago": ((v1.get("strategy_evidence") or {}).get("touch") or {}).get("bars_ago"),
                   "patterns": candle.get("patterns"), "pattern": candle.get("pattern")}
            (sr_retained if v2["strategy_valid"] else sr_rejected).append(row)
        a, b = out["tl_v5"], out["tl_v51"]
        if a["strategy_valid"] != b["strategy_valid"]:
            retest = b.get("trendline_retest") or {}
            row = {"symbol": symbol, "time": when, "v5": _brief(a), "v51": _brief(b), "v51_label": b.get("trendline"),
                   "retest": {key: retest.get(key) for key in ("bars_since_break", "retested", "failed", "confirmed", "pattern")}}
            (tl_removed if a["strategy_valid"] else tl_added).append(row)
        if out["smc"]["strategy_valid"]:
            ev = out["smc"]["strategy_evidence"]
            smc_examples.append({"symbol": symbol, "time": when, **_brief(out["smc"]),
                                 "htf": ev["htf"], "structure": ev["structure"]["last_break"],
                                 "fvgs": ev["displacement"]["fvgs"], "order_block": ev["order_block"],
                                 "liquidity_sweep": ev["liquidity_sweep"], "poi": ev["poi"],
                                 "candle": ev["candle_confirmation"], "plan": ev["plan"]})
    return {"symbol": symbol, "bars": len(m15) - first, "seconds": round(time.perf_counter() - started, 1),
            "setups": setups, "confirming": confirming, "sr_rejected": sr_rejected, "sr_retained": sr_retained,
            "tl_removed": tl_removed, "tl_added": tl_added, "smc_examples": smc_examples}


def summary(setups: list[dict]) -> dict:
    outcomes = {name: sum(1 for s in setups if s["outcome"] == name) for name in ("TARGET", "STOP", "AMBIGUOUS", "EXPIRED", "OPEN")}
    decided = outcomes["TARGET"] + outcomes["STOP"]
    return {"setups": len(setups), "outcomes": outcomes,
            "target_share_of_decided": round(outcomes["TARGET"] / decided, 3) if decided else None}


def main_report(out: Path, days: int) -> None:
    import MetaTrader5 as mt5
    import main
    if not mt5.initialize():
        raise SystemExit("MT5 not available")
    now = datetime.now(timezone.utc)
    jobs = []
    for symbol in main.configured_watchlist():
        loaded = load(symbol, now, days)
        if loaded:
            jobs.append((symbol, *loaded))
        else:
            print("no history:", symbol)
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(work, jobs))
    total = {m: [s for r in results for s in r["setups"][m]] for m in MODELS}
    report = {"generated_at": now.isoformat(), "days": days, "symbols": [r["symbol"] for r in results],
              "bars": {r["symbol"]: r["bars"] for r in results},
              "summary": {m: summary(total[m]) for m in MODELS},
              "confirming_bars": {m: sum(r["confirming"][m] for r in results) for m in MODELS},
              "by_symbol": {r["symbol"]: {m: len(r["setups"][m]) for m in MODELS} for r in results},
              "sr": {"v1_valid_bars": sum(len(r["sr_rejected"]) + len(r["sr_retained"]) for r in results),
                     "rejected_bars": sum(len(r["sr_rejected"]) for r in results),
                     "retained_bars": sum(len(r["sr_retained"]) for r in results),
                     "retained_patterns": {p: sum(1 for r in results for x in r["sr_retained"] if x["pattern"] == p)
                                           for p in ("wick_rejection", "engulfing", "close_away")},
                     "rejected_examples": [x for r in results for x in r["sr_rejected"]][:40],
                     "retained_examples": [x for r in results for x in r["sr_retained"]][:40]},
              "trendline": {"removed_bars": sum(len(r["tl_removed"]) for r in results),
                            "added_bars": sum(len(r["tl_added"]) for r in results),
                            "removed_examples": [x for r in results for x in r["tl_removed"]][:40],
                            "added_examples": [x for r in results for x in r["tl_added"]][:40]},
              "smc_examples": [x for r in results for x in r["smc_examples"]],
              "setups": total}
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("summary", "confirming_bars", "by_symbol")}, indent=1))
    print("sr:", {k: report["sr"][k] for k in ("v1_valid_bars", "rejected_bars", "retained_bars", "retained_patterns")})
    print("trendline:", {k: report["trendline"][k] for k in ("removed_bars", "added_bars")})


if __name__ == "__main__":
    main_report(Path(sys.argv[1] if len(sys.argv) > 1 else "strategy_upgrade.json"), int(sys.argv[2]) if len(sys.argv) > 2 else 90)
