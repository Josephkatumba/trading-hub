"""Walk-forward optimisation with out-of-sample evaluation.

    python -m engine.walkforward XAUUSD            # one symbol
    python -m engine.walkforward XAUUSD BTCUSD EURUSD GBPUSD --portfolio

For each rolling fold the grid is scored on the TRAIN window only; the chosen
parameters then trade the following TEST window, which they have never seen.
Only the concatenated TEST trades are reported as out-of-sample evidence.
The full-period grid is also reported so the share of profitable configs
(how easy it is to find something that "worked") is visible.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .market import INSTRUMENTS, load_m1
from .metrics import breakdown, summarize
from .simulator import M1Path, RiskParams, TradeParams, build_trades, params_dict, run_portfolio
from .strategy import constants_dict, generate_candidates

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
STRATEGY_VERSION = "tds-1.0"

GRID = {
    "rr": [1.0, 1.5, 2.0, 2.5],
    "sl_buffer_atr": [0.2, 0.5],
    "min_score": [70, 80, 90],
    "setups": [("BRT",), ("PB",), ("BRT", "PB")],
    "breakeven_r": [0.0, 1.0],
    "max_hold_min": [60, 180],
}


def grid():
    keys = list(GRID)
    for combo in itertools.product(*(GRID[k] for k in keys)):
        yield TradeParams(**dict(zip(keys, combo)))


def objective(df: pd.DataFrame, min_trades: int) -> float:
    if df.empty or len(df) < min_trades:
        return -math.inf
    r = df["r_multiple"].to_numpy(float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(len(r))) if sd > 0 else -math.inf


def slice_trades(trades, start, end):
    s, e = np.datetime64(start), np.datetime64(end)
    return [t for t in trades if s <= t["entry_time"] < e]


def folds(start: pd.Timestamp, end: pd.Timestamp, train_w: int, test_w: int):
    t0 = start.normalize() - pd.Timedelta(days=start.dayofweek)  # Monday
    out = []
    while True:
        tr_s, tr_e = t0, t0 + pd.Timedelta(weeks=train_w)
        te_e = tr_e + pd.Timedelta(weeks=test_w)
        if tr_e >= end:
            break
        out.append((tr_s, tr_e, tr_e, min(te_e, end)))
        if te_e >= end:
            break
        t0 += pd.Timedelta(weeks=test_w)
    return out


def run_symbol(symbol: str, train_w: int, test_w: int, risk: RiskParams, min_train_trades: int):
    m1 = load_m1(symbol)
    inst = INSTRUMENTS[symbol]
    cands = generate_candidates(symbol, m1)
    path = M1Path(m1)
    configs = list(grid())
    all_trades = [build_trades(cands, path, p, inst) for p in configs]

    # full-period landscape (in-sample; for overfitting context only)
    landscape = []
    for p, tr in zip(configs, all_trades):
        df = run_portfolio(tr, risk)
        s = summarize(df, risk.start_equity)
        landscape.append({"params": params_dict(p), **{k: s.get(k) for k in ("trades", "net_pnl", "expectancy_r", "profit_factor", "t_stat")}})
    profitable = sum(1 for x in landscape if (x["net_pnl"] or 0) > 0 and x["trades"] >= min_train_trades)

    start, end = m1["time"].iloc[0], m1["time"].iloc[-1]
    fold_rows, oos = [], []
    for tr_s, tr_e, te_s, te_e in folds(start, end, train_w, test_w):
        best_i, best_obj = None, -math.inf
        for i, tr in enumerate(all_trades):
            obj = objective(run_portfolio(slice_trades(tr, tr_s, tr_e), risk), min_train_trades)
            if obj > best_obj:
                best_i, best_obj = i, obj
        row = {"train": [str(tr_s.date()), str(tr_e.date())], "test": [str(te_s.date()), str(te_e.date())]}
        if best_i is None:
            row.update({"selected": None, "note": "no config met the train trade minimum; fold sits out"})
            fold_rows.append(row)
            continue
        test_df = run_portfolio(slice_trades(all_trades[best_i], te_s, te_e), risk)
        train_df = run_portfolio(slice_trades(all_trades[best_i], tr_s, tr_e), risk)
        row.update({"selected": params_dict(configs[best_i]), "train_obj": round(best_obj, 2),
                    "train": row["train"], "train_summary": summarize(train_df, risk.start_equity),
                    "test_summary": summarize(test_df, risk.start_equity)})
        fold_rows.append(row)
        if not test_df.empty:
            oos.append(test_df.assign(fold=len(fold_rows)))
    oos_df = pd.concat(oos, ignore_index=True) if oos else pd.DataFrame()
    default_df = run_portfolio(build_trades(cands, path, TradeParams(), inst), risk)
    return {
        "symbol": symbol,
        "data": {"first_bar_utc": str(start), "last_bar_utc": str(end), "m1_bars": int(len(m1)), "candidates": int(len(cands))},
        "configs_tested": len(configs),
        "configs_profitable_in_sample": profitable,
        "best_in_sample": max(landscape, key=lambda x: (x["net_pnl"] or -1e18)),
        "default_params_full_period": summarize(default_df, risk.start_equity),
        "folds": fold_rows,
        "out_of_sample": summarize(oos_df, risk.start_equity),
        "oos_by_setup": breakdown(oos_df, "setup", risk.start_equity),
        "oos_by_session": breakdown(oos_df, "session", risk.start_equity),
        "oos_by_reason": breakdown(oos_df, "reason", risk.start_equity),
        "_oos_trades": oos_df,
        "_all_trades": all_trades,
        "_configs": configs,
    }


def verdict(oos: dict) -> str:
    n = oos.get("trades", 0)
    if n < 30:
        return "INSUFFICIENT_EVIDENCE"
    t = oos.get("t_stat") or 0
    if oos.get("net_pnl", 0) > 0 and t >= 2.0:
        return "EDGE_CANDIDATE"
    if oos.get("net_pnl", 0) > 0:
        return "PROFITABLE_NOT_SIGNIFICANT"
    return "NO_EDGE"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--train-weeks", type=int, default=6)
    ap.add_argument("--test-weeks", type=int, default=2)
    ap.add_argument("--min-train-trades", type=int, default=15)
    ap.add_argument("--portfolio", action="store_true", help="also run the OOS-selected trades of all symbols through one account")
    a = ap.parse_args(argv)
    risk = RiskParams()
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    results, oos_all = [], []
    for s in a.symbols:
        print(f"[{s}] generating candidates and simulating {len(list(grid()))} configs ...", flush=True)
        res = run_symbol(s, a.train_weeks, a.test_weeks, risk, a.min_train_trades)
        res["verdict"] = verdict(res["out_of_sample"])
        oos_df = res.pop("_oos_trades")
        res.pop("_all_trades"); res.pop("_configs")
        if not oos_df.empty:
            oos_all.append(oos_df)
            oos_df.to_csv(REPORTS / f"oos_trades_{s}_{stamp}.csv", index=False)
        results.append(res)
        print(json.dumps({"symbol": s, "verdict": res["verdict"], "oos": res["out_of_sample"],
                          "default_full": res["default_params_full_period"],
                          "profitable_configs_in_sample": f'{res["configs_profitable_in_sample"]}/{res["configs_tested"]}'}, indent=1, default=str), flush=True)
    report = {"strategy_version": STRATEGY_VERSION, "generated_utc": stamp, "risk": params_dict(risk),
              "constants": constants_dict(), "grid": {k: [list(v) if isinstance(v, tuple) else v for v in vals] for k, vals in GRID.items()},
              "walk_forward": {"train_weeks": a.train_weeks, "test_weeks": a.test_weeks, "min_train_trades": a.min_train_trades},
              "symbols": results}
    if a.portfolio and oos_all:
        combined = pd.concat(oos_all, ignore_index=True)
        trades = combined[["entry", "exit", "stop", "target", "risk_px", "entry_time", "exit_time", "reason",
                           "symbol", "side", "setup", "score", "session", "signal_time"]].to_dict("records")
        port = run_portfolio(trades, risk)
        report["portfolio_oos"] = {"summary": summarize(port, risk.start_equity),
                                   "by_symbol": breakdown(port, "symbol", risk.start_equity),
                                   "verdict": verdict(summarize(port, risk.start_equity))}
        print(json.dumps(report["portfolio_oos"], indent=1, default=str))
    out = REPORTS / f"walkforward_{'_'.join(a.symbols)}_{stamp}.json"
    out.write_text(json.dumps(report, indent=1, default=str))
    print("report:", out)


if __name__ == "__main__":
    main()
