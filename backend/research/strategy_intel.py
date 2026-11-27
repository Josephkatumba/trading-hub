"""Strategy Performance Intelligence: one consistent historical evaluation of every bank strategy
(writes data/strategy_bank/intel.json, read by GET /api/intelligence/strategies).

Covers the T-034 bank strategies, the admitted expansion strategies, the ICT family
(strategy_bank/ict.py) and the audited upgrades (strategy_bank/upgrades.py), plus the three
production-linked strategies (production replay signals). Every bank strategy is replayed with the
SAME decide() functions and engine.confirm() gates as the live bank, on closed bars of the cached MT5
history: entry at the first M15 open after the confirming close (BUY at the ask), simulated by
research/simulate.py with spread, commission, stop slippage, overnight financing and an M1 tie-break,
one position per strategy and symbol (research/lab.trades).

Look-ahead protection: decide(ctx, i) receives only the index of the bar that has just closed and
every indicator is causal (tests/test_ict_strategies.py checks that decisions do not change when
future bars are appended). Overfitting protection: rules are fixed before this run (no parameter
search), the test period is reported separately, results survive or fail doubled costs, rolling
quarterly folds are reported, and significance is Holm-adjusted across every strategy evaluated.

Periods (research/v6.py): train 2024-10-15..2025-10-01, validation ..2026-04-01, test ..2026-10-12.
"Development" = train + validation. Walk-forward = lab.FOLDS (quarterly) plus the test period.

    python -m research.strategy_intel                 # all strategies, all symbols
    python -m research.strategy_intel --keys ict_mss  # a subset (merged into the existing file)
"""
from __future__ import annotations

import argparse
import re
import bisect
import json
import multiprocessing
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from research import lab, v6

PERIODS = {"train": v6.TRAIN, "validation": v6.VALID, "test": v6.TEST}
DEVELOPMENT = (v6.TRAIN[0], v6.VALID[1])
FULL = (v6.TRAIN[0], v6.TEST[1])
FOLDS = list(lab.FOLDS) + [v6.TEST]
SESSIONS = (("Asia", 0, 7), ("London", 7, 12), ("London/NY overlap", 12, 16), ("New York", 16, 21), ("Late / rollover", 21, 24))


def session_of(utc: float) -> str:
    hour = int(utc // 3600 % 24)
    return next(name for name, lo, hi in SESSIONS if lo <= hour < hi)


def _regime(ctx, utc: float) -> dict[str, str]:
    """Market regime at the confirming close, from closed H1 bars (causal)."""
    j = ctx.last_closed("H1", utc)
    if j < 150:
        return {"trend": "UNKNOWN", "volatility": "UNKNOWN"}
    adx = ctx.get("H1", "adx")[0][j]
    key = ("H1", "intel_atr_pct")
    if key not in ctx._cache:
        from strategy_bank import indicators as ind
        ctx._cache[key] = ind.rolling_percentile(ctx.get("H1", "atr"), 120)
    pct = ctx._cache[key][j]
    trend = "UNKNOWN" if adx != adx else "TRENDING" if adx >= 25 else "RANGING" if adx < 20 else "TRANSITIONAL"
    vol = "UNKNOWN" if pct != pct else "HIGH VOL" if pct >= 0.7 else "LOW VOL" if pct <= 0.3 else "NORMAL VOL"
    return {"trend": trend, "volatility": vol}


def _symbol(args: tuple[str, list[str] | None]) -> tuple[str, dict, dict, dict, float]:
    symbol, keys = args
    from strategy_bank import engine, rules
    rules.load_expansion()
    started = time.perf_counter()
    h = lab.history_for(symbol)
    ctx = rules.Ctx(symbol, {tf: h.full[tf] for tf in ("M15", "H1", "H4", "D1")})
    m15 = h.full["M15"]
    m15_utc = [b["utc"] for b in m15]
    out: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}
    tech: dict[str, Counter] = defaultdict(Counter)
    lo_t, hi_t = v6.TRAIN[0].timestamp(), v6.TEST[1].timestamp()
    for spec in rules.scanned():
        if symbol not in spec["instruments"] or (keys and spec["key"] not in keys):
            continue
        tf = spec["timeframe"]
        n = len(ctx.a[tf]["close"])
        for i in range(250 if tf != "M15" else 400, n):
            close_t = ctx.close_utc(tf, i)
            if close_t < lo_t or close_t >= hi_t:
                continue
            try:
                d = spec["decide"](ctx, i)
            except Exception as exc:                       # a failing rule is a technical finding, not a crash
                tech[spec["key"]][f"error: {type(exc).__name__}"] += 1
                continue
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
                tech[spec["key"]]["rejected: " + re.sub(r"[-+]?\d+(\.\d+)?", "x", reason)] += 1
                continue
            tech[spec["key"]]["accepted"] += 1
            out[spec["key"]].append({"index": j, "utc": m15[j]["utc"], "symbol": symbol, "strategy_id": spec["key"],
                                     "direction": signal["direction"], "entry": signal["entry"], "stop_loss": signal["stop_loss"],
                                     "take_profit": signal["take_profit"], "max_bars": d.max_bars or 5 * 96,
                                     "spread": spread, "evidence": {"score": None}})
            meta[f"{spec['key']}|{j}"] = {"rr": signal["rr"], "session": session_of(close_t), **_regime(ctx, close_t)}
    if not keys or any(k in keys for k in ("trendline_break_retest", "trendline_bounce", "support_resistance")):
        for key, rows in _linked(symbol).items():
            if keys and key not in keys:
                continue
            for s in rows:
                s = {**s, "strategy_id": key}
                out[key].append(s)
                risk = abs(s["entry"] - s["stop_loss"])
                rr = abs(s["take_profit"] - s["entry"]) / risk if risk else None
                meta[f"{key}|{s['index']}"] = {"rr": round(rr, 3) if rr else None, "session": session_of(s["utc"]), **_regime(ctx, s["utc"])}
    return symbol, dict(out), meta, {k: dict(v) for k, v in tech.items()}, time.perf_counter() - started


