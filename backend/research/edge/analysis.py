"""Descriptive analysis of edge-discovery-v1 AFTER the locked tournament (nothing here selects or promotes).

  null_check       how many validation p-values fall below 5% / 10% versus the number expected by chance
  persistence      does train expectancy predict out-of-sample expectancy across all trials? (rank correlation)
  selection_decay  mean train vs out-of-sample expectancy of the train-selected configurations
  exit_mechanics   out-of-sample expectancy / win rate by exit type, over every family x config with >= 30 OOS trades
  timeframes       the same by timeframe for the timeframe-agnostic families
  noise_ceiling    expected maximum out-of-sample expectancy among N pairs if no pair had any edge
  leads            the strongest out-of-sample results, with their peers on related instruments

    python -m research.edge.analysis        # writes data/research/edge/analysis.json
"""
from __future__ import annotations

import json
import multiprocessing
from collections import defaultdict
from typing import Any

import numpy as np

from research.edge import tournament as T
from research.edge.registry import FAMILIES


def _rank_corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 5:
        return None
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return round(float(np.corrcoef(ra, rb)[0, 1]), 3)


def main() -> None:
    board = json.loads((T.out_dir() / "tournament.json").read_text(encoding="utf-8"))
    with multiprocessing.Pool(len(T.SYMBOLS)) as pool:
        results = {r["symbol"]: r for r in pool.imap_unordered(T.pass1, T.SYMBOLS)}
    combos: dict[tuple, list] = defaultdict(list)
    for symbol, res in results.items():
        for row in res["trades"]:
            combos[(symbol, row[0], row[1], row[2])].append(row)
    cells = []
    for (symbol, fam, ci, ex), rows in combos.items():
        rows = T.busy_filter(rows)
        tr, oos = T.split(rows, "train"), T.split(rows, "validation") + T.split(rows, "test")
        if len(tr) < 30 or len(oos) < 30 or symbol not in T.TARGETS:
            continue
        s_tr, s_oos = T.stats(tr), T.stats(oos)
        tf = None
        if fam != "logit_h1":
            tf = next(x for x in FAMILIES if x["key"] == fam)["configs"][ci].get("tf")
        cells.append({"symbol": symbol, "family": fam, "config": ci, "exit": ex, "tf": tf, "train_e": s_tr["expectancy_r"],
                      "oos_e": s_oos["expectancy_r"], "oos_wr": s_oos["win_rate"], "oos_n": s_oos["trades"], "oos_pf": s_oos["profit_factor"]})
    lb = [b for b in board["leaderboard"]]
    p = [b["p_raw"] for b in lb]
    n = len(p)

    def agg(key):
        g: dict[str, list] = defaultdict(list)
        for c in cells:
            if c[key] is not None:
                g[str(c[key])].append(c)
        return {k: {"cells": len(v), "mean_oos_expectancy_r": round(float(np.mean([c["oos_e"] for c in v])), 4),
                    "median_oos_expectancy_r": round(float(np.median([c["oos_e"] for c in v])), 4),
                    "share_positive": round(sum(c["oos_e"] > 0 for c in v) / len(v), 3),
                    "mean_oos_win_rate": round(float(np.mean([c["oos_wr"] for c in v if c["oos_wr"] is not None])), 3)}
                for k, v in sorted(g.items())}

    new = [b for b in lb if b["kind"] == "new"]
    # noise ceiling: simulate the max of N independent null estimates with each pair's own standard error
    rng = np.random.default_rng(11)
    ses = []
    for b in lb:
        lo, hi = b["oos_ci95"]
        if lo is not None and hi is not None:
            ses.append((hi - lo) / 3.92)
    sims = [max(rng.normal(0, s) for s in ses) for _ in range(2000)]
    leads = []
    for b in lb[:8]:
        peers = {}
        sym, fam = b["symbol"], b["family"]
        for peer in T.PEERS.get(sym, []):
            if fam.startswith("existing:") or fam in ("regime_selector", "ensemble_2of_n"):
                continue
            ci = next((c["config"] for c in cells if c["symbol"] == sym and c["family"] == fam and c["exit"] == b["exit"]), None)
            rows = T.busy_filter([r for r in results[peer]["trades"] if r[0] == fam and r[2] == b["exit"] and (ci is None or r[1] == ci)])
            s = T.stats(T.split(rows, "validation") + T.split(rows, "test"))
            peers[peer] = {"trades": s["trades"], "expectancy_r": s["expectancy_r"]}
        leads.append({k: b[k] for k in ("pair", "exit", "oos_trades", "oos_win_rate", "oos_expectancy_r", "oos_ci95", "oos_profit_factor",
                                         "oos_2x_expectancy_r", "validation_expectancy_r", "test_expectancy_r", "quarters_positive",
                                         "p_raw", "holm_p", "random_control")} | {"peers": peers})
    out = {
        "null_check": {"pairs": n, "p_below_0.05": sum(x < 0.05 for x in p), "expected_by_chance_0.05": round(0.05 * n, 1),
                       "p_below_0.10": sum(x < 0.10 for x in p), "expected_by_chance_0.10": round(0.10 * n, 1),
                       "smallest_p": sorted(p)[:5]},
        "persistence": {"trials": len(cells), "rank_corr_train_vs_oos": _rank_corr([c["train_e"] for c in cells], [c["oos_e"] for c in cells]),
                        "share_train_positive_that_stay_positive": round(
                            sum(c["oos_e"] > 0 for c in cells if c["train_e"] > 0) / max(1, sum(c["train_e"] > 0 for c in cells)), 3),
                        "share_train_negative_that_turn_positive": round(
                            sum(c["oos_e"] > 0 for c in cells if c["train_e"] <= 0) / max(1, sum(c["train_e"] <= 0 for c in cells)), 3)},
        "selection_decay": {"new_family_pairs": len(new),
                            "mean_train_expectancy_selected": round(float(np.mean([b["train_expectancy_r"] for b in new])), 4),
                            "mean_oos_expectancy_selected": round(float(np.mean([b["oos_expectancy_r"] for b in new])), 4)},
        "exit_mechanics": agg("exit"), "timeframes": agg("tf"),
        "by_family": agg("family"), "by_symbol": agg("symbol"),
        "noise_ceiling": {"pairs": len(ses), "expected_max_oos_expectancy_if_no_edge": round(float(np.mean(sims)), 3),
                          "p95_max": round(float(np.percentile(sims, 95)), 3),
                          "observed_max": max(b["oos_expectancy_r"] for b in lb)},
        "leads": leads,
    }
    path = T.out_dir() / "analysis.json"
    path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("null_check", "persistence", "selection_decay", "noise_ceiling")}, indent=1))
    for k in ("exit_mechanics", "timeframes", "by_family", "by_symbol"):
        print("==", k)
        for name, v in out[k].items():
            print(f"  {name:28} cells={v['cells']:4} meanE={v['mean_oos_expectancy_r']:+.4f} medE={v['median_oos_expectancy_r']:+.4f} pos={v['share_positive']} WR={v['mean_oos_win_rate']}")
    for l in leads:
        print(l["pair"], l["exit"], l["oos_trades"], l["oos_expectancy_r"], l["oos_ci95"], "val", l["validation_expectancy_r"], "test", l["test_expectancy_r"], "q+", l["quarters_positive"], "peers", l["peers"])


if __name__ == "__main__":
    main()
