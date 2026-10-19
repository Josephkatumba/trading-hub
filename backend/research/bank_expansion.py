"""Research and admission of bank expansion strategies (strategy_bank/expansion.py).

Same pipeline as research/bank_backtest.py (bank decide() + engine.confirm() gates, next-open entry,
spread/commission/slippage/financing), then the V6/T-033 protocol per family:
  train      rank the family's configurations (robust shortlist: >= 60 trades, positive, neighbours)
  validation choose one configuration (>= 30 trades, positive)
  test       score it ONCE (enforced: data/strategy_bank/expansion_results.json "test_consumed")
  controls   random-entry percentile on development; global Holm-Bonferroni across every test scoring
             in TRADEden's research (discovery registry + bank history + these)
Admission: a chosen configuration whose single test is positive with profit factor > 1 is admitted to
FORWARD_TESTING (registered in the bank as RESEARCH: scanned and recorded, never alerted). Everything
else is ARCHIVED with its evidence. Every configuration is also written to the lab ledger.

    python -m research.bank_expansion            (also writes the capacity measurements)
"""
from __future__ import annotations

import bisect
import json
import multiprocessing
import time
import tracemalloc
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research import lab, v6

FAMILY_KEYS = ("fx_session_momentum", "weekend_gap", "turtle_soup", "heikin_ashi_trend", "kama_trend", "prior_close_reversion")


def signals_for(symbol: str, specs: list[dict[str, Any]]) -> tuple[dict[str, list], dict[str, dict]]:
    """Bank-pipeline signals of `specs` on one symbol's cached history (train start .. test end)."""
    from strategy_bank import engine, rules
    h = lab.history_for(symbol)
    ctx = rules.Ctx(symbol, {tf: h.full[tf] for tf in ("M15", "H1", "H4", "D1")})
    m15 = h.full["M15"]
    m15_utc = [b["utc"] for b in m15]
    out: dict[str, list] = defaultdict(list)
    tech: dict[str, Counter] = defaultdict(Counter)
    for spec in specs:
        if symbol not in spec["instruments"]:
            continue
        tf = spec["timeframe"]
        for i in range(250 if tf != "M15" else 400, len(ctx.a[tf]["close"])):
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
            signal, reason = engine.confirm(spec, d, ctx, i, {"bid": bid, "ask": bid + spread, "tick_age_seconds": 0.0},
                                            close_t, check_freshness=False)
            if signal is None:
                tech[spec["key"]][f"rejected: {reason}"] += 1
                continue
            tech[spec["key"]]["accepted"] += 1
            out[spec["key"]].append({"index": j, "utc": m15[j]["utc"], "symbol": symbol, "strategy_id": spec["key"],
                                     "direction": signal["direction"], "entry": signal["entry"], "stop_loss": signal["stop_loss"],
                                     "take_profit": signal["take_profit"], "max_bars": d.max_bars or 5 * 96,
                                     "spread": spread, "evidence": {"score": None}})
    return dict(out), {k: dict(v) for k, v in tech.items()}


def _worker(symbol: str) -> tuple[str, dict, dict, float]:
    from strategy_bank import expansion
    started = time.perf_counter()
    out, tech = signals_for(symbol, list(expansion.CANDIDATES.values()))
    return symbol, out, tech, time.perf_counter() - started


def results_path() -> Path:
    from strategy_bank import engine
    return engine.bank_dir() / "expansion_results.json"