_LINKED_CACHE: dict[str, list] = {}


def _linked(symbol: str) -> dict[str, list]:
    if not _LINKED_CACHE:
        try:
            tl = lab.load_signals("trendline_v5")
            _LINKED_CACHE["trendline_break_retest"] = [s for s in tl if str(s["evidence"].get("setup_family")).upper() == "BREAK"]
            _LINKED_CACHE["trendline_bounce"] = [s for s in tl if str(s["evidence"].get("setup_family")).upper() == "REVERSAL"]
            _LINKED_CACHE["support_resistance"] = lab.load_signals("support_resistance")
        except FileNotFoundError:
            _LINKED_CACHE["_none"] = []
    return {k: [s for s in v if s["symbol"] == symbol] for k, v in _LINKED_CACHE.items() if not k.startswith("_")}


def _np_bootstrap(values: list[float], seed: int = 7) -> tuple[float | None, float | None, float | None]:
    """Vectorised equivalent of research.metrics._bootstrap (same 4000 seeded percentile resamples of the
    mean, same 2.5/97.5% indices and P(mean > 0)); the pure-Python version took ~3 s per 5000 trades.
    Installed for this runner only; research/metrics.py is unchanged for every other ledger."""
    from research import metrics
    if len(values) < 2:
        return None, None, None
    n, b = len(values), metrics.BOOTSTRAP
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(b)
    for k in range(0, b, 500):                           # chunked to bound memory on large samples
        m = min(500, b - k)
        means[k:k + m] = v[rng.integers(0, n, size=(m, n))].mean(axis=1)
    means.sort()
    return (round(float(means[int(0.025 * b)]), 4), round(float(means[int(0.975 * b) - 1]), 4),
            round(float((means > 0).mean()), 3))


def _install_fast_bootstrap() -> None:
    from research import metrics
    metrics._bootstrap = _np_bootstrap


def _simple(trades: list[dict]) -> dict[str, Any]:
    """Point statistics without confidence intervals (for conditional breakdowns)."""
    rs = [t["r"] for t in trades if t.get("r") is not None]
    if not rs:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None, "expectancy_r": None, "profit_factor": None,
                "total_r": 0.0, "max_drawdown_r": 0.0}
    gw, gl = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); dd = max(dd, peak - eq)
    wins = sum(1 for r in rs if r > 0)
    return {"trades": len(rs), "wins": wins, "losses": len(rs) - wins, "win_rate": round(wins / len(rs), 4),
            "expectancy_r": round(sum(rs) / len(rs), 4), "profit_factor": round(gw / gl, 3) if gl else None,
            "total_r": round(sum(rs), 2), "max_drawdown_r": round(dd, 3)}


def _stats(trades: list[dict], window=None) -> dict[str, Any]:
    s = v6.stats(trades, window)
    rs = [t["r"] for t in trades if t.get("r") is not None]
    s["wins"] = sum(1 for r in rs if r > 0)
    s["losses"] = sum(1 for r in rs if r <= 0)
    return s


def _group(trades: list[dict], meta: dict, field: str) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        m = meta.get(f"{t['strategy_id']}|{t['index']}", {})
        groups[str(t["symbol"] if field == "symbol" else t["direction"] if field == "direction" else m.get(field, "UNKNOWN"))].append(t)
    return {k: _simple(v) for k, v in sorted(groups.items())}


