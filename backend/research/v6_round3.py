"""TRADEden V6 round 3 (expanded mandate): market regimes, a regime-aware hybrid, two new
non-indicator families, instrument-specific analysis and multiple-testing control.

Same protocol as research/v6.py (TRAIN -> VALIDATION -> TEST once). Hypotheses, registered
before running:
  H-R1  Strategy performance depends on the market regime (trend strength x volatility), and a
        rule chosen on TRAIN that runs each family only in its positive regimes improves
        expectancy on VALIDATION (and then on TEST).
  H-R2  Cross-sectional momentum: instruments that outperformed peers (ATR-normalised 20/60-day
        return) keep outperforming over the next week.
  H-R3  H4 inside-bar breakout (price action): a break of the mother bar after a contraction
        bar starts a directional move.
  H-R4  Instrument selection: instruments that were profitable for the best family on TRAIN stay
        better than the others on VALIDATION. (Analysis only; no test scoring.)
Multiple testing: every configuration ever scored on TEST (rounds 1-3) gets a one-sided p-value
for expectancy > 0 from its test trades; Holm-Bonferroni across all of them is reported.

    python -m research.v6_round3
"""
from __future__ import annotations

import bisect
import json
import math
import statistics as st
from collections import defaultdict
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

from research import experiments as ex
from research import lab, v6
from research.metrics import summarize

MIN_CELL_TRAIN = 40


# ----- regimes (closed H1 bars at the decision time only) -------------------------------------------------

_REGIME: dict[str, Any] = {}


def regime(h, m15_index: int) -> str:
    """'TREND|RANGE|MIXED' + '/' + 'HIGH|NORMAL|LOW' volatility, from H1 bars closed before the M15 bar opens.
    Trend strength = |EMA50 now - EMA50 10 bars ago| / ATR14; volatility = ATR14 / median ATR14 of 100 bars."""
    c = v6.h1_context(h)
    if h.symbol not in _REGIME:
        _REGIME[h.symbol] = [b["utc"] for b in c["bars"]]
    utc = h.full["M15"][m15_index]["utc"]
    i = bisect.bisect_right(_REGIME[h.symbol], utc - 3600) - 1          # last H1 bar closed by then
    if i < 210 or not c["atr"][i]:
        return "UNKNOWN"
    a = c["atr"][i]
    strength = abs(c["ema50"][i] - c["ema50"][i - 10]) / a
    trend = "TREND" if strength > 0.5 else "RANGE" if strength < 0.25 else "MIXED"
    recent = [x for x in c["atr"][i - 100:i] if x]
    ratio = a / st.median(recent) if recent else 1.0
    vol = "HIGH" if ratio > 1.25 else "LOW" if ratio < 0.8 else "NORMAL"
    return f"{trend}/{vol}"


def tag(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for t in trades:
        t["regime"] = regime(lab.history_for(t["symbol"]), t["index"])
    return trades


# ----- candidate streams (each family at its best TRAIN configuration; production as deployed) -------------

def streams() -> dict[str, list[dict[str, Any]]]:
    out = {sid: lab.load_signals(sid) for sid in ex.PRODUCTION}
    out["Donchian H1 (N=20, 3 ATR, 2R)"] = v6.generate(lambda h: v6.donchian_trend(h, 20, 3.0, "fixed2", False))
    out["H1 pullback (2 ATR, trail2)"] = v6.generate(lambda h: v6.trend_pullback(h, 2.0, "trail2"))
    out["London ORB (3R, far, <=1.5 ATR)"] = v6.generate(lambda h: v6.opening_range_breakout(h, 3.0, "far", 1.5))
    out["H1 mean reversion (z=2.5, mean)"] = v6.generate(lambda h: v6.bollinger_reversion(h, 2.5, "mean"))
    out["H1 squeeze (0.1, trail3)"] = v6.generate(lambda h: v6.squeeze_breakout(h, 0.1, "trail3"))
    out["D1 TS momentum (60d, 3 ATR, trail3)"] = v6.generate(lambda h: v6.weekly_tsmom(h, 60, 3.0, "trail3"))
    for name, rows in out.items():
        for r in rows:
            r["strategy_id"] = name
    return out


def regime_tables(all_streams: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, dict[str, list]]]:
    tables, by_cell = {}, {}
    for name, sig in all_streams.items():
        cells: dict[str, dict[str, Any]] = {}
        trained = tag(v6.run(sig, v6.TRAIN))
        groups = defaultdict(list)
        for t in trained:
            groups[t["regime"]].append(t)
        for cell, rows in sorted(groups.items()):
            s = summarize(rows)
            cells[cell] = {"trades": s["trades"], "expectancy_r": s["expectancy_r"], "ci95": s["expectancy_ci95"]}
        tables[name] = cells
        by_cell[name] = groups
    return tables, by_cell


