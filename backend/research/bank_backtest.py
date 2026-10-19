"""Historical testing of the 20-strategy bank (writes data/strategy_bank/historical.json).

Uses the SAME strategy_bank.rules decide() functions and engine.confirm() gates as the live bank,
on closed bars of the cached MT5 history; entry at the first M15 open after the confirming close
(BUY at the ask: open + recorded spread). Trades are simulated by research/simulate.py (spread,
commission, stop slippage, overnight financing, M1 tie-break), one open position per strategy and
symbol. Linked strategies #1-3 use the production replay signals (research/lab generate) split by
setup family.

Two separate verdicts per strategy:
  technical      does the implementation trigger, are all levels valid, which gates reject what
  profitability  out-of-sample expectancy after costs (train / validation / test), with CIs
Rules are fixed (no parameter fitting), so all three periods are out-of-sample for the rules
themselves; the test window was already viewed in V6/T-033 for related families.

    python -m research.bank_backtest
"""
from __future__ import annotations

import bisect
import json
import multiprocessing
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from research import lab, v6

PERIODS = {"train": v6.TRAIN, "validation": v6.VALID, "test": v6.TEST}


def _symbol_signals(symbol: str) -> tuple[str, dict[str, list[dict[str, Any]]], dict[str, dict[str, int]], float]:
    from strategy_bank import engine, rules
    started = time.perf_counter()
    h = lab.history_for(symbol)
    frames = {tf: h.full[tf] for tf in ("M15", "H1", "H4", "D1")}
    ctx = rules.Ctx(symbol, frames)
    m15 = h.full["M15"]
    m15_utc = [b["utc"] for b in m15]
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tech: dict[str, Counter] = defaultdict(Counter)
    for spec in rules.scanned():
        if symbol not in spec["instruments"]:
            continue
        tf = spec["timeframe"]
        n = len(ctx.a[tf]["close"])
        for i in range(250 if tf != "M15" else 400, n):
            close_t = ctx.close_utc(tf, i)
            if close_t < v6.TRAIN[0].timestamp() or close_t >= v6.TEST[1].timestamp():
                continue
            d = spec["decide"](ctx, i)
            if d is None:
                continue
            tech[spec["key"]]["decisions"] += 1
            j = bisect.bisect_left(m15_utc, close_t)
            if j >= len(m15) or m15_utc[j] - close_t > 3 * 86400:
                tech[spec["key"]]["rejected: no next bar"] += 1
                continue
            bid, spread = m15[j]["open"], m15[j]["spread"]
            quote = {"bid": bid, "ask": bid + spread, "tick_age_seconds": 0.0, "basis": "historical next-bar open"}
            signal, reason = engine.confirm(spec, d, ctx, i, quote, close_t, check_freshness=False)
            if signal is None:
                tech[spec["key"]][f"rejected: {reason}"] += 1
                continue
            long = signal["direction"] == "LONG"
            ok = (signal["stop_loss"] < signal["entry"] < signal["take_profit"]) if long else (signal["take_profit"] < signal["entry"] < signal["stop_loss"])
            tech[spec["key"]]["accepted"] += 1
            tech[spec["key"]]["invalid_levels"] += 0 if ok else 1
            out[spec["key"]].append({"index": j, "utc": m15[j]["utc"], "symbol": symbol, "strategy_id": spec["key"],
                                     "direction": signal["direction"], "entry": signal["entry"], "stop_loss": signal["stop_loss"],
                                     "take_profit": signal["take_profit"], "max_bars": d.max_bars or 5 * 96,
                                     "spread": spread, "evidence": {"score": None}})
    return symbol, dict(out), {k: dict(v) for k, v in tech.items()}, time.perf_counter() - started


def linked_signals() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    tl = lab.load_signals("trendline_v5")
    out["trendline_break_retest"] = [s for s in tl if str(s["evidence"].get("setup_family")).upper() == "BREAK"]
    out["trendline_bounce"] = [s for s in tl if str(s["evidence"].get("setup_family")).upper() == "REVERSAL"]
    out["support_resistance"] = lab.load_signals("support_resistance")
    return out


