"""Walk-forward validation of the signal quality engine against the existing baseline.

Design (protects against look-ahead and overfitting):
  - expanding-window walk-forward: six test quarters from 2025-04-01 to 2026-10-12; each fold trains only
    on signals whose BASE trade had already EXITED before the test quarter starts (purged: no training
    label overlaps the test period)
  - inside each fold, per-strategy exit selection (target / stop variants) and the scorecard are fitted on
    the training rows only; the test quarter is scored once
  - grade thresholds and regime caps are fixed a priori (signal_quality/model.py), not tuned
  - all results net of spread, commission, stop slippage and financing; every policy is also re-run at 2x costs
  - a random-selection control keeps the same number of signals per test quarter at random (20 seeds):
    a quality filter must beat chance selection, not just the unfiltered baseline
  - one position per strategy and symbol is enforced AFTER filtering (a rejected signal never blocks a later one)

Policies compared on the same out-of-sample signals:
  baseline      every signal, the strategy's own entry, stop and target            (the current engine)
  exits_only    every signal, exit variant chosen per strategy on training data
  quality_A     base exits, only A+ / A grades (CONFIRMED)
  quality_B     base exits, A+ / A / B
  combined_A    chosen exits + scorecard trained on those exits, A+ / A only       (the proposed engine)
  combined_A_nocaps  as combined_A without regime / evidence caps                  (ablation)
  entry_confirm / entry_pullback  every signal with a confirmation-candle / pullback-limit entry (ablations)

    python -m research.quality_research      # writes data/research/quality/walk_forward.json and the model
"""
from __future__ import annotations

import json
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import math

import numpy as np

from research.metrics import BOOTSTRAP, MIN_TRADES, max_drawdown
from research.quality_dataset import TARGET_RS, load
from signal_quality.model import CONFIRMED_GRADES, FEATURES, QualityModel, form_bucket
from storage_config import data_directory