def evaluate(signals: list[dict], meta: dict) -> dict[str, Any]:
    signals = sorted(signals, key=lambda s: (s["utc"], s["symbol"]))
    perf: dict[str, Any] = {name: _stats(v6.run(signals, w), w) for name, w in PERIODS.items()}
    perf["development"] = _stats(v6.run(signals, DEVELOPMENT), DEVELOPMENT)
    trades = v6.run(signals, FULL)
    perf["all_periods"] = _stats(trades, FULL)
    perf["all_periods_x2_costs"] = _stats(v6.run(signals, FULL, cost_multiplier=2.0), FULL)
    perf["walk_forward"] = [{"start": a.date().isoformat(), "end": b.date().isoformat(),
                             **{k: v for k, v in _simple(v6.run(signals, (a, b))).items() if k in ("trades", "expectancy_r", "win_rate", "profit_factor")}}
                            for a, b in FOLDS]
    rrs = [meta.get(f"{s['strategy_id']}|{s['index']}", {}).get("rr") for s in signals]
    rrs = [x for x in rrs if x]
    perf["avg_planned_rr"] = round(float(np.mean(rrs)), 3) if rrs else None
    perf["by_instrument"] = _group(trades, meta, "symbol")
    perf["by_session"] = _group(trades, meta, "session")
    perf["by_trend_regime"] = _group(trades, meta, "trend")
    perf["by_volatility_regime"] = _group(trades, meta, "volatility")
    perf["by_direction"] = _group(trades, meta, "direction")
    perf["equity_r"] = [round(x, 2) for x in np.cumsum([t["r"] for t in trades if t.get("r") is not None])[::max(1, len(trades) // 120)].tolist()] if trades else []
    from research.v6_round3 import one_sided_p
    perf["p_value_all_periods"] = one_sided_p([t["r"] for t in trades if t.get("r") is not None])
    perf["_trades"] = [{**{k: t.get(k) for k in ("utc", "symbol", "strategy_id", "direction", "outcome", "r", "exit_index", "index")},
                        **meta.get(f"{t['strategy_id']}|{t['index']}", {})} for t in trades]
    return perf


def _sha(path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save_baseline(result: dict[str, Any], trade_log: dict, signal_log: dict, symbols: list[str]) -> None:
    """Freeze this evaluation as the research baseline: results, every signal and simulated trade,
    and hashes of the code and data that produced them (data/strategy_bank/baselines/<date>/)."""
    import gzip
    from pathlib import Path
    from strategy_bank import engine
    from research import history
    stamp = result["generated_at"][:10]
    folder = engine.bank_dir() / "baselines" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "intel.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    with gzip.open(folder / "trades.jsonl.gz", "wt", encoding="utf-8") as fh:
        for key, rows in trade_log.items():
            for r in rows:
                fh.write(json.dumps({"strategy": key, **r}, default=str) + "\n")
    with gzip.open(folder / "signals.jsonl.gz", "wt", encoding="utf-8") as fh:
        for key, rows in signal_log.items():
            for r in rows:
                fh.write(json.dumps({"strategy": key, **{k: v for k, v in r.items() if k != "evidence"}}, default=str) + "\n")
    root = Path(__file__).resolve().parents[1]
    code = ["strategy_bank/ict.py", "strategy_bank/upgrades.py", "strategy_bank/rules.py", "strategy_bank/expansion.py",
            "strategy_bank/engine.py", "strategy_bank/evidence_tiers.py", "strategy_bank/indicators.py", "research/strategy_intel.py",
            "research/simulate.py", "research/lab.py", "research/v6.py", "research/metrics.py"]
    data = {}
    for sym in symbols:
        for tf in ("M15", "H1", "H4", "D1", "M1"):
            bars = history.load(sym, tf)
            if bars:
                data[f"{sym}_{tf}"] = {"bars": len(bars), "first_utc": bars[0]["utc"], "last_utc": bars[-1]["utc"]}
    manifest = {"baseline": stamp, "generated_at": result["generated_at"], "strategies": len(result["strategies"]),
                "trades": sum(len(v) for v in trade_log.values()), "signals": sum(len(v) for v in signal_log.values()),
                "code_sha256": {c: _sha(root / c) for c in code if (root / c).exists()}, "bar_cache": data,
                "bootstrap": "numpy percentile bootstrap, 4000 resamples, seed 7 (equivalent to research.metrics._bootstrap)",
                "note": "Research baseline. Later evaluations are compared against this one; do not overwrite it."}
    (folder / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"baseline saved to {folder}")


def main() -> None:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", default="")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    keys = [k for k in args.keys.split(",") if k] or None
    symbols = [s for s in args.symbols.split(",") if s] or list(lab.SYMBOLS)
    from strategy_bank import engine, evidence_tiers, ict, rules, upgrades
    from research.v6_round3 import holm
    rules.load_expansion()
    _install_fast_bootstrap()
    collected: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}
    technical: dict[str, Counter] = defaultdict(Counter)
    started = time.perf_counter()
    with multiprocessing.Pool(min(args.workers, len(symbols))) as pool:
        for symbol, out, m, tech, seconds in pool.imap_unordered(_symbol, [(s, keys) for s in symbols]):
            print(f"  {symbol}: {sum(len(v) for v in out.values())} signals ({seconds:.0f}s)", flush=True)
            for k, v in out.items():
                collected[k] += v
            meta.update(m)
            for k, v in tech.items():
                technical[k].update(v)
    path = engine.bank_dir() / "intel.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() and keys else {}
    strategies = dict(previous.get("strategies") or {})
    trade_log: dict[str, list] = {}
    signal_log: dict[str, list] = {}
    for spec in rules.SPECS:
        if keys and spec["key"] not in keys:
            continue
        if spec["status"] == rules.UNSUPPORTED:
            strategies[spec["key"]] = {"name": spec["name"], "status": spec["status"], "unsupported_reason": spec.get("unsupported_reason")}
            continue
        sig = collected.get(spec["key"], [])
        perf = evaluate(sig, meta) if sig else None
        if perf:
            trade_log[spec["key"]] = perf.pop("_trades")
            signal_log[spec["key"]] = sig
        print(f"  evaluated {spec['key']} ({len(sig)} signals, {time.perf_counter() - started:.0f}s)", flush=True)
        strategies[spec["key"]] = {"name": spec["name"], "status": spec["status"], "timeframe": spec["timeframe"],
                                   "family": spec.get("family") or ("PRODUCTION-LINKED" if spec["status"] == rules.LINKED else "T-034 BANK"),
                                   "group": spec.get("group"), "replaces": spec.get("replaces"), "hypothesis": spec.get("hypothesis"),
                                   "technical": dict(technical.get(spec["key"], {})) or ({"accepted": len(sig)} if sig else {}),
                                   "performance": perf}
    pvals = {k: v["performance"]["p_value_all_periods"] for k, v in strategies.items()
             if v.get("performance") and v["performance"].get("p_value_all_periods") is not None}
    adjusted = holm(pvals)
    for k, v in strategies.items():
        v["holm_p"] = adjusted.get(k)
        v["evidence"] = evidence_tiers.classify(v.get("performance"), adjusted.get(k))
    result = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "label": "HISTORICAL EVALUATION (simulated on MT5 history with costs; not live results)",
              "periods": {k: [a.date().isoformat(), b.date().isoformat()] for k, (a, b) in PERIODS.items()},
              "development": [DEVELOPMENT[0].date().isoformat(), DEVELOPMENT[1].date().isoformat()],
              "folds": [[a.date().isoformat(), b.date().isoformat()] for a, b in FOLDS],
              "costs": "spread on the correct side, IC-Markets-Raw-style commission, 0.5-spread stop slippage, overnight financing; x2-cost stress reported",
              "protocol": {"ict": {"version": ict.VERSION, "params": ict.PARAMS}, "upgrades": upgrades.VERSION,
                           "tiers": evidence_tiers.__doc__.strip().splitlines()[0],
                           "multiple_testing": f"Holm-Bonferroni across {len(pvals)} strategies (one-sided H0: expectancy <= 0)",
                           "note": "Rules fixed before the run; no parameter search. The test window was previously viewed for related "
                                   "families (V6/T-033), so it is not pristine for FVG / order-block / sweep ideas."},
              "runtime_seconds": round(time.perf_counter() - started, 1),
              "strategies": strategies}
    path.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    if not keys:
        _save_baseline(result, trade_log, signal_log, symbols)
    print(f"wrote {path} ({len(strategies)} strategies)")
    for k, v in sorted(strategies.items(), key=lambda kv: -((kv[1].get("performance") or {}).get("all_periods", {}).get("expectancy_r") or -9)):
        a = (v.get("performance") or {}).get("all_periods") or {}
        print(f"  {k:28s} {v['evidence']['tier']:12s} n={a.get('trades')} E={a.get('expectancy_r')} CI={a.get('expectancy_ci95')} PF={a.get('profit_factor')}")


if __name__ == "__main__":
    main()