# ----- H-R1 regime-aware hybrid ------------------------------------------------------------------------

def hybrid_rule(tables: dict[str, Any]) -> dict[str, list[str]]:
    """Cells allowed per family, decided on TRAIN only: n >= MIN_CELL_TRAIN and the 95% CI lower
    bound above -0.05R with a positive point estimate (a deliberately strict bar, to limit
    selecting noise across ~10 families x 9 cells)."""
    rule = {}
    for name, cells in tables.items():
        ok = [c for c, s in cells.items() if c != "UNKNOWN" and s["trades"] >= MIN_CELL_TRAIN
              and (s["expectancy_r"] or 0) > 0 and s["ci95"][0] is not None and s["ci95"][0] > -0.05]
        if ok:
            rule[name] = ok
    return rule


def hybrid_trades(all_streams, rule, window) -> list[dict[str, Any]]:
    trades = []
    for name, cells in rule.items():
        allowed = set(cells)

        def keep(signal, h, allowed=allowed):
            return {} if regime(h, signal["index"]) in allowed else None
        trades += [dict(t, family=name) for t in v6.run(all_streams[name], window, keep)]
    return sorted(trades, key=lambda t: t["utc"])


# ----- H-R2 cross-sectional momentum --------------------------------------------------------------------

def cross_sectional_momentum(lookback: int, stop_atr: float, top: int = 3) -> list[dict[str, Any]]:
    """Weekly: rank the 16 instruments by their `lookback`-day return in D1-ATR units (closed D1 bars
    at the first D1 close of the week); BUY the top `top`, SELL the bottom `top`; stop k x D1 ATR;
    exit after one week. Market-neutral-ish across instruments; uses relative, not absolute, trend."""
    ctx = {s: v6.tf_context(lab.history_for(s), "D1") for s in lab.SYMBOLS}
    weeks: dict[tuple, dict[str, int]] = defaultdict(dict)
    for s, c in ctx.items():
        bars = c["bars"]
        for i in range(lookback + 1, len(bars) - 1):
            wk = datetime.fromtimestamp(bars[i]["utc"] + 86400, v6.UTC).isocalendar()[:2]
            prev = datetime.fromtimestamp(bars[i - 1]["utc"] + 86400, v6.UTC).isocalendar()[:2]
            if wk != prev and c["entry_index"][i] is not None and c["atr"][i]:
                weeks[wk][s] = i
    out = []
    for wk, members in weeks.items():
        if len(members) < 10:
            continue
        scores = []
        for s, i in members.items():
            c = ctx[s]
            score = (c["bars"][i]["close"] - c["bars"][i - lookback]["close"]) / c["atr"][i]
            scores.append((score, s, i))
        scores.sort()
        picks = [(s, i, False) for _, s, i in scores[:top]] + [(s, i, True) for _, s, i in scores[-top:]]
        for s, i, long in picks:
            h, c = lab.history_for(s), ctx[s]
            sig = v6._signal(h, c["entry_index"][i], "xsmom", long, stop_atr * c["atr"][i], 50.0, None, 5 * 96,
                             {"lookback": lookback})
            if sig:
                out.append(sig)
    return sorted(out, key=lambda r: (r["utc"], r["symbol"]))


# ----- H-R3 H4 inside-bar breakout -------------------------------------------------------------------------