UTC = timezone.utc
START = datetime(2024, 10, 15, tzinfo=UTC).timestamp()
END = datetime(2026, 10, 12, tzinfo=UTC).timestamp()
TEST_STARTS = [datetime(y, m, 1, tzinfo=UTC).timestamp() for y, m in ((2025, 4), (2025, 7), (2025, 10), (2026, 1), (2026, 4), (2026, 7))]
EXIT_CANDIDATES = ("base", *TARGET_RS, "atr", "wide", "trail")
MIN_EXIT_TRADES = 200
MIN_EXIT_GAIN = 0.03
TARGETS = ("XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "US500", "GER40")
FORM_WINDOW = 40


def out_dir() -> Path:
    return data_directory() / "research" / "quality"


# ----- preparation ---------------------------------------------------------------------------------

def add_strategy_form(rows: list[dict[str, Any]]) -> None:
    """features.strategy_form = bucket of the mean base R of the strategy's last FORM_WINDOW signals that had
    EXITED before this signal's entry (causal)."""
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_strategy[r["strategy"]].append(r)
    for items in by_strategy.values():
        exits = sorted((r["outcomes"]["base"]["exit_utc"], r["outcomes"]["base"]["r"]) for r in items)
        items.sort(key=lambda r: r["utc"])
        done: list[float] = []
        k = 0
        for r in items:
            while k < len(exits) and exits[k][0] < r["utc"]:
                done.append(exits[k][1])
                k += 1
            r["features"]["strategy_form"] = form_bucket(done[-FORM_WINDOW:])


def outcome(row: dict[str, Any], variant: str, costs: int = 1) -> dict[str, Any] | None:
    o = row["outcomes"].get(variant)
    if not o or o.get("r") is None:
        return None
    return {"r": o["r"] if costs == 1 else o.get("r2"), "outcome": o["outcome"], "exit_index": o.get("exit_index"),
            "entry_index": o.get("entry_index", row["index"])}


def trade_list(rows: list[dict[str, Any]], choose: Callable[[dict[str, Any]], str | None], costs: int = 1) -> list[dict[str, Any]]:
    """Chronological trades: `choose(row)` returns the variant to trade, or None to skip. One open position
    per strategy and symbol; a skipped signal never blocks a later one."""
    busy: dict[tuple[str, str], int] = {}
    out = []
    for row in sorted(rows, key=lambda r: (r["utc"], r["symbol"], r["strategy"])):
        variant = choose(row)
        if variant is None:
            continue
        o = outcome(row, variant, costs)
        if o is None or o["r"] is None:
            continue
        key = (row["strategy"], row["symbol"])
        if o["entry_index"] <= busy.get(key, -1):
            continue
        busy[key] = o["exit_index"] if o["exit_index"] is not None else o["entry_index"]
        out.append({"utc": row["utc"], "symbol": row["symbol"], "strategy": row["strategy"], "r": o["r"],
                    "outcome": {"TRAIL": "TP"}.get(o["outcome"], o["outcome"]), "hold_hours": 0,
                    "session": row["features"]["session"], "regime": row["features"]["regime"],
                    "grade": row.get("_grade"), "variant": variant})
    return out


def months(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 1.0
    return max(1.0, (max(r["utc"] for r in rows) - min(r["utc"] for r in rows)) / 86400 / 30.44)


def stats(trades: list[dict[str, Any]], span_months: float | None = None) -> dict[str, Any]:
    """research.metrics.summarize semantics (ambiguous = stop, win = positive R) with a vectorised, seeded
    bootstrap so tens of thousands of trades can be summarised quickly."""
    rs = np.array([t["r"] for t in trades if t.get("r") is not None], dtype=float)
    n = len(rs)
    out: dict[str, Any] = {"trades": n, "sufficient": n >= MIN_TRADES}
    if not n:
        return out | {"win_rate": None, "expectancy_r": None, "expectancy_ci95": [None, None], "p_expectancy_positive": None,
                      "profit_factor": None, "total_r": 0.0, "max_drawdown_r": 0.0, "avg_win_r": None, "avg_loss_r": None,
                      "t_stat": None, "trades_per_month": None, "wins": 0, "losses": 0, "ambiguous": 0}
    ambiguous = np.array([t.get("outcome") == "AMBIGUOUS" for t in trades if t.get("r") is not None])
    wins = (rs > 0) & ~ambiguous
    losses = (rs <= 0) & ~ambiguous
    gross_loss = -rs[rs < 0].sum()
    rng = np.random.default_rng(7)
    if n >= 2:
        means = np.sort(np.concatenate([rs[rng.integers(0, n, size=(200, n))].mean(axis=1) for _ in range(BOOTSTRAP // 200)]))
        ci = [round(float(means[int(0.025 * len(means))]), 4), round(float(means[int(0.975 * len(means)) - 1]), 4)]
        p_pos = round(float((means > 0).mean()), 3)
        sd = float(rs.std(ddof=1))
    else:
        ci, p_pos, sd = [None, None], None, 0.0
    mean = float(rs.mean())
    return out | {
        "wins": int(wins.sum()), "losses": int(losses.sum()), "ambiguous": int(ambiguous.sum()),
        "win_rate": round(float(wins.sum() / (wins.sum() + losses.sum())), 4) if wins.sum() + losses.sum() else None,
        "expectancy_r": round(mean, 4), "expectancy_ci95": ci, "p_expectancy_positive": p_pos,
        "t_stat": round(mean / (sd / math.sqrt(n)), 2) if sd else None,
        "profit_factor": round(float(rs[rs > 0].sum() / gross_loss), 3) if gross_loss else None,
        "total_r": round(float(rs.sum()), 2), "max_drawdown_r": max_drawdown(rs.tolist()),
        "avg_win_r": round(float(rs[rs > 0].mean()), 3) if (rs > 0).any() else None,
        "avg_loss_r": round(float(rs[rs <= 0].mean()), 3) if (rs <= 0).any() else None,
        "trades_per_month": round(n / span_months, 1) if span_months else None,
    }


def by(trades: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any], keep=("trades", "win_rate", "expectancy_r", "profit_factor", "total_r", "max_drawdown_r", "sufficient")) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        groups[str(key(t))].append(t)
    out = {}
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = stats(v)
        out[k] = {x: s[x] for x in keep}
    return out


# ----- per-fold fitting ----------------------------------------------------------------------------

def choose_exits(train: list[dict[str, Any]]) -> dict[str, str]:
    """Per strategy: the exit variant with the best training expectancy, if it beats the strategy's own exit
    by at least MIN_EXIT_GAIN R on at least MIN_EXIT_TRADES trades; otherwise keep the strategy's own exit."""
    sums: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in train:
        for v in EXIT_CANDIDATES:
            o = row["outcomes"].get(v)
            if o and o.get("r") is not None:
                sums[(row["strategy"], v)].append(o["r"])
    choice = {}
    for strategy in {row["strategy"] for row in train}:
        base = sums.get((strategy, "base"), [])
        best, best_mean = "base", (sum(base) / len(base)) if base else 0.0
        for v in EXIT_CANDIDATES[1:]:
            values = sums.get((strategy, v), [])
            if len(values) >= MIN_EXIT_TRADES and sum(values) / len(values) >= best_mean + MIN_EXIT_GAIN:
                best, best_mean = v, sum(values) / len(values)
        choice[strategy] = best
    return choice


def fit(train: list[dict[str, Any]], exits: dict[str, str] | None) -> QualityModel:
    pairs = []
    for row in train:
        o = outcome(row, exits.get(row["strategy"], "base") if exits else "base")
        if o is not None and o["r"] is not None:
            pairs.append((row["features"], o["r"]))
    return QualityModel.fit(pairs, FEATURES, exits=exits)


def walk_forward(rows: list[dict[str, Any]], log: Callable[[str], None] = print) -> dict[str, Any]:
    folds_out = []
    graded: dict[str, list[dict[str, Any]]] = defaultdict(list)      # policy -> test rows with grade attached
    exits_per_fold = []
    bounds = TEST_STARTS + [END]
    for start, end in zip(bounds, bounds[1:]):
        train = [r for r in rows if START <= r["utc"] and r["outcomes"]["base"]["exit_utc"] < start]
        test = [r for r in rows if start <= r["utc"] < end]
        t0 = time.perf_counter()
        exits = choose_exits(train)
        m_base = fit(train, None)
        m_comb = fit(train, exits)
        for r in test:
            g_base = m_base.grade(r["features"])["grade"]
            g_comb = m_comb.grade(r["features"])
            g_nocap = m_comb.grade(r["features"], apply_caps=False)["grade"]
            graded["rows"].append({**r, "_fold": start, "_exit": exits.get(r["strategy"], "base"), "_g_base": g_base,
                                   "_grade": g_comb["grade"], "_g_nocap": g_nocap, "_expected": g_comb["expected_r"]})
        exits_per_fold.append({"test_from": datetime.fromtimestamp(start, UTC).date().isoformat(),
                               "changed": {k: v for k, v in sorted(exits.items()) if v != "base"}})
        folds_out.append({"test_from": datetime.fromtimestamp(start, UTC).date().isoformat(),
                          "test_to": datetime.fromtimestamp(end, UTC).date().isoformat(),
                          "train_signals": len(train), "test_signals": len(test)})
        log(f"  fold {folds_out[-1]['test_from']}: train={len(train)} test={len(test)} ({time.perf_counter() - t0:.0f}s)")
    return {"folds": folds_out, "exit_choices": exits_per_fold, "rows": graded["rows"]}


# ----- evaluation ----------------------------------------------------------------------------------

POLICIES: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "baseline": lambda r: "base",
    "exits_only": lambda r: r["_exit"],
    "quality_A": lambda r: "base" if r["_g_base"] in CONFIRMED_GRADES else None,
    "quality_B": lambda r: "base" if r["_g_base"] in ("A+", "A", "B") else None,
    "combined_A": lambda r: r["_exit"] if r["_grade"] in CONFIRMED_GRADES else None,
    "combined_B": lambda r: r["_exit"] if r["_grade"] in ("A+", "A", "B") else None,
    "combined_A_nocaps": lambda r: r["_exit"] if r["_g_nocap"] in CONFIRMED_GRADES else None,
    "entry_confirm": lambda r: "confirm",
    "entry_pullback": lambda r: "pullback",
}


def random_control(rows: list[dict[str, Any]], policy: str, seeds: int = 20) -> dict[str, Any]:
    """Pick, per test quarter, the same NUMBER of signals as `policy` selects, uniformly at random (with the
    policy's exits): does the scorecard beat chance selection?"""
    chosen = POLICIES[policy]
    per_fold: dict[float, int] = defaultdict(int)
    for r in rows:
        if chosen(r) is not None:
            per_fold[r["_fold"]] += 1
    means = []
    for seed in range(seeds):
        rng = random.Random(seed)
        keep = set()
        for fold, n in per_fold.items():
            ids = [id(r) for r in rows if r["_fold"] == fold]
            keep.update(rng.sample(ids, min(n, len(ids))))
        trades = trade_list(rows, lambda r: r["_exit"] if id(r) in keep else None)
        s = stats(trades)
        means.append(s["expectancy_r"])
    means.sort()
    return {"seeds": seeds, "expectancy_r_mean": round(sum(means) / len(means), 4),
            "expectancy_r_range": [means[0], means[-1]]}


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    span = months(rows)
    out: dict[str, Any] = {"policies": {}}
    for name, chosen in POLICIES.items():
        t1 = trade_list(rows, chosen)
        t2 = trade_list(rows, chosen, costs=2)
        signals = sum(1 for r in rows if chosen(r) is not None)
        s2 = stats(t2, span)
        out["policies"][name] = {"signals_selected": signals, "selection_rate": round(signals / len(rows), 4),
                                 "costs_1x": stats(t1, span), "costs_2x": {k: s2[k] for k in ("trades", "expectancy_r", "profit_factor", "total_r")},
                                 "by_fold": by(t1, lambda t: _fold_label(t["utc"]))}
    return out


def _fold_label(utc: float) -> str:
    starts = [s for s in TEST_STARTS if s <= utc]
    return datetime.fromtimestamp(starts[-1], UTC).date().isoformat() if starts else "before"


def grade_calibration(rows: list[dict[str, Any]], grade_key: str = "_grade", variant_key: str | None = "_exit") -> dict[str, Any]:
    """Per-signal realised expectancy by grade (no position filter): is the grade order monotone out of sample?"""
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        o = outcome(r, r[variant_key] if variant_key else "base")
        if o and o["r"] is not None:
            groups[r[grade_key]].append({"r": o["r"], "outcome": o["outcome"], "utc": r["utc"]})
    order = ("A+", "A", "B", "C", "REJECTED")
    out = {}
    for g in order:
        if g in groups:
            s = stats(sorted(groups[g], key=lambda t: t["utc"]))
            out[g] = {k: s[k] for k in ("trades", "win_rate", "expectancy_r", "profit_factor", "expectancy_ci95")}
    return out


def strategy_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Out-of-sample verdict per strategy (base exits, every signal) and with the proposed engine."""
    result = {}
    for strategy in sorted({r["strategy"] for r in rows}):
        mine = [r for r in rows if r["strategy"] == strategy]
        base = stats(trade_list(mine, POLICIES["baseline"]))
        comb = stats(trade_list(mine, POLICIES["quality_A"]))
        targets = stats(trade_list([r for r in mine if r["symbol"] in TARGETS], POLICIES["baseline"]))
        by_symbol = by(trade_list(mine, POLICIES["baseline"]), lambda t: t["symbol"], keep=("trades", "expectancy_r"))
        positive_symbols = sorted(k for k, v in by_symbol.items() if v["trades"] >= 50 and (v["expectancy_r"] or 0) > 0.05)
        e, lo = base["expectancy_r"] or 0, (base["expectancy_ci95"] or [None])[0]
        ce, cn = comb["expectancy_r"] or 0, comb["trades"]
        if base["trades"] < 100:
            verdict, why = "INSUFFICIENT EVIDENCE", f"{base['trades']} out-of-sample trades"
        elif e > 0 and lo is not None and lo > 0:
            verdict, why = "PROMOTE (candidate)", "positive out-of-sample expectancy with CI above zero; still requires forward validation"
        elif cn >= 50 and ce > 0.05 and (comb["expectancy_ci95"] or [0])[0] > 0:
            verdict, why = "RESTRICT TO QUALITY-GATED", "unprofitable unfiltered; positive with CI above zero only on A/A+ setups"
        elif cn >= 30 and ce > 0:
            verdict, why = "IMPROVE (quality-gated, unproven)", "positive only on A/A+ setups and not yet significant"
        elif positive_symbols:
            verdict, why = "RESTRICT TO INSTRUMENTS", f"positive only on {', '.join(positive_symbols)} (not significant)"
        elif e < -0.1:
            verdict, why = "DISABLE (keep records)", "clearly negative out of sample and no profitable gated subset"
        else:
            verdict, why = "DISABLE (keep records)", "no positive out-of-sample subset after costs"
        result[strategy] = {"baseline": {k: base[k] for k in ("trades", "win_rate", "avg_win_r", "avg_loss_r", "expectancy_r", "expectancy_ci95", "profit_factor", "max_drawdown_r")},
                            "quality_gated": {k: comb[k] for k in ("trades", "win_rate", "expectancy_r", "expectancy_ci95", "profit_factor", "max_drawdown_r")},
                            "target_instruments": {k: targets[k] for k in ("trades", "win_rate", "expectancy_r", "profit_factor")},
                            "by_symbol": by_symbol, "verdict": verdict, "reason": why}
    return result


def diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive (in-sample, whole history) answers to the audit questions, from base outcomes."""
    base = [(r, r["outcomes"]["base"]) for r in rows]
    stops = [(r, o) for r, o in base if o["outcome"] in ("SL", "AMBIGUOUS")]
    reached_1r = sum(1 for _, o in stops if (o.get("mfe") or 0) >= 1.0)
    reached_half = sum(1 for _, o in stops if (o.get("mfe") or 0) >= 0.5)
    instant = sum(1 for r, o in stops if o.get("exit_index") is not None and o["exit_index"] - r["index"] <= 4)
    rescued = sum(1 for r, _ in stops if (r["outcomes"].get("wide") or {}).get("outcome") == "TP")
    planned = defaultdict(list)
    for r, o in base:
        planned[r["features"].get("planned_rr")].append(o["r"])
    univariate = {}
    for name in FEATURES:
        if name in ("strategy", "symbol"):
            continue
        groups: dict[str, list[float]] = defaultdict(list)
        for r, o in base:
            groups[str(r["features"].get(name))].append(o["r"])
        univariate[name] = {k: {"n": len(v), "expectancy_r": round(sum(v) / len(v), 4)}
                            for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])) if len(v) >= 200}
    # duplicate pressure: another strategy, same symbol and direction, within one hour
    keyed: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for r in rows:
        keyed[(r["symbol"], r["direction"])].append((r["utc"], r["strategy"]))
    clustered = 0
    cluster_r, alone_r = [], []
    for r in rows:
        peers = keyed[(r["symbol"], r["direction"])]
        has = any(abs(u - r["utc"]) <= 3600 and s != r["strategy"] for u, s in peers[max(0, _bisect(peers, r["utc"] - 3600)):_bisect(peers, r["utc"] + 3601)])
        clustered += has
        (cluster_r if has else alone_r).append(r["outcomes"]["base"]["r"])
    mean = lambda v: round(sum(v) / len(v), 4) if v else None
    return {
        "signals": len(rows),
        "stops": len(stops),
        "stopped_after_reaching_1R": round(reached_1r / len(stops), 4),
        "stopped_after_reaching_0.5R": round(reached_half / len(stops), 4),
        "stopped_within_1h_of_entry": round(instant / len(stops), 4),
        "stops_that_reach_target_with_1.5x_stop": round(rescued / len(stops), 4),
        "expectancy_by_planned_rr": {k: {"n": len(v), "expectancy_r": mean(v)} for k, v in planned.items()},
        "univariate_expectancy": univariate,
        "clustered_signals_share": round(clustered / len(rows), 4),
        "clustered_expectancy_r": mean(cluster_r), "isolated_expectancy_r": mean(alone_r),
    }


def _bisect(peers: list[tuple[float, str]], utc: float) -> int:
    import bisect
    return bisect.bisect_left(peers, (utc, ""))


def main() -> None:
    t0 = time.perf_counter()
    rows = [r for r in load() if START <= r["utc"] < END]
    rows.sort(key=lambda r: r["utc"])
    add_strategy_form(rows)
    print(f"{len(rows)} signals loaded ({time.perf_counter() - t0:.0f}s)")
    wf = walk_forward(rows)
    oos = wf.pop("rows")
    target_rows = [r for r in oos if r["symbol"] in TARGETS]
    result: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "label": "HISTORICAL WALK-FORWARD (simulated on MT5 history, out-of-sample quarters; not live results)",
        "method": __doc__.split("Policies compared")[0].strip(),
        "data": {"signals": len(rows), "out_of_sample_signals": len(oos), "from": "2024-10-15", "to": "2026-10-12"},
        "folds": wf["folds"], "exit_choices": wf["exit_choices"],
        "all_instruments": evaluate(oos),
        "target_instruments": evaluate(target_rows),
        "grade_calibration": {"base_exits": grade_calibration(oos, "_g_base", None), "combined": grade_calibration(oos),
                              "target_instruments": grade_calibration(target_rows, "_g_base", None)},
        "random_control": {"combined_A": random_control(oos, "combined_A"), "quality_A": random_control(oos, "quality_A")},
    }
    base_t = trade_list(oos, POLICIES["baseline"])
    comb_t = trade_list(oos, POLICIES["quality_A"])
    tb, tc = trade_list(target_rows, POLICIES["baseline"]), trade_list(target_rows, POLICIES["quality_A"])
    result["breakdowns"] = {
        name: {"baseline": by(b, key), "quality_A": by(c, key)}
        for name, key, b, c in (("symbol", lambda t: t["symbol"], base_t, comb_t),
                                ("strategy", lambda t: t["strategy"], base_t, comb_t),
                                ("session", lambda t: t["session"], base_t, comb_t),
                                ("regime", lambda t: t["regime"], base_t, comb_t),
                                ("month", lambda t: datetime.fromtimestamp(t["utc"], UTC).strftime("%Y-%m"), base_t, comb_t),
                                ("target_symbol", lambda t: t["symbol"], tb, tc),
                                ("target_strategy", lambda t: t["strategy"], tb, tc))}
    result["strategy_status"] = strategy_status(oos)
    result["diagnostics"] = diagnostics(rows)
    # Final model on all history, for production annotation. It is fitted on the strategies' OWN exits: the
    # walk-forward shows the A/A+ gate on own exits (quality_A) at least as good as the gate combined with
    # per-strategy exit changes (combined_A), so exit changes stay advisory (model.exits) and unapplied.
    exits = choose_exits(rows)
    final = QualityModel.fit([(r["features"], r["outcomes"]["base"]["r"]) for r in rows],
                             FEATURES, exits=exits,
                             meta={"trained_from": "2024-10-15", "trained_to": "2026-10-12", "signals": len(rows),
                                   "evidence": "research/quality_research.py walk-forward; see docs/SIGNAL_QUALITY_REPORT.md"})
    path = final.save()
    result["final_model"] = {"path": str(path), "exits": {k: v for k, v in sorted(exits.items()) if v != "base"},
                             "top_effects": {f: dict(sorted(t.items(), key=lambda kv: kv[1])[:2] + sorted(t.items(), key=lambda kv: kv[1])[-2:])
                                             for f, t in final.effects.items()}}
    out = out_dir() / "walk_forward.json"
    out.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    for scope in ("all_instruments", "target_instruments"):
        print(f"== {scope}")
        for name, p in result[scope]["policies"].items():
            s, s2 = p["costs_1x"], p["costs_2x"]
            print(f"  {name:18} sel={p['selection_rate']:.3f} n={s['trades']:6} WR={s['win_rate']} E={s['expectancy_r']} CI={s['expectancy_ci95']} "
                  f"PF={s['profit_factor']} DD={s['max_drawdown_r']} tot={s['total_r']} | 2x E={s2['expectancy_r']} PF={s2['profit_factor']}")
    print("random control", result["random_control"])
    print("calibration", json.dumps(result["grade_calibration"]["base_exits"]))
    print(f"written {out} ({time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()