def summarize(signals: list[dict[str, Any]]) -> dict[str, Any]:
    signals = sorted(signals, key=lambda s: (s["utc"], s["symbol"]))
    res: dict[str, Any] = {}
    for name, w in PERIODS.items():
        res[name] = v6.stats(v6.run(signals, w), w)
    full = (v6.TRAIN[0], v6.TEST[1])
    trades = v6.run(signals, full)
    res["all_periods"] = v6.stats(trades, full)
    res["all_periods_x2_costs"] = v6.stats(v6.run(signals, full, cost_multiplier=2.0), full)
    by_inst = defaultdict(list)
    for t in trades:
        by_inst[t["symbol"]].append(t)
    res["by_instrument"] = {k: {x: v6.stats(v)[x] for x in ("trades", "win_rate", "expectancy_r")} for k, v in sorted(by_inst.items())}
    from research.v6_round3 import one_sided_p
    res["p_value_all_periods"] = one_sided_p([t["r"] for t in trades if t.get("r") is not None])
    return res


def verdict(perf: dict[str, Any]) -> str:
    v, t, a = perf["validation"], perf["test"], perf["all_periods"]
    if a["trades"] < 30:
        return "INSUFFICIENT HISTORY"
    lo = (a["expectancy_ci95"] or [None])[0]
    if all((x["expectancy_r"] or 0) > 0 for x in (perf["train"], v, t)) and lo is not None and lo > 0 \
            and (perf["all_periods_x2_costs"]["expectancy_r"] or 0) > 0:
        return "HISTORICALLY POSITIVE (all periods, CI > 0, survives x2 costs) - still requires forward validation"
    if (a["expectancy_r"] or 0) > 0:
        return "NOT PROVEN (positive overall but not in every period / CI includes 0)"
    return "HISTORICALLY UNPROFITABLE after costs"


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from strategy_bank import engine, rules
    from research.v6_round3 import holm
    collected: dict[str, list] = defaultdict(list)
    technical: dict[str, Counter] = defaultdict(Counter)
    with multiprocessing.Pool(16) as pool:
        for symbol, out, tech, seconds in pool.imap_unordered(_symbol_signals, lab.SYMBOLS):
            print(f"  {symbol}: {sum(len(v) for v in out.values())} signals ({seconds:.0f}s)", flush=True)
            for k, v in out.items():
                collected[k] += v
            for k, v in tech.items():
                technical[k].update(v)
    linked = linked_signals()
    results = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "label": "HISTORICAL BACKTEST (simulated on MT5 history; not live results)",
               "periods": {k: [w[0].date().isoformat(), w[1].date().isoformat()] for k, w in PERIODS.items()},
               "costs": "spread on the correct side, IC-Markets-Raw-style commission, 0.5-spread stop slippage, overnight financing (current swap specs)",
               "strategies": {}}
    pvals = {}
    for spec in rules.SPECS:
        key = spec["key"]
        entry: dict[str, Any] = {"n": spec["n"], "name": spec["name"], "status": spec["status"]}
        if spec["status"] == rules.UNSUPPORTED:
            entry.update(technical={"note": "unsupported: no reliable traded-volume data"}, performance=None, verdict="UNSUPPORTED")
        else:
            sig = linked.get(key) if spec["status"] == rules.LINKED else collected.get(key, [])
            tech = dict(technical.get(key, {})) if spec["status"] != rules.LINKED else {"note": "production strategy replay (research/replay.py)", "accepted": len(sig)}
            perf = summarize(sig) if sig else None
            entry.update(technical=tech, performance=perf, verdict=verdict(perf) if perf else "NO SIGNALS")
            if perf and perf["p_value_all_periods"] is not None:
                pvals[key] = perf["p_value_all_periods"]
        results["strategies"][key] = entry
        a = (entry.get("performance") or {}).get("all_periods") or {}
        print(f"{spec['n']:2} {spec['name']:32} n={a.get('trades')} WR={a.get('win_rate')} E={a.get('expectancy_r')} CI={a.get('expectancy_ci95')} -> {entry['verdict']}", flush=True)
    adjusted = holm(pvals)
    for key, p in adjusted.items():
        results["strategies"][key]["holm_adjusted_p"] = p
    results["multiple_testing"] = f"Holm-Bonferroni across {len(pvals)} strategies (one-sided H0: expectancy <= 0)."
    path = engine.bank_dir() / "historical.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"written {path}")


if __name__ == "__main__":
    main()