def inside_bar_breakout(h, target_r: float, trend_filter: bool) -> list[dict[str, Any]]:
    """H4: bar i-1 inside bar i-2 (the mother); bar i closes beyond the mother's range -> enter at the
    next open in that direction; stop beyond the mother's opposite side; target fixed R; optional D1
    EMA50/EMA200 trend filter. Pure price action, no indicator in the trigger."""
    c, d = v6.tf_context(h, "H4"), v6.tf_context(h, "D1")
    bars = c["bars"]
    d_utc = [b["utc"] for b in d["bars"]]
    out = []
    for i in range(2, len(bars)):
        j = c["entry_index"][i]
        mother, inside, cur = bars[i - 2], bars[i - 1], bars[i]
        if j is None or not (inside["high"] <= mother["high"] and inside["low"] >= mother["low"]):
            continue
        long = cur["close"] > mother["high"]
        if not long and not cur["close"] < mother["low"]:
            continue
        if trend_filter:
            k = bisect.bisect_right(d_utc, cur["utc"] + c["seconds"] - 86400) - 1
            if k < 200 or (d["ema50"][k] > d["ema200"][k]) != long:
                continue
        m = h.full["M15"][j]
        entry = m["open"] + m["spread"] if long else m["open"]
        dist = (entry - mother["low"]) if long else (mother["high"] - entry)
        if dist <= 0:
            continue
        s = v6._signal(h, j, "insidebar", long, dist, target_r, None, 10 * 96, {})
        if s:
            out.append(s)
    return out


# ----- multiple testing --------------------------------------------------------------------------------

def one_sided_p(rs: list[float]) -> float | None:
    """P(mean <= 0) under a normal approximation of the mean of `rs` (n >= 30)."""
    n = len(rs)
    if n < 30:
        return None
    mean, sd = sum(rs) / n, st.pstdev(rs)
    if not sd:
        return None
    z = mean / (sd / math.sqrt(n))
    return 0.5 * math.erfc(z / math.sqrt(2))


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, running, out = len(ordered), 0.0, {}
    for k, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - k) * p))
        out[name] = round(running, 4)
    return out


# ----- driver --------------------------------------------------------------------------------------------

