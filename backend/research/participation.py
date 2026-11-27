"""Strategy participation, quality, regime, diversification and allocation report (TRADEDEN V7).

Answers, for EVERY strategy TRADEDEN runs (the live scanner registry and the strategy bank):
  how much it participates      setups detected, confirmed, active, TP / SL / expired / invalidated,
                                signals per week, confirmation rate (live production stores)
  why it does or does not       the confirmation funnel: which gate rejects its setups
                                (live observations, a no-look-ahead replay sample, bank gate counters)
  whether it is any good        historical evaluation after costs (development / untouched test,
                                walk-forward folds, doubled costs, 95% CI, evidence tier)
  where it works                performance in each of eight market regimes (market_regime.py) and
                                whether it does better inside the regimes it is designed for
  whether it is independent     signal overlap, entry similarity, directional agreement, outcome
                                correlation and shared exposure between every pair of strategies
  what it has earned            the advisory allocation class (strategy_bank/allocation.py)

Quantity is reported but never rewarded: classifications are defined on evidence, and "high volume,
low quality" is an explicit flag. Nothing here changes a strategy, a deployment status, an alert or
an execution permission; it reads stores and research outputs and writes
data/strategy_bank/participation.json (read by GET /api/intelligence/participation).

Inputs (all produced elsewhere, never fabricated here):
  data/setup_observations.jsonl, setup_confirmations.jsonl, signal_outcomes.jsonl, setup_lifecycle.jsonl
  data/strategy_bank/signals.jsonl                         live bank signals and outcomes
  data/strategy_bank/intel.json + baselines/<date>/         historical evaluation and its trades
  data/research/v7_variants.json + v7_trades.jsonl.gz       live TM / SMC historical replay (research.v7_variants)

    python -m research.participation                     # full report
    python -m research.participation --obs-tail-mb 1500  # live funnel from the last 1.5 GB of observations
    python -m research.participation --label before       # also freeze a copy as participation_<label>.json
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import json
import math
import multiprocessing
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

UTC = timezone.utc
STAGES = ("DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE", "RESOLVED")
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}
FINAL_WIN, FINAL_LOSS = ("TARGET_HIT",), ("STOP_HIT",)
TIER_ORDER = ["PRODUCTION", "VALIDATED", "RESEARCH", "EXPERIMENTAL", "SUSPENDED"]

from market_regime import STRATEGY_FAMILY as FAMILY  # noqa: E402  (methodology taxonomy, shared with the live bank)
LIVE_NAMES = {"trendline_v5": "Trendline (break-retest & bounce)", "support_resistance": "Support & Resistance levels",
              "trend_momentum": "Trend / Momentum pullback", "smc": "Smart Money Concepts confluence"}
# Historical keys behind each live scanner strategy (the trendline is evaluated per family).
LIVE_HISTORY = {"trendline_v5": ("trendline_break_retest", "trendline_bounce"), "support_resistance": ("support_resistance",),
                "trend_momentum": ("tm_A_capped",), "smc": ("smc_A_v1",)}

# Classification thresholds (fixed, round, documented in docs/STRATEGY_PARTICIPATION.md).
DOMINANT_SHARE_X, DOMINANT_MIN_SHARE = 2.0, 0.25
UNDER_SHARE_X = 0.25
FILTER_RATE, FILTER_MIN_SETUPS, FILTER_TOP_SHARE = 0.05, 50, 0.5
HV_PERCENTILE, LQ_EXPECTANCY = 75, -0.10
OVERLAP_WINDOW_BARS = 4            # same symbol + direction within 1 hour (4 M15 bars) = the same opportunity
CLUSTER_CORR, CLUSTER_OVERLAP = 0.5, 0.5


def data_dir() -> Path:
    from storage_config import data_directory
    return data_directory()


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("rb") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def _ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ------------------------------------------------------------------ statistics

def _bootstrap(rs: list[float], seed: int = 7, b: int = 4000) -> tuple[float | None, float | None]:
    if len(rs) < 2:
        return None, None
    v = np.asarray(rs, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(b)
    for k in range(0, b, 500):
        m = min(500, b - k)
        means[k:k + m] = v[rng.integers(0, len(v), size=(m, len(v)))].mean(axis=1)
    means.sort()
    return round(float(means[int(0.025 * b)]), 4), round(float(means[int(0.975 * b) - 1]), 4)


def perf(rs: list[float], months: float | None = None, ci: bool = True) -> dict[str, Any]:
    rs = [float(r) for r in rs if r is not None and math.isfinite(float(r))]
    if not rs:
        return {"trades": 0, "win_rate": None, "expectancy_r": None, "expectancy_ci95": [None, None], "profit_factor": None,
                "total_r": 0.0, "max_drawdown_r": 0.0, "trades_per_month": None}
    gw, gl = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"trades": len(rs), "win_rate": round(sum(1 for r in rs if r > 0) / len(rs), 4),
            "expectancy_r": round(sum(rs) / len(rs), 4), "expectancy_ci95": list(_bootstrap(rs)) if ci else [None, None],
            "profit_factor": round(gw / gl, 3) if gl else None, "total_r": round(sum(rs), 2), "max_drawdown_r": round(dd, 2),
            "trades_per_month": round(len(rs) / months, 2) if months else None}


# ------------------------------------------------------------------ live: scanner registry

def scan_observations(path: Path, tail_bytes: int | None = None) -> dict[str, dict[str, Any]]:
    """Per strategy: episodes by the highest lifecycle stage they reached, observation states and the
    confirmation rules that failed. A binary line scan (the file is several GB); only three fields are
    extracted per line, plus the failed-rule list of setups that reached CONFIRMING."""
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"episodes": {}, "states": Counter(), "failed": Counter(),
                                                          "qual_failed": Counter(), "observations": 0, "first": None, "last": None})
    if not path.exists():
        return {}
    key_sid, key_sid2, key_state, key_at = b'"setup_id":"', b'"strategy_id":"', b'"lifecycle_state":"', b'"observed_at":"'

    def field(line: bytes, key: bytes) -> str | None:
        i = line.find(key)
        if i < 0:
            return None
        j = line.find(b'"', i + len(key))
        return line[i + len(key):j].decode("ascii", "replace")
    size = path.stat().st_size
    with path.open("rb") as fh:
        if tail_bytes and tail_bytes < size:
            fh.seek(size - tail_bytes)
            fh.readline()
        for line in fh:
            sid = field(line, key_sid2) or "trendline"
            setup, state = field(line, key_sid), field(line, key_state)
            if not setup or not state:
                continue
            s = out[sid]
            s["observations"] += 1
            s["states"][state] += 1
            at = field(line, key_at)
            if at:
                s["first"] = s["first"] or at
                s["last"] = at
            if STAGE_RANK.get(state, -1) > STAGE_RANK.get(s["episodes"].get(setup, ""), -1):
                s["episodes"][setup] = state
            if state == "CONFIRMING":
                m = re.search(rb'"confirmation":\{"rules":\{[^}]*\},"passed":(?:true|false),"failed":\[([^\]]*)\]', line)
                if m:
                    for name in re.findall(rb'"([^"]+)"', m.group(1)):
                        s["failed"][name.decode()] += 1
                q = re.search(rb'"qualification":\{"version":"[^"]*","qualified":false,"failed":\[([^\]]*)\]', line)
                if q:
                    s["qual_failed"][",".join(x.decode() for x in re.findall(rb'"([^"]+)"', q.group(1)))] += 1
    result = {}
    for sid, s in out.items():
        stages = Counter(s["episodes"].values())
        reached = lambda floor: sum(n for st, n in stages.items() if STAGE_RANK.get(st, -1) >= STAGE_RANK[floor])  # noqa: E731
        result[sid] = {"observations": s["observations"], "episodes": len(s["episodes"]),
                       "reached": {st: reached(st) for st in ("DEVELOPING", "CONFIRMING", "CONFIRMED")},
                       "states": dict(s["states"]), "failed_rules": dict(s["failed"].most_common(12)),
                       "qualification_failed": dict(s["qual_failed"].most_common(6)), "first": s["first"], "last": s["last"],
                       "window": "tail" if tail_bytes else "full"}
    return result


def live_scanner(base: Path, now: float) -> dict[str, dict[str, Any]]:
    """Confirmed signals, outcomes and lifecycle terminations per live scanner strategy."""
    from strategies.base import record_strategy_id
    conf: dict[str, dict[str, Any]] = {}
    for r in _rows(base / "setup_confirmations.jsonl"):
        conf[str(r.get("setup_id"))] = {"strategy": record_strategy_id(r), "at": _ts(r.get("confirmed_at")),
                                        "symbol": r.get("symbol"), "direction": r.get("direction")}
    latest: dict[str, dict[str, Any]] = {}
    for r in _rows(base / "signal_outcomes.jsonl"):
        k = str(r.get("setup_id"))
        if k not in latest or (r.get("revision") or 0) >= (latest[k].get("revision") or 0):
            latest[k] = r
    terminal: dict[str, str] = {}
    for r in _rows(base / "setup_lifecycle.jsonl"):
        k = str(r.get("setup_id"))
        if k in conf and r.get("to_state") in ("EXPIRED", "INVALIDATED", "RESOLVED"):
            terminal[k] = r["to_state"]
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"confirmed": 0, "symbols": set(), "rs": [], "status": Counter(),
                                                          "terminal": Counter(), "first": None, "last": None, "shadow": 0})
    for k, c in conf.items():
        s = out[c["strategy"]]
        s["confirmed"] += 1
        s["symbols"].add(c["symbol"])
        if c["at"]:
            s["first"] = min(s["first"] or c["at"], c["at"])
            s["last"] = max(s["last"] or c["at"], c["at"])
        o = latest.get(k)
        status = (o or {}).get("status") or "PENDING"
        s["status"][status] += 1
        if o and o.get("shadow"):
            s["shadow"] += 1
        if status in FINAL_WIN + FINAL_LOSS and o.get("r_multiple") is not None:
            s["rs"].append((c["at"] or 0, float(o["r_multiple"])))
        if k in terminal:
            s["terminal"][terminal[k]] += 1
    result = {}
    for sid, s in out.items():
        rs = [r for _, r in sorted(s["rs"])]
        weeks = max(1.0, ((now - s["first"]) / 604800.0)) if s["first"] else None
        result[sid] = {"confirmed": s["confirmed"], "active": s["status"].get("PENDING", 0),
                       "tp": s["status"].get("TARGET_HIT", 0), "sl": s["status"].get("STOP_HIT", 0),
                       "unavailable": s["status"].get("UNAVAILABLE", 0), "time_exit": 0,
                       "expired": s["terminal"].get("EXPIRED", 0), "invalidated": s["terminal"].get("INVALIDATED", 0),
                       "instruments": sorted(x for x in s["symbols"] if x),
                       "signals_per_week": round(s["confirmed"] / weeks, 2) if weeks else None,
                       "first": datetime.fromtimestamp(s["first"], UTC).isoformat() if s["first"] else None,
                       "last": datetime.fromtimestamp(s["last"], UTC).isoformat() if s["last"] else None,
                       **{k: v for k, v in perf(rs, ci=len(rs) >= 10).items() if k != "trades_per_month"}, "resolved": len(rs)}
    return result


def live_bank(now: float) -> dict[str, dict[str, Any]]:
    from strategy_bank import engine
    store = engine.BankStore()
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in store.signals.values():
        by[s["strategy_key"]].append(s)
    out = {}
    for key, rows in by.items():
        rows.sort(key=lambda r: r.get("confirmed_at") or "")
        st = Counter(r.get("outcome_status") or "PENDING" for r in rows)
        rs = [float(r["r_multiple"]) for r in rows if r.get("outcome_status") in ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")
              and r.get("r_multiple") is not None]
        first = _ts(rows[0].get("confirmed_at"))
        weeks = max(1.0, (now - first) / 604800.0) if first else None
        out[key] = {"confirmed": len(rows), "active": st.get("PENDING", 0), "tp": st.get("TARGET_HIT", 0), "sl": st.get("STOP_HIT", 0),
                    "time_exit": st.get("TIME_EXIT", 0), "unavailable": st.get("UNAVAILABLE", 0) + st.get("NO_HIT", 0),
                    "expired": st.get("TIME_EXIT", 0), "invalidated": 0,
                    "instruments": sorted({r["symbol"] for r in rows}), "signals_per_week": round(len(rows) / weeks, 2) if weeks else None,
                    "first": rows[0].get("confirmed_at"), "last": rows[-1].get("confirmed_at"),
                    **{k: v for k, v in perf(rs, ci=len(rs) >= 10).items() if k != "trades_per_month"}, "resolved": len(rs)}
    return out


# ------------------------------------------------------------------ replay funnel (live scanner strategies)

def _reason_key(reason: str | None) -> str:
    text = re.sub(r"[-+]?\d+(\.\d+)?", "#", reason or "")
    return re.split(r"[(;:]", text)[0].strip()[:80] or "-"


def _funnel_symbol(args: tuple[str, float, float]) -> tuple[str, dict[str, dict[str, Any]]]:
    symbol, start, end = args
    from research.replay import SymbolHistory, production_setup
    from research import experiments
    h = SymbolHistory.load(symbol)
    strategies = {sid: experiments.strategy(sid) for sid in LIVE_HISTORY}
    out = {sid: {"bars": 0, "states": Counter(), "no_setup": Counter(), "confirming_failed": Counter(),
                 "qualification": Counter(), "confirmed_bars": 0, "onsets": 0} for sid in strategies}
    prev: dict[str, str | None] = {sid: None for sid in strategies}
    full = h.full["M15"]
    for i in range(h.first_index(), len(full)):
        u = full[i]["utc"]
        if u < start:
            continue
        if u >= end:
            break
        built = h.market_input(i)
        if built is None:
            prev = {sid: None for sid in strategies}
            continue
        for sid, s in strategies.items():
            o = out[sid]
            st = production_setup(s, *built)
            o["bars"] += 1
            state = (st or {}).get("state") or "ERROR"
            o["states"][state] += 1
            valid = bool(st and st.get("strategy_valid") is True)
            if state == "NO SETUP":
                o["no_setup"][_reason_key(st.get("reason"))] += 1
            if state == "CONFIRMING" and not valid:
                conf = ((st.get("strategy_evidence") or {}).get("confirmation") or {}) if isinstance(st.get("strategy_evidence"), dict) else {}
                failed = conf.get("failed") or []
                if failed:
                    for x in failed:
                        o["confirming_failed"][x] += 1
                elif st.get("strategy_signal_valid"):
                    o["qualification"][",".join((st.get("qualification") or {}).get("failed") or [])] += 1
                else:
                    o["confirming_failed"]["strategy confirmation gate (no per-rule breakdown)"] += 1
            if valid:
                o["confirmed_bars"] += 1
            d = st.get("direction") if valid else None
            if valid and d != prev[sid]:
                o["onsets"] += 1
            prev[sid] = d
    return symbol, {sid: {**o, "states": dict(o["states"]), "no_setup": dict(o["no_setup"]),
                          "confirming_failed": dict(o["confirming_failed"]), "qualification": dict(o["qualification"])}
                    for sid, o in out.items()}


def replay_funnel(start: datetime, end: datetime, workers: int = 16) -> dict[str, Any]:
    from research import lab
    total: dict[str, dict[str, Any]] = {}
    with multiprocessing.Pool(min(workers, len(lab.SYMBOLS))) as pool:
        for _, res in pool.imap_unordered(_funnel_symbol, [(s, start.timestamp(), end.timestamp()) for s in lab.SYMBOLS]):
            for sid, o in res.items():
                t = total.setdefault(sid, {"bars": 0, "confirmed_bars": 0, "onsets": 0, "states": Counter(), "no_setup": Counter(),
                                           "confirming_failed": Counter(), "qualification": Counter()})
                for k in ("bars", "confirmed_bars", "onsets"):
                    t[k] += o[k]
                for k in ("states", "no_setup", "confirming_failed", "qualification"):
                    t[k].update(o[k])
    out = {}
    for sid, t in total.items():
        confirming = t["states"].get("CONFIRMING", 0)
        out[sid] = {"window": [start.date().isoformat(), end.date().isoformat()], "bars_evaluated": t["bars"],
                    "states": dict(t["states"]), "confirming_bars": confirming, "confirmed_bars": t["confirmed_bars"],
                    "signal_onsets": t["onsets"],
                    "confirmation_rate": round(t["confirmed_bars"] / confirming, 4) if confirming else None,
                    "top_no_setup_reasons": t["no_setup"].most_common(8),
                    "confirming_rejections": t["confirming_failed"].most_common(8),
                    "qualification_rejections": t["qualification"].most_common(5)}
    return out


# ------------------------------------------------------------------ historical trades

def load_trades(bank: Path, research_root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple, float]]:
    """{strategy: trades} from the frozen baseline and the V7 live-strategy replay, plus entries by
    (strategy, symbol, index) for entry-similarity."""
    trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    entries: dict[tuple, float] = {}
    baselines = sorted((bank / "baselines").glob("*/trades.jsonl.gz"))
    if baselines:
        folder = baselines[-1].parent
        with gzip.open(folder / "trades.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                t = json.loads(line)
                trades[t["strategy"]].append(t)
        if (folder / "signals.jsonl.gz").exists():
            with gzip.open(folder / "signals.jsonl.gz", "rt", encoding="utf-8") as fh:
                for line in fh:
                    s = json.loads(line)
                    if s.get("entry") is not None:
                        entries[(s["strategy"], s["symbol"], s["index"])] = float(s["entry"])
    v7 = research_root / "v7_trades.jsonl.gz"
    if v7.exists():
        with gzip.open(v7, "rt", encoding="utf-8") as fh:
            for line in fh:
                t = json.loads(line)
                trades[t["strategy"]].append(t)
                if t.get("entry") is not None:
                    entries[(t["strategy"], t["symbol"], t["index"])] = float(t["entry"])
    for rows in trades.values():
        rows.sort(key=lambda t: (t["utc"], t["symbol"]))
    return dict(trades), entries


def regime_tags(trades: dict[str, list[dict[str, Any]]]) -> None:
    """Tag every historical trade with the eight-regime label known at its entry (in place)."""
    import market_regime
    from research import lab
    from strategy_bank import rules
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rows in trades.values():
        for t in rows:
            by_symbol[t["symbol"]].append(t)
    for symbol, rows in by_symbol.items():
        h = lab.history_for(symbol)
        ctx = rules.Ctx(symbol, {tf: h.full[tf] for tf in ("H1", "H4")})
        labels = market_regime.label_array(ctx)
        for t in rows:
            i = ctx.last_closed("H1", float(t["utc"]))
            t["regime8"] = str(labels[i]) if i >= market_regime.MIN_INDEX else "UNKNOWN"


def regime_report(rows: list[dict[str, Any]], family: str) -> dict[str, Any]:
    import market_regime
    by: dict[str, list[float]] = defaultdict(list)
    for t in rows:
        if t.get("r") is not None:
            by[t.get("regime8", "UNKNOWN")].append(float(t["r"]))
    table = {g: {k: v for k, v in perf(rs, ci=False).items() if k in ("trades", "win_rate", "expectancy_r", "profit_factor", "total_r")}
             for g, rs in by.items()}
    design = market_regime.SUITABILITY.get(family, ())
    inside = [r for g, rs in by.items() if g in design for r in rs]
    outside = [r for g, rs in by.items() if g not in design and g != "UNKNOWN" for r in rs]
    pi, po = perf(inside, ci=len(inside) >= 30), perf(outside, ci=len(outside) >= 30)
    best = max(((g, v) for g, v in table.items() if g != "UNKNOWN" and v["trades"] >= 30), key=lambda x: x[1]["expectancy_r"], default=(None, None))[0]
    return {"by_regime": table, "designed_for": list(design),
            "inside_design": {k: pi[k] for k in ("trades", "expectancy_r", "expectancy_ci95", "profit_factor")},
            "outside_design": {k: po[k] for k in ("trades", "expectancy_r", "expectancy_ci95", "profit_factor")},
            "share_inside_design": round(len(inside) / max(1, len(inside) + len(outside)), 3), "best_regime": best,
            "regime_fit": (None if pi["expectancy_r"] is None or po["expectancy_r"] is None else
                           "BETTER_IN_DESIGN" if pi["expectancy_r"] > po["expectancy_r"] else "NOT_BETTER_IN_DESIGN")}


# ------------------------------------------------------------------ diversification

def diversification(trades: dict[str, list[dict[str, Any]]], entries: dict[tuple, float], keys: list[str],
                    min_trades: int = 30) -> dict[str, Any]:
    keys = [k for k in keys if len(trades.get(k, [])) >= min_trades]
    days = sorted({int(t["utc"] // 86400) for k in keys for t in trades[k]})
    di = {d: n for n, d in enumerate(days)}
    daily = {}
    for k in keys:
        v = np.zeros(len(days))
        for t in trades[k]:
            if t.get("r") is not None:
                v[di[int(t["utc"] // 86400)]] += float(t["r"])
        daily[k] = v
    index: dict[str, dict[str, tuple[list[int], list[dict]]]] = {}
    for k in keys:
        per: dict[str, list[dict]] = defaultdict(list)
        for t in trades[k]:
            per[t["symbol"]].append(t)
        index[k] = {s: ([t["index"] for t in sorted(rows, key=lambda x: x["index"])], sorted(rows, key=lambda x: x["index"]))
                    for s, rows in per.items()}

    def match(a: str, b: str) -> dict[str, Any]:
        same = opposite = 0
        price_diffs: list[float] = []
        agree = disagree = 0
        exposure = 0
        bars_a = sum(max(1, (t.get("exit_index") or t["index"]) - t["index"]) for t in trades[a])
        bars_b = sum(max(1, (t.get("exit_index") or t["index"]) - t["index"]) for t in trades[b])
        for sym, (idx_a, rows_a) in index[a].items():
            if sym not in index[b]:
                continue
            idx_b, rows_b = index[b][sym]
            for t in rows_a:
                lo = bisect.bisect_left(idx_b, t["index"] - OVERLAP_WINDOW_BARS)
                hi = bisect.bisect_right(idx_b, t["index"] + OVERLAP_WINDOW_BARS)
                near = rows_b[lo:hi]
                if any(u["direction"] == t["direction"] for u in near):
                    same += 1
                    u = next(u for u in near if u["direction"] == t["direction"])
                    ea, eb = entries.get((a, sym, t["index"])), entries.get((b, sym, u["index"]))
                    if ea and eb:
                        price_diffs.append(abs(ea - eb) / ea * 1e4)
                elif near:
                    opposite += 1
            # shared exposure and directional agreement over overlapping holding intervals
            j = 0
            for t in rows_a:
                s0, s1 = t["index"], max(t["index"] + 1, t.get("exit_index") or t["index"] + 1)
                while j < len(rows_b) and max(rows_b[j]["index"] + 1, rows_b[j].get("exit_index") or 0) <= s0:
                    j += 1
                k = j
                while k < len(rows_b) and rows_b[k]["index"] < s1:
                    u = rows_b[k]
                    ov = min(s1, max(u["index"] + 1, u.get("exit_index") or u["index"] + 1)) - max(s0, u["index"])
                    if ov > 0:
                        exposure += ov
                        if u["direction"] == t["direction"]:
                            agree += 1
                        else:
                            disagree += 1
                    k += 1
        na, nb = len(trades[a]), len(trades[b])
        x, y = daily[a], daily[b]
        active = (x != 0) | (y != 0)
        corr = None
        if active.sum() >= 30 and np.std(x[active]) > 0 and np.std(y[active]) > 0:
            corr = round(float(np.corrcoef(x[active], y[active])[0, 1]), 3)
        return {"a": a, "b": b, "overlap_a": round(same / na, 3), "overlap_b": round(same / nb, 3),
                "overlap_jaccard": round(same / max(1, na + nb - same), 3), "conflicts": opposite,
                "entry_diff_bps_median": round(float(np.median(price_diffs)), 2) if price_diffs else None,
                "directional_agreement": round(agree / (agree + disagree), 3) if agree + disagree else None,
                "shared_exposure": round(exposure / max(1, min(bars_a, bars_b)), 3), "outcome_corr": corr}

    pairs = [match(a, b) for n, a in enumerate(keys) for b in keys[n + 1:]]
    # Near-duplicate clusters (union-find on outcome correlation or same-opportunity overlap).
    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for p in pairs:
        if (p["outcome_corr"] or 0) >= CLUSTER_CORR or max(p["overlap_a"], p["overlap_b"]) >= CLUSTER_OVERLAP:
            parent[find(p["a"])] = find(p["b"])
    groups: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    clusters = sorted(groups.values(), key=len, reverse=True)
    cluster_of = {k: n for n, g in enumerate(clusters) for k in g}
    mat = np.array([daily[k] for k in keys]) if keys else np.zeros((0, 0))
    n_eff = None
    if len(keys) >= 2:
        c = np.corrcoef(mat)
        c = np.nan_to_num(c, nan=0.0)
        lam = np.clip(np.linalg.eigvalsh(c), 0, None)
        n_eff = round(float(lam.sum() ** 2 / (lam ** 2).sum()), 2) if (lam ** 2).sum() > 0 else None
    return {"strategies": keys, "pairs": pairs, "clusters": clusters, "cluster_of": cluster_of,
            "effective_independent_sources": n_eff, "min_trades": min_trades,
            "method": ("overlap = share of a strategy's trades with a same-symbol, same-direction trade of the other within "
                       f"{OVERLAP_WINDOW_BARS} M15 bars; outcome correlation = Pearson of daily R on days either traded; "
                       "shared exposure = overlapping holding bars on the same symbol / the smaller strategy's holding bars; "
                       "effective sources = participation ratio of the daily-R correlation matrix eigenvalues")}


# ------------------------------------------------------------------ assembly

def _months(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 2:
        return None
    return max(1.0, (rows[-1]["utc"] - rows[0]["utc"]) / (30.44 * 86400))


def historical_block(key: str, intel: dict[str, Any], v7: dict[str, Any], trades: dict[str, list]) -> dict[str, Any] | None:
    """Historical metrics for a bank key, or the merged sources behind a live scanner strategy."""
    from strategy_bank import evidence_tiers
    hist = intel.get("strategies") or {}
    sources = LIVE_HISTORY.get(key, (key,))
    if len(sources) == 1 and sources[0] in hist and (hist[sources[0]].get("performance") or {}).get("all_periods"):
        h = hist[sources[0]]
        p = h["performance"]
        a = p["all_periods"]
        folds = [f for f in p.get("walk_forward") or [] if f.get("trades")]
        return {"source": "intel", "trades": a.get("trades"), "win_rate": a.get("win_rate"), "expectancy_r": a.get("expectancy_r"),
                "expectancy_ci95": a.get("expectancy_ci95"), "profit_factor": a.get("profit_factor"), "total_r": a.get("total_r"),
                "max_drawdown_r": a.get("max_drawdown_r"), "trades_per_month": a.get("trades_per_month"),
                "development_expectancy": (p.get("development") or {}).get("expectancy_r"), "test_expectancy": (p.get("test") or {}).get("expectancy_r"),
                "test_trades": (p.get("test") or {}).get("trades"), "x2_cost_expectancy": (p.get("all_periods_x2_costs") or {}).get("expectancy_r"),
                "walk_forward_positive": sum(1 for f in folds if (f.get("expectancy_r") or 0) > 0), "walk_forward_folds": len(folds),
                "instruments_positive": sum(1 for v in (p.get("by_instrument") or {}).values() if (v.get("expectancy_r") or 0) > 0 and v.get("trades", 0) >= 20),
                "instruments_evaluated": sum(1 for v in (p.get("by_instrument") or {}).values() if v.get("trades", 0) >= 20),
                "evidence": h.get("evidence"), "holm_p": h.get("holm_p")}
    rows = sorted((t for s in sources for t in trades.get(s, [])), key=lambda t: t["utc"])
    if not rows:
        return None
    rs = [t["r"] for t in rows if t.get("r") is not None]
    a = perf(rs, _months(rows))
    v7p = ((v7.get("variants") or {}).get(sources[0]) or {}).get("performance") if len(sources) == 1 else None
    dev_cut = datetime(2026, 4, 1, tzinfo=UTC).timestamp()
    dev = [t["r"] for t in rows if t["utc"] < dev_cut and t.get("r") is not None]
    test = [t["r"] for t in rows if t["utc"] >= dev_cut and t.get("r") is not None]
    folds = (v7p or {}).get("walk_forward") or []
    by_inst: dict[str, list[float]] = defaultdict(list)
    for t in rows:
        if t.get("r") is not None:
            by_inst[t["symbol"]].append(t["r"])
    synthetic = {"all_periods": {**a}, "development": perf(dev, ci=False), "test": perf(test, ci=False),
                 "all_periods_x2_costs": (v7p or {}).get("all_periods_x2_costs") or {}, "walk_forward": folds}
    evidence = evidence_tiers.classify(synthetic, None)
    evidence["note"] = ("merged from " + " + ".join(sources) if len(sources) > 1 else "V7 production replay") + \
                       "; not part of the Holm family, so significance cannot pass"
    return {"source": "+".join(sources), "trades": a["trades"], "win_rate": a["win_rate"], "expectancy_r": a["expectancy_r"],
            "expectancy_ci95": a["expectancy_ci95"], "profit_factor": a["profit_factor"], "total_r": a["total_r"],
            "max_drawdown_r": a["max_drawdown_r"], "trades_per_month": a["trades_per_month"],
            "development_expectancy": synthetic["development"]["expectancy_r"], "test_expectancy": synthetic["test"]["expectancy_r"],
            "test_trades": synthetic["test"]["trades"], "x2_cost_expectancy": synthetic["all_periods_x2_costs"].get("expectancy_r"),
            "walk_forward_positive": sum(1 for f in folds if (f.get("expectancy_r") or 0) > 0 and f.get("trades")),
            "walk_forward_folds": sum(1 for f in folds if f.get("trades")),
            "instruments_positive": sum(1 for v in by_inst.values() if len(v) >= 20 and sum(v) > 0),
            "instruments_evaluated": sum(1 for v in by_inst.values() if len(v) >= 20),
            "evidence": evidence, "holm_p": None}


def classify_rows(rows: list[dict[str, Any]]) -> None:
    """Participation and quality flags (in place). Shares are computed within each system."""
    for system in ("LIVE_SCANNER", "STRATEGY_BANK"):
        group = [r for r in rows if r["system"] == system and r["scanned"]]
        total = sum((r["live"] or {}).get("confirmed", 0) for r in group)
        fair = 1 / len(group) if group else 0
        for r in group:
            n = (r["live"] or {}).get("confirmed", 0)
            r["live_share"] = round(n / total, 4) if total else 0.0
    tpm = [r["historical"]["trades_per_month"] for r in rows if r.get("historical") and r["historical"].get("trades_per_month")]
    hv = float(np.percentile(tpm, HV_PERCENTILE)) if tpm else math.inf
    for r in rows:
        flags, notes = [], []
        group_n = sum(1 for x in rows if x["system"] == r["system"] and x["scanned"])
        fair = 1 / group_n if group_n else 0
        share = r.get("live_share", 0.0)
        live_n = (r["live"] or {}).get("confirmed", 0)
        if r["scanned"] and share >= max(DOMINANT_MIN_SHARE, DOMINANT_SHARE_X * fair):
            flags.append("DOMINANT")
            notes.append(f"{share:.0%} of its system's live confirmations (equal share {fair:.0%})")
        if r["scanned"] and live_n == 0:
            flags.append("INACTIVE")
            notes.append("no live confirmation recorded")
        elif r["scanned"] and share < UNDER_SHARE_X * fair:
            flags.append("UNDERREPRESENTED")
            notes.append(f"{share:.1%} of live confirmations")
        f = r.get("funnel") or {}
        setups, rate = f.get("setups"), f.get("confirmation_rate")
        if setups and setups >= FILTER_MIN_SETUPS and rate is not None and rate < FILTER_RATE and f.get("top_rejection_share", 0) >= FILTER_TOP_SHARE:
            flags.append("EXCESSIVE_FILTERING")
            notes.append(f"{rate:.1%} of setups confirm; '{f.get('top_rejection')}' causes {f['top_rejection_share']:.0%} of rejections")
        h = r.get("historical") or {}
        e, ci, tier = h.get("expectancy_r"), h.get("expectancy_ci95") or [None, None], (h.get("evidence") or {}).get("tier")
        if tier in ("RESEARCH", "VALIDATED", "PRODUCTION") or ((h.get("development_expectancy") or 0) > 0 and (h.get("test_expectancy") or 0) > 0
                                                              and (h.get("trades") or 0) >= 100):
            flags.append("PROMISING")
            notes.append(f"evidence tier {tier}; development {h.get('development_expectancy')} R, test {h.get('test_expectancy')} R")
        if (h.get("trades_per_month") or 0) >= hv and e is not None and ((ci[1] is not None and ci[1] < 0) or e <= LQ_EXPECTANCY):
            flags.append("HIGH_VOLUME_LOW_QUALITY")
            notes.append(f"{h.get('trades_per_month')} trades/month (top quartile) at {e} R per trade")
        r["flags"], r["flag_notes"] = flags, notes


def build(args: argparse.Namespace) -> dict[str, Any]:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    import market_regime
    from strategies import REGISTRY
    from strategy_bank import allocation, engine, rules
    rules.load_expansion()
    t0 = time.perf_counter()
    now = time.time()
    base = data_dir()
    bank = engine.bank_dir()
    research_root = base / "research"
    intel = json.loads((bank / "intel.json").read_text(encoding="utf-8")) if (bank / "intel.json").exists() else {}
    v7 = json.loads((research_root / "v7_variants.json").read_text(encoding="utf-8")) if (research_root / "v7_variants.json").exists() else {}
    print("live scanner stores ...", flush=True)
    scanner_live = live_scanner(base, now)
    print(f"observations (tail {args.obs_tail_mb or 'full'} MB) ...", flush=True)
    obs = scan_observations(base / "setup_observations.jsonl", int(args.obs_tail_mb * 1e6) if args.obs_tail_mb else None)
    print(f"  {time.perf_counter() - t0:.0f}s; bank store ...", flush=True)
    bank_live = live_bank(now)
    funnel = {}
    if not args.no_replay:
        start, end = datetime.fromisoformat(args.replay_start).replace(tzinfo=UTC), datetime.fromisoformat(args.replay_end).replace(tzinfo=UTC)
        print(f"replay funnel {start.date()} .. {end.date()} ...", flush=True)
        funnel = replay_funnel(start, end)
    print(f"  {time.perf_counter() - t0:.0f}s; historical trades + regimes ...", flush=True)
    trades, entries = load_trades(bank, research_root)
    regime_tags(trades)

    rows: list[dict[str, Any]] = []
    for item in REGISTRY.describe():
        sid = item["strategy_id"]
        fam, concepts = FAMILY.get(sid, ("Other", ()))
        o, rf = obs.get(sid) or {}, funnel.get(sid) or {}
        setups = (o.get("reached") or {}).get("DEVELOPING")
        rej = (rf.get("confirming_rejections") or []) + (rf.get("qualification_rejections") or [])
        rej_total = sum(n for _, n in rej)
        top = max(rej, key=lambda x: x[1], default=(None, 0))
        live = scanner_live.get(sid)
        hist_trades = sorted((t for s in LIVE_HISTORY.get(sid, ()) for t in trades.get(s, [])), key=lambda t: t["utc"])
        rows.append({"key": sid, "name": LIVE_NAMES.get(sid, sid), "family": fam, "concepts": list(concepts), "system": "LIVE_SCANNER",
                     "deployment": item["status"], "version": item["version"], "timeframe": item["timeframe"], "scanned": item["status"] != "DISABLED",
                     "instruments": (live or {}).get("instruments") or [], "live": live,
                     "funnel": {"source": "live observations + replay sample", "episodes": o.get("episodes"), "setups": setups,
                                "reached_confirming": (o.get("reached") or {}).get("CONFIRMING"),
                                "confirmed": (o.get("reached") or {}).get("CONFIRMED"),
                                "confirmation_rate": round(((o.get("reached") or {}).get("CONFIRMED") or 0) / setups, 4) if setups else None,
                                "rate_basis": "episodes that reached CONFIRMED / episodes that reached DEVELOPING, same observation window",
                                "live_failed_rules": o.get("failed_rules"), "live_qualification_failed": o.get("qualification_failed"),
                                "observation_window": [o.get("first"), o.get("last")], "replay": rf or None,
                                "top_rejection": top[0], "top_rejection_share": round(top[1] / rej_total, 3) if rej_total else 0.0},
                     "historical": historical_block(sid, intel, v7, trades),
                     "regimes": regime_report(hist_trades, fam) if hist_trades else None})
    hist = intel.get("strategies") or {}
    for spec in rules.SPECS:
        key = spec["key"]
        if spec["status"] == rules.LINKED:
            continue                                   # linked strategies ARE the live scanner rows above
        fam, concepts = FAMILY.get(key, ("Other", ()))
        tech = (hist.get(key) or {}).get("technical") or {}
        decisions, accepted = tech.get("decisions"), tech.get("accepted")
        rej = sorted(((k.replace("rejected: ", ""), v) for k, v in tech.items() if k.startswith("rejected")), key=lambda x: -x[1])
        rej_total = sum(v for _, v in rej)
        live = bank_live.get(key)
        rows.append({"key": key, "name": spec["name"], "family": fam, "concepts": list(concepts), "system": "STRATEGY_BANK",
                     "deployment": spec["status"], "version": spec.get("version") or spec.get("family") or "bank", "timeframe": spec["timeframe"],
                     "scanned": spec["status"] in rules.SCANNED_STATUSES and callable(spec.get("decide")),
                     "instruments": list(spec.get("instruments") or []), "unsupported_reason": spec.get("unsupported_reason"),
                     "live": live,
                     "funnel": {"source": "historical gate counters (engine.confirm)", "setups": decisions, "confirmed": accepted,
                                "confirmation_rate": round(accepted / decisions, 4) if decisions and accepted is not None else None,
                                "rejections": rej[:6], "top_rejection": rej[0][0] if rej else None,
                                "top_rejection_share": round(rej[0][1] / rej_total, 3) if rej_total else 0.0,
                                "note": "bank rules decide on closed bars; the funnel counts decisions that the common gates rejected"},
                     "historical": historical_block(key, intel, v7, trades),
                     "regimes": regime_report(trades[key], fam) if trades.get(key) else None})
    classify_rows(rows)

    div_keys = [k for k in trades if not k.endswith(("_B_measured", "_B_v2"))]
    print(f"  {time.perf_counter() - t0:.0f}s; diversification over {len(div_keys)} strategies ...", flush=True)
    div = diversification(trades, entries, div_keys)
    pol = allocation.policy()
    alloc_rows = []
    for r in rows:
        h = r.get("historical") or {}
        fwd = r.get("live") or {}
        a = allocation.classify(h.get("evidence"), {"resolved": fwd.get("resolved"), "expectancy_r": fwd.get("expectancy_r"),
                                                     "profit_factor": fwd.get("profit_factor")}, r["key"], pol)
        r["allocation"] = {**a, "current_deployment": r["deployment"], "evidence_tier": (h.get("evidence") or {}).get("tier")}
        alloc_rows.append({"key": r["key"], "class": a["class"], "ci_lower": (h.get("expectancy_ci95") or [None])[0]})
    cluster_of = {}
    for r in rows:
        srcs = LIVE_HISTORY.get(r["key"], (r["key"],))
        cluster_of[r["key"]] = div["cluster_of"].get(srcs[0], -1 - len(cluster_of))
    w = allocation.weights(alloc_rows, cluster_of, pol)
    for r in rows:
        r["allocation"]["weight"] = w.get(r["key"], 0.0)

    families = defaultdict(list)
    for r in rows:
        families[r["family"]].append(r["key"])
    coverage = []
    for fam in market_regime.SUITABILITY:
        members = [r for r in rows if r["family"] == fam or fam in r["concepts"]]
        coverage.append({"family": fam, "strategies": [r["key"] for r in members],
                         "primary": [r["key"] for r in members if r["family"] == fam],
                         "live_confirmations": sum((r["live"] or {}).get("confirmed", 0) for r in members if r["family"] == fam),
                         "best_tier": min((((r.get("historical") or {}).get("evidence") or {}).get("tier") or "EXPERIMENTAL" for r in members),
                                          key=TIER_ORDER.index) if members else None,
                         "designed_regimes": list(market_regime.SUITABILITY[fam])})
    result = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "label": args.label or "current",
              "runtime_seconds": round(time.perf_counter() - t0),
              "notes": ["Live = production stores (hypothetical signal outcomes, not trades).",
                        "Historical = simulated on MT5 history with spread, commission, slippage and financing; not live results.",
                        "Classifications reward evidence, never volume. Nothing in this report changes the engine."],
              "thresholds": {"dominant": f"share >= max({DOMINANT_MIN_SHARE}, {DOMINANT_SHARE_X} x equal share)",
                             "underrepresented": f"share < {UNDER_SHARE_X} x equal share", "inactive": "no live confirmation",
                             "excessive_filtering": f"confirmation rate < {FILTER_RATE:.0%} with >= {FILTER_MIN_SETUPS} setups and one gate >= {FILTER_TOP_SHARE:.0%} of rejections",
                             "high_volume_low_quality": f"historical trades/month >= P{HV_PERCENTILE} and (CI below zero or expectancy <= {LQ_EXPECTANCY} R)",
                             "promising": "evidence tier RESEARCH or better, or positive development AND test expectancy with >= 100 trades"},
              "regimes": {"labels": market_regime.LABELS, "suitability": {k: list(v) for k, v in market_regime.SUITABILITY.items()}},
              "strategies": rows, "family_coverage": coverage,
              "diversification": {k: v for k, v in div.items() if k != "cluster_of"},
              "allocation_policy": pol, "variant_tests": v7.get("decisions"),
              "inputs": {"intel_generated_at": intel.get("generated_at"), "v7_generated_at": v7.get("generated_at"),
                         "observation_tail_mb": args.obs_tail_mb or None}}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--obs-tail-mb", type=float, default=0.0, help="scan only the last N MB of setup_observations.jsonl (0 = all)")
    parser.add_argument("--replay-start", default="2026-06-01")
    parser.add_argument("--replay-end", default="2026-07-01")
    parser.add_argument("--no-replay", action="store_true")
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    result = build(args)
    from strategy_bank import engine
    path = engine.bank_dir() / "participation.json"
    text = json.dumps(result, indent=1, default=str)
    path.write_text(text, encoding="utf-8")
    if args.label:
        (engine.bank_dir() / f"participation_{args.label}.json").write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(result['strategies'])} strategies, {result['runtime_seconds']}s)")


if __name__ == "__main__":
    main()