def capacity() -> dict[str, Any]:
    """Measured cost of the bank: live scan per M15 close, memory, and backtest time per strategy."""
    import os
    from strategy_bank import rules, expansion
    h = lab.history_for("EURUSD")
    window = {tf: h.full[tf][-n:] for tf, n in (("M15", 400), ("H1", 400), ("H4", 260), ("D1", 60))}
    specs = rules.scanned() + list(expansion.CANDIDATES.values())
    tracemalloc.start()
    t = time.perf_counter()
    ctx = rules.Ctx("EURUSD", window)
    for spec in specs:
        tf = spec["timeframe"]
        spec["decide"](ctx, len(ctx.a[tf]["close"]) - 1)
    per_symbol = time.perf_counter() - t
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # End-to-end backtest of the heaviest strategy (most signals): every symbol, gates, simulation, statistics.
    heavy = rules.BY_KEY["ema_pullback"]
    t = time.perf_counter()
    signals = []
    for symbol in lab.SYMBOLS:
        out, _ = signals_for(symbol, [heavy])
        signals += out.get(heavy["key"], [])
    signals.sort(key=lambda s: (s["utc"], s["symbol"]))
    for window in (v6.TRAIN, v6.VALID, v6.TEST):
        v6.stats(v6.run(signals, window), window)
    per_strategy_end_to_end = time.perf_counter() - t
    per_strategy_symbol_backtest = per_strategy_end_to_end / len(lab.SYMBOLS)
    cores = os.cpu_count() or 1
    live_budget = 30.0                      # seconds of CPU we allow per M15 close (bar is 900 s)
    per_strategy_scan = per_symbol / max(1, len(specs))
    return {"cpu_cores": cores, "strategies_measured": len(specs),
            "live_scan_seconds_per_symbol_all_strategies": round(per_symbol, 4),
            "live_scan_seconds_per_strategy_per_symbol": round(per_strategy_scan, 5),
            "live_peak_memory_mb_per_symbol_context": round(peak / 1e6, 1),
            "backtest_seconds_per_strategy_per_symbol_2y": round(per_strategy_symbol_backtest, 2),
            "estimate": {
                "live_strategies_within_30s_per_M15_close_16_symbols": int(live_budget / max(1e-6, per_strategy_scan * 16)),
                "end_to_end_backtest_seconds_heaviest_strategy_16_symbols_serial": round(per_strategy_end_to_end, 1),
                "strategy_backtests_per_hour_parallel": int(3600 / max(1e-6, per_strategy_end_to_end / max(1, min(cores, 16) // 2))),
                "note": "Live scan: one engine thread, decide() only (MT5 bar fetch adds ~0.1-0.3 s per symbol, independent of the number of strategies). Backtests: end to end (gates, simulation with costs, statistics), parallel estimate assumes half the cores (hyper-threading, engine headroom). Measured on this laptop."}}


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    from strategy_bank import expansion, qualification
    from research import discovery
    from research.v6_round3 import one_sided_p, holm
    prior = json.loads(results_path().read_text(encoding="utf-8")) if results_path().exists() else {}
    consumed = prior.get("test_consumed", {})
    collected: dict[str, list] = defaultdict(list)
    technical: dict[str, Counter] = defaultdict(Counter)
    t0 = time.perf_counter()
    with multiprocessing.Pool(16) as pool:
        for symbol, out, tech, seconds in pool.imap_unordered(_worker, lab.SYMBOLS):
            print(f"  {symbol}: {sum(len(v) for v in out.values())} signals ({seconds:.0f}s)", flush=True)
            for k, v in out.items():
                collected[k] += v
            for k, v in tech.items():
                technical[k].update(v)
    generation_seconds = time.perf_counter() - t0
    results: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "protocol": discovery.PROTOCOL,
                               "families": {}, "test_consumed": consumed}
    pvals: dict[str, float] = {}
    for family in FAMILY_KEYS:
        fam = expansion.FAMILIES[family]
        for key, spec in fam["configs"].items():
            qualification.transition(key, qualification.RESEARCHING, "T-036 expansion candidate under research",
                                     name=spec["name"], source="bank")
        grid = {key: (lambda k=key: sorted(collected.get(k, []), key=lambda s: (s["utc"], s["symbol"]))) for key in fam["configs"]}
        sel = v6.select(family, {"grid": grid, "rationale": fam["rationale"]}, lambda m: print(m, flush=True))
        entry: dict[str, Any] = {"source": fam["source"], "rationale": fam["rationale"], "configs": list(fam["configs"]),
                                 "technical": {k: dict(technical.get(k, {})) for k in fam["configs"]},
                                 "train": sel["train"], "shortlist": sel["shortlist"], "chosen": sel["chosen"],
                                 "validation": sel["validation"]}
        verdict = "REJECTED ON TRAIN" if not sel["shortlist"] else "REJECTED ON VALIDATION"
        if sel["chosen"] and sel["chosen_validation_positive"]:
            if sel["chosen"] in consumed:
                raise RuntimeError(f"{sel['chosen']} has already been scored on the test window")
            scored = v6.score_test(sel)
            consumed[sel["chosen"]] = datetime.now(timezone.utc).isoformat()
            verdict = v6.verdict(scored)
            rs = [t["r"] for t in scored["_test_trades"] if t.get("r") is not None]
            entry["test"] = {k: v for k, v in scored.items() if not k.startswith("_")}
            entry["p_value"] = one_sided_p(rs)
            entry["random_control"] = discovery.random_percentile(sel["_signals"][sel["chosen"]])
            if entry["p_value"] is not None:
                pvals[sel["chosen"]] = entry["p_value"]
        entry["verdict"] = verdict
        test = (entry.get("test") or {}).get("test") or {}
        admitted = bool(test) and (test.get("expectancy_r") or 0) > 0 and (test.get("profit_factor") or 0) > 1 \
            and not verdict.startswith("FAILED")
        for key, spec in fam["configs"].items():
            lab.record({"name": f"T036 {family}: {key}", "kind": "t036-bank-expansion", "family": family, "config": key,
                        "train": sel["train"].get(key), "validation": sel["validation"].get(key),
                        "test": test if key == sel["chosen"] else None, "verdict": verdict if key == sel["chosen"] else "not chosen"})
            evidence = {"train": sel["train"].get(key), "validation": sel["validation"].get(key),
                        "test": test if key == sel["chosen"] else None, "verdict": verdict}
            if key == sel["chosen"] and admitted:
                qualification.transition(key, qualification.BACKTESTED, f"passed train/validation; single test {verdict}", evidence=evidence)
                qualification.transition(key, qualification.FORWARD_TESTING,
                                         "admitted to shadow forward testing (recorded only, never alerted)", evidence=evidence)
            else:
                reason = verdict.lower() if key == sel["chosen"] else ("not chosen: " + verdict.lower())
                qualification.transition(key, qualification.ARCHIVED, reason, evidence=evidence)
        entry["admitted"] = sel["chosen"] if admitted else None
        results["families"][family] = entry
        print(f"  {family}: {verdict} -> {'FORWARD_TESTING ' + sel['chosen'] if admitted else 'ARCHIVED'}", flush=True)
    # Global multiple testing: every test scoring in TRADEden's research.
    reg = discovery.load()
    allp = dict(reg.get("global", {}).get("multiple_testing", {}).get("raw", {}))
    hist_path = results_path().with_name("historical.json")
    if hist_path.exists():
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
        allp.update({f"bank {k}": v["performance"]["p_value_all_periods"] for k, v in hist["strategies"].items()
                     if v.get("performance") and v["performance"].get("p_value_all_periods") is not None})
    allp.update({f"T036 {k}": p for k, p in pvals.items()})
    results["multiple_testing"] = {"tests": len(allp), "holm": {k: v for k, v in holm(allp).items() if k.startswith("T036")}}
    results["test_consumed"] = consumed
    results["generation_seconds_16_processes"] = round(generation_seconds, 1)
    results["capacity"] = capacity()
    results_path().write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"multiple_testing": results["multiple_testing"], "capacity": results["capacity"]}, indent=1))
    print(f"written {results_path()}")


if __name__ == "__main__":
    main()
