"""Developer tool: Phase 11 Trend / Momentum stop-model A/B replay (read-only).

Usage (from backend/, MT5 terminal running):  python tests/tools/tm_stop_ab_report.py OUT.json

Reads MT5 history for every scanned instrument; writes nothing except OUT.json.
A = tm-pullback-v1, B = tm-pullback-v2. See stop_ab.py for the replay rules.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import stop_ab  # noqa: E402

START = datetime(2025, 9, 1, tzinfo=timezone.utc)
FROM = {"M15": datetime(2025, 8, 1, tzinfo=timezone.utc), "H1": datetime(2025, 6, 1, tzinfo=timezone.utc),
        "H4": datetime(2025, 3, 1, tzinfo=timezone.utc), "D1": datetime(2024, 8, 1, tzinfo=timezone.utc)}


def load(symbol: str, now: datetime):
    import MetaTrader5 as mt5
    import main
    broker = main.mt5_symbol(symbol)
    if not broker:
        return None
    frames = {}
    for tf, since in FROM.items():
        rates = mt5.copy_rates_range(broker, getattr(mt5, "TIMEFRAME_" + tf), since, now)
        if rates is None or not len(rates):
            return None
        frames[tf] = [{"time": float(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                       "low": float(r["low"]), "close": float(r["close"])} for r in rates]
    return frames


def work(args):
    symbol, frames = args
    started = time.perf_counter()
    result = stop_ab.replay_symbol(symbol, frames, START.timestamp())
    result["seconds"] = round(time.perf_counter() - started, 1)
    result["m15_bars"] = len(frames["M15"])
    result["first_bar"], result["last_bar"] = frames["M15"][0]["time"], frames["M15"][-1]["time"]
    return result


def main_report(out: Path) -> None:
    import MetaTrader5 as mt5
    import main
    if not mt5.initialize():
        raise SystemExit("MT5 not available")
    now = datetime.now(timezone.utc)
    jobs = []
    for symbol in main.configured_watchlist():
        frames = load(symbol, now)
        if frames:
            jobs.append((symbol, frames))
        else:
            print("no history:", symbol)
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(work, jobs))
    a_model, b_model = stop_ab.MODELS
    all_setups = {m: [s for r in results for s in r["setups"][m]] for m in stop_ab.MODELS}
    all_triggers = {m: [t for r in results for t in r["triggers"][m]] for m in stop_ab.MODELS}
    report = {"generated_at": now.isoformat(), "models": {"A": a_model, "B": b_model},
              "replay": {"start": START.isoformat(), "horizon_bars": stop_ab.HORIZON_BARS,
                         "tight_risk_atr": stop_ab.TIGHT_RISK_ATR, "symbols": [r["symbol"] for r in results]},
              "counts": {r["symbol"]: {**r["counts"], "m15_bars": r["m15_bars"], "seconds": r["seconds"]} for r in results},
              "A": stop_ab.summarize(all_setups[a_model], all_triggers[a_model]),
              "B": stop_ab.summarize(all_setups[b_model], all_triggers[b_model]),
              "comparison": stop_ab.compare(all_setups[a_model], all_setups[b_model]),
              "by_instrument": {r["symbol"]: {"A": stop_ab.summarize(r["setups"][a_model], r["triggers"][a_model]),
                                              "B": stop_ab.summarize(r["setups"][b_model], r["triggers"][b_model])}
                                for r in results},
              "by_direction": {d: {"A": stop_ab.summarize([s for s in all_setups[a_model] if s["direction"] == d],
                                                          [t for t in all_triggers[a_model] if t["direction"] == d]),
                                   "B": stop_ab.summarize([s for s in all_setups[b_model] if s["direction"] == d],
                                                          [t for t in all_triggers[b_model] if t["direction"] == d])}
                               for d in ("LONG", "SHORT")},
              "setups": all_setups}
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("A", "B", "comparison")}, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main_report(Path(sys.argv[1] if len(sys.argv) > 1 else "tm_stop_ab.json"))