def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    out_path = lab.root() / "v6_round3_results.json"
    res: dict[str, Any] = {}

    def save():
        out_path.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")

    print("streams...", flush=True)
    all_streams = streams()
    print("regime tables (train)...", flush=True)
    tables, _ = regime_tables(all_streams)
    res["regime_tables_train"] = tables
    save()

    print("H-R1 regime-aware hybrid...", flush=True)
    rule = hybrid_rule(tables)
    res["hybrid_rule"] = rule
    train_h = hybrid_trades(all_streams, rule, v6.TRAIN)
    valid_h = hybrid_trades(all_streams, rule, v6.VALID)
    res["hybrid"] = {"train": v6.stats(train_h, v6.TRAIN), "validation": v6.stats(valid_h, v6.VALID)}
    if rule and (res["hybrid"]["validation"]["expectancy_r"] or 0) > 0 and res["hybrid"]["validation"]["trades"] >= v6.MIN_VALID:
        test_h = hybrid_trades(all_streams, rule, v6.TEST)
        res["hybrid"]["test"] = v6.stats(test_h, v6.TEST)
        res["hybrid"]["test_x2_costs"] = v6.stats(hybrid_trades_cost(all_streams, rule, v6.TEST), v6.TEST)
        res["hybrid"]["_test_rs"] = [t["r"] for t in test_h if t["r"] is not None]
        res["hybrid"]["portfolio_test"] = v6.portfolio({"hybrid": test_h})
    lab.record({"name": "V6 R3 regime-aware hybrid", "kind": "v6-r3", "hypothesis": "H-R1",
                **{k: v for k, v in res["hybrid"].items() if not k.startswith("_")}, "rule": rule})
    print(json.dumps({k: v for k, v in res["hybrid"].items() if not k.startswith("_")}, indent=1), flush=True)
    save()

    print("H-R2 / H-R3 new families...", flush=True)
    specs = {
        "Cross-sectional momentum (weekly)": {
            "rationale": "Relative (cross-sectional) momentum: instruments that outperformed peers keep outperforming over the next week.",
            "grid": {f"lookback {n}d, stop {k} ATR": (lambda n=n, k=k: cross_sectional_momentum(n, k))
                     for n, k in product((20, 60), (2.0, 3.0))}},
        "H4 inside-bar breakout": {
            "rationale": "Price action: a break of the mother bar after a contraction (inside) bar starts a directional move.",
            "grid": {f"target {r}R, {'D1 trend' if t else 'no filter'}": (lambda r=r, t=t: v6.generate(lambda h: inside_bar_breakout(h, r, t)))
                     for r, t in product((1.5, 2.0, 3.0), (True, False))}},
    }
    res["families"] = {}
    for family, spec in specs.items():
        sel = v6.select(family, spec, lambda m: print(m, flush=True))
        entry = {k: v for k, v in sel.items() if not k.startswith("_")}
        scored = v6.score_test(sel)
        if scored:
            scored["verdict"] = v6.verdict(scored)
            entry["test"] = {k: v for k, v in scored.items() if not k.startswith("_")}
            entry["_test_rs"] = [t["r"] for t in scored["_test_trades"] if t["r"] is not None]
            lab.record({"name": f"V6 R3 FINALIST {family}: {scored['config']}", "kind": "v6-test", "family": family,
                        **{k: v for k, v in scored.items() if not k.startswith("_")}})
            print(f"  TEST {family}: {json.dumps(scored['test'])} -> {scored['verdict']}", flush=True)
        res["families"][family] = entry
    save()

    print("H-R4 instrument selection (analysis only)...", flush=True)
    mr = all_streams["H1 mean reversion (z=2.5, mean)"]
    per = defaultdict(lambda: {"train": [], "validation": []})
    for name, w in (("train", v6.TRAIN), ("validation", v6.VALID)):
        for t in v6.run(mr, w):
            per[t["symbol"]][name].append(t)
    train_pos = {s for s, d in per.items() if d["train"] and summarize(d["train"])["expectancy_r"] > 0}
    sel_v = [t for s in train_pos for t in per[s]["validation"]]
    rest_v = [t for s, d in per.items() if s not in train_pos for t in d["validation"]]
    res["instrument_selection"] = {
        "family": "H1 mean reversion (z=2.5, mean)", "selected_on_train": sorted(train_pos),
        "validation_selected": v6.stats(sel_v), "validation_others": v6.stats(rest_v),
        "per_instrument": {s: {"train": summarize(d["train"])["expectancy_r"] if d["train"] else None,
                               "validation": summarize(d["validation"])["expectancy_r"] if d["validation"] else None,
                               "n_train": len(d["train"]), "n_validation": len(d["validation"])} for s, d in sorted(per.items())}}
    lab.record({"name": "V6 R3 instrument selection (H1 mean reversion)", "kind": "v6-r3", "hypothesis": "H-R4",
                **res["instrument_selection"]})
    print(json.dumps({k: v for k, v in res["instrument_selection"].items() if k != "per_instrument"}, indent=1), flush=True)
    save()

    print("multiple testing...", flush=True)
    v6res = json.loads((lab.root() / "v6_results.json").read_text(encoding="utf-8"))
    pvals = {}
    finals = {**v6res.get("finalists", {}), **v6res.get("finalists_round2", {})}
    for fam, f in finals.items():
        # Recompute the test trades for each previously scored finalist (same config, same window).
        sig = _rebuild(fam, f["config"])
        rs = [t["r"] for t in v6.run(sig, v6.TEST) if t["r"] is not None]
        pvals[f"{fam}: {f['config']}"] = one_sided_p(rs)
    for fam, e in res["families"].items():
        if e.get("_test_rs"):
            pvals[f"{fam}: {e['test']['config']}"] = one_sided_p(e["_test_rs"])
    if res["hybrid"].get("_test_rs"):
        pvals["Regime-aware hybrid"] = one_sided_p(res["hybrid"]["_test_rs"])
    pvals = {k: v for k, v in pvals.items() if v is not None}
    total_configs = sum(len(s["train"]) for s in v6res["selections"].values()) + \
        sum(len(e["train"]) for e in res["families"].values()) + 1
    res["multiple_testing"] = {"configurations_evaluated_all_rounds": total_configs,
                               "raw_one_sided_p": {k: round(v, 4) for k, v in pvals.items()},
                               "holm_adjusted_p": holm(pvals)}
    print(json.dumps(res["multiple_testing"], indent=1), flush=True)
    for e in res["families"].values():
        e.pop("_test_rs", None)
    res["hybrid"].pop("_test_rs", None)
    save()
    print(f"written {out_path}", flush=True)


def hybrid_trades_cost(all_streams, rule, window):
    trades = []
    for name, cells in rule.items():
        allowed = set(cells)
        trades += v6.run(all_streams[name], window, lambda s, h, a=allowed: {} if regime(h, s["index"]) in a else None,
                         cost_multiplier=2.0)
    return sorted(trades, key=lambda t: t["utc"])


def _rebuild(family: str, config: str) -> list[dict[str, Any]]:
    specs = {**v6.families(), **v6.round2_families()}
    return specs[family]["grid"][config]()


if __name__ == "__main__":
    main()
