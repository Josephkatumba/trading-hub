"""Edge-discovery tournament (protocol: docs/EDGE_DISCOVERY_PLAN.md, registry: research/edge/registry.py).

Pass 1 (one process per instrument): experiment 0 diagnostics, every family x config x exit simulated with
          research/simulate.py at 1x and 2x costs, the per-instrument logistic classifier, buy-and-hold.
Selection: per (family, instrument) the config x exit with the best TRAIN expectancy among those with
          >= 60 train trades. Nothing else is chosen anywhere.
Pass 2:   matched random-entry controls (20 seeds) for every selected pair, on validation and test.
Gate:     validation E > 0, PF > 1.1, >= 30 trades, above the 95th percentile of its random controls, and
          Holm-adjusted one-sided p < 0.10 across ALL selected pairs (new families, quant layer and the
          existing strategies, which compete with their own fixed rules).
Test:     evaluated once for every selected pair. CREDIBLE = gate passed AND test E > 0, PF > 1.1, >= 30
          trades AND validation+test CI lower bound > 0 AND positive at 2x costs AND >= 3/4 positive OOS quarters.
Every trial is written to data/research/edge/ledger.jsonl with the registry fingerprint.

    python -m research.edge.tournament
"""
from __future__ import annotations

import json
import math
import multiprocessing
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from research.edge import registry
from research.edge.registry import EXITS, FAMILIES, GATES, OOS_QUARTERS, SPLITS, TARGETS, UTC
from storage_config import data_directory

PEERS = {"XAUUSD": ["XAGUSD"], "BTCUSD": ["ETHUSD"], "ETHUSD": ["BTCUSD"], "NAS100": ["US500", "GER40"],
         "US500": ["NAS100", "GER40"], "GER40": ["NAS100", "US500"]}
SYMBOLS = TARGETS + ("XAGUSD",)
TS = {k: (a.timestamp(), b.timestamp()) for k, (a, b) in SPLITS.items()}
FAR = 100.0


def out_dir() -> Path:
    return data_directory() / "research" / "edge"


def period_of(utc: float) -> str | None:
    for name, (a, b) in TS.items():
        if a <= utc < b:
            return name
    return None


# ----- pre-registration -------------------------------------------------------------------------------

def ledger_path() -> Path:
    return out_dir() / "ledger.jsonl"


def preregister() -> dict[str, Any]:
    """Record the program fingerprint before any result exists; refuse to run if the registry changed."""
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fp = registry.fingerprint()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if lines:
        for line in lines:
            row = json.loads(line)
            if row.get("type") == "preregistration" and row.get("program") == registry.PROGRAM:
                if row["fingerprint"] != fp:
                    raise SystemExit(f"{registry.PROGRAM} was pre-registered with a different fingerprint; "
                                     "register a new PROGRAM version instead of editing the registry")
                return row
    row = {"type": "preregistration", "program": registry.PROGRAM, "fingerprint": fp,
           "recorded_at": datetime.now(UTC).isoformat(), "trials_per_instrument": registry.trial_count(),
           "spec": registry.spec()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")
    return row


# ----- pass 1: per instrument ------------------------------------------------------------------------

def _plan(m: Any, s: dict[str, Any]) -> dict[str, Any] | None:
    j = s["i"] + 1
    if j >= m.n:
        return None
    long = s["dir"] == 1
    entry = m.open[j] + (m.spread[j] if long else 0.0)
    risk = (entry - s["stop"]) if long else (s["stop"] - entry)
    atr = s["atr"]
    if not (atr > 0 and 0.15 * atr <= risk <= 6 * atr):
        return None
    return {"index": j, "utc": float(m.utc[j]), "direction": "LONG" if long else "SHORT", "entry": float(entry),
            "stop_loss": float(s["stop"]), "risk": float(risk), "max_bars": s["max_bars"], "target": s.get("target"),
            "atr": atr}


def _simulate_exits(plan: dict[str, Any], h: Any, natural: str | None) -> dict[str, tuple]:
    """{exit: (r1x, r2x, exit_index, outcome)} for every applicable exit."""
    from research.simulate import simulate
    sign = 1 if plan["direction"] == "LONG" else -1
    e, risk = plan["entry"], plan["risk"]
    sig = {"index": plan["index"], "direction": plan["direction"], "entry": e, "stop_loss": plan["stop_loss"],
           "take_profit": None}

    def run(target: float | None, trail: float | None = None) -> tuple | None:
        a = simulate(sig, h, target=target, max_bars=plan["max_bars"], trail=trail)
        if a.get("r") is None:
            return None
        b = simulate(sig, h, target=target, max_bars=plan["max_bars"], trail=trail, cost_multiplier=2.0)
        return (a["r"], b.get("r"), a.get("exit_index", plan["index"]), a["outcome"])

    out: dict[str, tuple] = {}
    far = e + sign * FAR * risk
    if natural == "target" and plan["target"] is not None and sign * (plan["target"] - e) > 0.2 * risk:
        res = run(plan["target"])
        if res:
            out["natural"] = res
    for name, k in (("1.5R", 1.5), ("2R", 2.0), ("3R", 3.0), ("1R", 1.0)):
        res = run(e + sign * k * risk)
        if res:
            out[name] = res
    res = run(far)
    if res:
        out["time"] = res
        if natural == "time":
            out["natural"] = res
    res = run(None, trail=risk)
    if res:
        out["trail"] = res
    if "1R" in out and "trail" in out:
        a, b = out["1R"], out["trail"]
        out["partial"] = (round(0.5 * a[0] + 0.5 * b[0], 4), None if a[1] is None or b[1] is None else round(0.5 * a[1] + 0.5 * b[1], 4),
                          max(a[2], b[2]), "PARTIAL")
    out.pop("1R", None)
    return out


def _simulate_one(plan: dict[str, Any], h: Any, exit_: str) -> float | None:
    """Net R (1x costs) of one exit type for a plan without a natural target (random-entry controls)."""
    from research.simulate import simulate
    sign = 1 if plan["direction"] == "LONG" else -1
    e, risk = plan["entry"], plan["risk"]
    sig = {"index": plan["index"], "direction": plan["direction"], "entry": e, "stop_loss": plan["stop_loss"], "take_profit": None}
    run = lambda target, trail=None: simulate(sig, h, target=target, max_bars=plan["max_bars"], trail=trail).get("r")
    if exit_ in ("1.5R", "2R", "3R"):
        return run(e + sign * float(exit_[:-1]) * risk)
    if exit_ in ("time", "natural"):
        return run(e + sign * FAR * risk)
    if exit_ == "trail":
        return run(None, risk)
    if exit_ == "partial":
        a, b = run(e + sign * risk), run(None, risk)
        return None if a is None or b is None else 0.5 * a + 0.5 * b
    return run(e + sign * 2 * risk)


def _logit_signals(m: Any) -> list[dict[str, Any]]:
    """E3: per-instrument logistic classifier on H1 bars, fitted on TRAIN bars only (labels purged at the boundary)."""
    from strategy_bank import indicators as ind
    f = m.frame("H1")
    c, atr = f.close, f.atr
    n = len(c)
    rsi = ind.rsi(c, 14)
    ema20, ema50 = f.ema(20), f.ema(50)
    base = ind.sma(np.nan_to_num(atr, nan=0.0), 100)
    lr = np.r_[np.nan, np.diff(np.log(c))]
    hours = (f.utc % 86400) // 3600
    X = np.column_stack([lr, np.r_[np.nan, lr[:-1]], np.r_[[np.nan] * 2, lr[:-2]], np.r_[[np.nan] * 3, lr[:-3]],
                         (c - ema20) / atr, (c - ema50) / atr, rsi / 100 - 0.5, f.adx / 100,
                         atr / np.where(base > 0, base, np.nan) - 1, np.sin(2 * np.pi * hours / 24), np.cos(2 * np.pi * hours / 24)])
    y = np.r_[(c[4:] > c[:-4]).astype(float), [np.nan] * 4]
    ok = np.isfinite(X).all(axis=1)
    a, b = TS["train"]
    close_t = f.utc + 3600
    train = ok & np.isfinite(y) & (close_t >= a) & (np.r_[close_t[4:], [np.inf] * 4] < b) & (np.arange(n) > 120)
    if train.sum() < 500:
        return []
    mu, sd = X[train].mean(axis=0), X[train].std(axis=0) + 1e-12
    Z = (X - mu) / sd
    Z = np.column_stack([np.ones(n), np.nan_to_num(Z)])
    w = np.zeros(Z.shape[1])
    Zt, yt = Z[train], y[train]
    for _ in range(600):
        p = 1 / (1 + np.exp(-Zt @ w))
        grad = Zt.T @ (p - yt) / len(yt) + 1e-3 * np.r_[0, w[1:]]
        w -= 0.5 * grad
    p_all = 1 / (1 + np.exp(-Z @ w))
    out = []
    for k in range(121, n):
        i = int(f.last_m15[k])
        if i >= m.n - 1 or not ok[k] or not (atr[k] > 0):
            continue
        d = 1 if p_all[k] > 0.56 else -1 if p_all[k] < 0.44 else 0
        if d:
            out.append({"i": i, "dir": d, "stop": float(c[k] - d * atr[k]), "target": None, "max_bars": 16, "atr": float(m.atr_h1_at[i])})
    return out


def buy_and_hold(m: Any) -> dict[str, Any]:
    out = {}
    for name, (a, b) in TS.items():
        sel = (m.utc >= a) & (m.utc < b)
        if sel.sum() < 100:
            continue
        c = m.close[sel]
        eq = c / c[0]
        dd = float((1 - eq / np.maximum.accumulate(eq)).max())
        day = (m.utc[sel] // 86400).astype(int)
        last = np.r_[day[1:] != day[:-1], True]
        dr = np.diff(np.log(c[last]))
        sharpe = float(dr.mean() / dr.std() * math.sqrt(252)) if len(dr) > 10 and dr.std() > 0 else None
        out[name] = {"return_pct": round(float(eq[-1] - 1) * 100, 2), "max_drawdown_pct": round(dd * 100, 2),
                     "sharpe": round(sharpe, 2) if sharpe is not None else None}
    return out


def pass1(symbol: str) -> dict[str, Any]:
    from research import lab
    from research.edge import candidates, diagnostics
    from research.edge.market import Market
    from signal_quality import regime as regime_mod
    from strategy_bank import rules
    t0 = time.perf_counter()
    h = lab.history_for(symbol)
    m = Market(symbol, h)
    diag = diagnostics.run(m, SPLITS)
    signs = {tf: v["large_move"]["sign"] for tf, v in diag["train"]["structure"].items()}
    ctx = rules.Ctx(symbol, {tf: h.full[tf] for tf in ("M15", "H1", "H4", "D1")})
    regime_cache: dict[int, str] = {}

    def regime_at(j: int) -> str:
        if j not in regime_cache:
            regime_cache[j] = regime_mod.classify(ctx, float(m.utc[j]))["regime"]
        return regime_cache[j]

    jobs = [(fam["key"], ci, cfg, fam["natural"]) for fam in FAMILIES for ci, cfg in enumerate(fam["configs"])]
    trades: list[tuple] = []
    signal_counts: dict[str, int] = {}
    for key, ci, cfg, natural in jobs + [("logit_h1", 0, {}, None)]:
        if key == "large_move":
            cfg = {**cfg, "sign": signs.get(cfg["tf"], 0)}
        raw = _logit_signals(m) if key == "logit_h1" else candidates.GENERATORS[key](m, cfg)
        signal_counts[f"{key}#{ci}"] = len(raw)
        for s in raw:
            plan = _plan(m, s)
            if plan is None or period_of(plan["utc"]) is None:
                continue
            exits = _simulate_exits(plan, h, natural)
            if not exits:
                continue
            reg = regime_at(plan["index"])
            hour = int((plan["utc"] % 86400) // 3600)
            for ex, (r1, r2, xi, outcome) in exits.items():
                trades.append((key, ci, ex, plan["utc"], plan["index"], xi, r1, r2, s["dir"], hour,
                               round(plan["risk"] / plan["atr"], 3), plan["max_bars"], reg, outcome))
    return {"symbol": symbol, "diagnostics": diag, "large_move_signs": signs, "trades": trades,
            "signal_counts": signal_counts, "buy_and_hold": buy_and_hold(m), "seconds": round(time.perf_counter() - t0)}


# ----- statistics -------------------------------------------------------------------------------------

def busy_filter(rows: list[tuple]) -> list[tuple]:
    """One position at a time (rows of one strategy on one instrument, any order)."""
    out, busy = [], -1
    for row in sorted(rows, key=lambda r: (r[3], r[4])):
        if row[4] <= busy:
            continue
        busy = row[5]
        out.append(row)
    return out


def stats(rows: list[tuple], cost: int = 1) -> dict[str, Any]:
    from research.quality_research import stats as qstats
    k = 6 if cost == 1 else 7
    return qstats([{"r": r[k], "outcome": r[13], "utc": r[3]} for r in rows if r[k] is not None])


def p_one_sided(s: dict[str, Any]) -> float | None:
    t = s.get("t_stat")
    if t is None:
        return None
    return 0.5 * math.erfc(t / math.sqrt(2))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for rank, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - rank) * p))
        out[k] = running
    return out


def split(rows: list[tuple], name: str) -> list[tuple]:
    a, b = TS[name]
    return [r for r in rows if a <= r[3] < b]


def quarters(rows: list[tuple]) -> list[dict[str, Any]]:
    out = []
    for a, b in zip(OOS_QUARTERS, OOS_QUARTERS[1:]):
        sel = [r for r in rows if a.timestamp() <= r[3] < b.timestamp()]
        s = stats(sel)
        out.append({"from": a.date().isoformat(), "trades": s["trades"], "expectancy_r": s["expectancy_r"]})
    return out


def regime_stability(rows: list[tuple]) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r[12]].append(r[6])
    eligible = {k: v for k, v in groups.items() if len(v) >= 20}
    positive = sorted(k for k, v in eligible.items() if sum(v) / len(v) > 0)
    return {"regimes_tested": len(eligible), "regimes_positive": len(positive), "positive": positive,
            "by_regime": {k: {"n": len(v), "expectancy_r": round(sum(v) / len(v), 4)} for k, v in sorted(groups.items())}}


# ----- pass 2: random-entry controls ---------------------------------------------------------------------

def pass2(task: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """Matched random entries for each selected pair on one instrument: same months, hours of day, long share,
    stop distance in ATR(H1), horizon, exit type (a natural target is replaced by 2R) and trade count."""
    from research import lab
    from research.edge.market import Market
    symbol, specs = task
    h = lab.history_for(symbol)
    m = Market(symbol, h)
    ah1 = m.atr_h1_at
    months = ((m.utc // 86400) // 30.44).astype(int)
    hours = ((m.utc % 86400) // 3600).astype(int)
    by_month_hour: dict[tuple[int, int], np.ndarray] = {}
    out = {}
    for spec in specs:
        res = {}
        for period in ("validation", "test"):
            rows = spec[period]
            if not rows:
                continue
            exit_ = "2R" if spec["exit"] == "natural" and spec["natural"] == "target" else spec["exit"]
            means = []
            for seed in range(GATES["random_seeds"]):
                rng = random.Random(f"{symbol}|{spec['id']}|{period}|{seed}")
                trades = []
                for r in rows:
                    key = (int((r["utc"] // 86400) // 30.44), r["hour"])
                    if key not in by_month_hour:
                        by_month_hour[key] = np.flatnonzero((months == key[0]) & (hours == key[1]))
                    pool = by_month_hour[key]
                    if not len(pool):
                        continue
                    i = int(pool[rng.randrange(len(pool))])
                    if i + 1 >= m.n or not (ah1[i] > 0):
                        continue
                    d = 1 if rng.random() < spec["long_share"] else -1
                    entry = m.open[i + 1] + (m.spread[i + 1] if d == 1 else 0.0)
                    stop = entry - d * r["risk_atr"] * ah1[i]
                    plan = {"index": i + 1, "utc": float(m.utc[i + 1]), "direction": "LONG" if d == 1 else "SHORT",
                            "entry": float(entry), "stop_loss": float(stop), "risk": float(r["risk_atr"] * ah1[i]),
                            "max_bars": r["max_bars"], "target": None, "atr": float(ah1[i])}
                    val = _simulate_one(plan, h, exit_)
                    if val is not None:
                        trades.append(val)
                if trades:
                    means.append(sum(trades) / len(trades))
            means.sort()
            if means:
                res[period] = {"mean": round(sum(means) / len(means), 4),
                               "p95": round(means[min(len(means) - 1, int(0.95 * len(means)))], 4)}
        out[spec["id"]] = res
    return symbol, out


# ----- main -------------------------------------------------------------------------------------------

def existing_strategy_rows() -> dict[tuple[str, str], list[tuple]]:
    """The 21 existing strategies (production replays and bank) from the quality dataset, with their own exits."""
    from research.quality_dataset import load
    out: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for r in load():
        if r["symbol"] not in TARGETS:
            continue
        o = r["outcomes"]["base"]
        if period_of(r["utc"]) is None:
            continue
        out[(r["strategy"], r["symbol"])].append(
            ("existing:" + r["strategy"], 0, "own", r["utc"], r["index"], o.get("exit_index") or r["index"], o["r"], o.get("r2"),
             1 if r["direction"] == "LONG" else -1, int((r["utc"] % 86400) // 3600), None, 480, r["features"]["regime"], o["outcome"]))
    return out


def summarize_pair(rows_sel: list[tuple]) -> dict[str, Any]:
    tr, va, te = (split(rows_sel, k) for k in ("train", "validation", "test"))
    oos = va + te
    s_oos = stats(oos)
    return {"train": stats(tr), "validation": stats(va), "test": stats(te), "oos": s_oos, "oos_2x": stats(oos, 2),
            "quarters": quarters(oos), "regimes": regime_stability(oos)}


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    t0 = time.perf_counter()
    prereg = preregister()
    print(f"program {registry.PROGRAM} fingerprint {prereg['fingerprint'][:16]}")
    results: dict[str, Any] = {}
    with multiprocessing.Pool(len(SYMBOLS)) as pool:
        for res in pool.imap_unordered(pass1, SYMBOLS):
            results[res["symbol"]] = res
            print(f"  {res['symbol']}: {len(res['trades'])} trade rows ({res['seconds']}s)", flush=True)
    ledger = ledger_path().open("a", encoding="utf-8")
    recorded = datetime.now(UTC).isoformat()

    # ---- selection on TRAIN only -----------------------------------------------------------------------
    pairs: dict[str, dict[str, Any]] = {}
    trials = 0
    for symbol in TARGETS:
        grouped: dict[tuple, list] = defaultdict(list)
        for row in results[symbol]["trades"]:
            grouped[(row[0], row[1], row[2])].append(row)
        families = sorted({k[0] for k in grouped})
        for fam in families:
            best, best_e = None, -math.inf
            for (f, ci, ex), rows in grouped.items():
                if f != fam:
                    continue
                trials += 1
                filtered = busy_filter(rows)
                tr = stats(split(filtered, "train"))
                eligible = tr["trades"] >= GATES["min_train_trades"]
                ledger.write(json.dumps({"type": "trial", "program": registry.PROGRAM, "fingerprint": prereg["fingerprint"],
                                         "recorded_at": recorded, "symbol": symbol, "family": f, "config": ci, "exit": ex,
                                         "train": {k: tr[k] for k in ("trades", "win_rate", "expectancy_r", "profit_factor")},
                                         "eligible": eligible}) + "\n")
                if eligible and tr["expectancy_r"] > best_e:
                    best, best_e = (ci, ex, filtered), tr["expectancy_r"]
            pid = f"{symbol}|{fam}"
            if best is None:
                pairs[pid] = {"symbol": symbol, "family": fam, "kind": "quant" if fam == "logit_h1" else "new",
                              "status": "INELIGIBLE (train sample < 60)"}
                continue
            ci, ex, filtered = best
            cfg = ({"logit_h1": {}}.get(fam) if fam == "logit_h1" else next(x for x in FAMILIES if x["key"] == fam)["configs"][ci])
            pairs[pid] = {"symbol": symbol, "family": fam, "kind": "quant" if fam == "logit_h1" else "new", "config": cfg,
                          "config_index": ci, "exit": ex, "rows": filtered,
                          "natural": None if fam == "logit_h1" else next(x for x in FAMILIES if x["key"] == fam)["natural"]}

    # ---- quant layer: regime selector and ensemble (built from TRAIN selections) -------------------------
    for symbol in TARGETS:
        base = {p["family"]: p for p in pairs.values() if p["symbol"] == symbol and "rows" in p and p["kind"] == "new"}
        # E1 regime selector
        regime_map = {}
        for fam, p in base.items():
            tr = split(p["rows"], "train")
            for reg in {r[12] for r in tr}:
                vals = [r[6] for r in tr if r[12] == reg]
                if len(vals) >= 30 and sum(vals) / len(vals) > 0:
                    e = sum(vals) / len(vals)
                    if reg not in regime_map or e > regime_map[reg][1]:
                        regime_map[reg] = (fam, round(e, 4), len(vals))
        rows = []
        for reg, (fam, _, _) in regime_map.items():
            rows += [r for r in base[fam]["rows"] if r[12] == reg]
        sel_rows = []
        busy: dict[str, int] = {}
        for r in sorted(rows, key=lambda r: r[3]):
            if r[4] <= busy.get(r[0], -1):
                continue
            busy[r[0]] = r[5]
            sel_rows.append(r)
        pairs[f"{symbol}|regime_selector"] = {"symbol": symbol, "family": "regime_selector", "kind": "quant", "exit": "per family",
                                               "config": {k: v[0] for k, v in regime_map.items()}, "regime_map": regime_map,
                                               "rows": sel_rows}
        # E2 ensemble 2-of-N (causal agreement), exit 2R
        grouped2: dict[tuple, list] = defaultdict(list)
        for row in results[symbol]["trades"]:
            grouped2[(row[0], row[1], row[2])].append(row)
        sigs = []
        for fam, p in base.items():
            sigs += [r for r in grouped2.get((fam, p["config_index"], "2R"), [])]
        by_dir = defaultdict(list)
        for r in sigs:
            by_dir[r[8]].append((r[4], r[0]))
        ens = []
        for r in sigs:
            if any(r[4] - 4 <= j <= r[4] and f != r[0] for j, f in by_dir[r[8]]):
                ens.append(r)
        ens_rows = busy_filter(ens)
        pairs[f"{symbol}|ensemble_2of_n"] = {"symbol": symbol, "family": "ensemble_2of_n", "kind": "quant", "exit": "2R",
                                              "config": {"families": sorted(base)}, "rows": ens_rows}

    # ---- existing strategies (fixed rules, own exits) ------------------------------------------------------
    for (strategy, symbol), rows in existing_strategy_rows().items():
        filtered = busy_filter(rows)
        if len(split(filtered, "train")) < GATES["min_train_trades"]:
            pairs[f"{symbol}|existing:{strategy}"] = {"symbol": symbol, "family": "existing:" + strategy, "kind": "existing",
                                                      "status": "INELIGIBLE (train sample < 60)", "rows": filtered}
            continue
        pairs[f"{symbol}|existing:{strategy}"] = {"symbol": symbol, "family": "existing:" + strategy, "kind": "existing",
                                                  "exit": "own", "config": {}, "rows": filtered}

    # ---- statistics, random controls, gates ----------------------------------------------------------------
    for pid, p in pairs.items():
        if "rows" in p and "status" not in p:
            p.update(summarize_pair(p["rows"]))
    tasks: dict[str, list] = defaultdict(list)
    for pid, p in pairs.items():
        if "validation" not in p:
            continue
        rows = p["rows"]
        spec = {"id": pid, "exit": p["exit"] if p["exit"] in EXITS else "2R", "natural": p.get("natural"),
                "long_share": (sum(1 for r in rows if r[8] == 1) / len(rows)) if rows else 0.5}
        for period in ("validation", "test"):
            spec[period] = [{"utc": r[3], "hour": r[9], "risk_atr": r[10] if r[10] else 1.0, "max_bars": r[11]} for r in split(rows, period)]
        tasks[p["symbol"]].append(spec)
    with multiprocessing.Pool(len(TARGETS)) as pool:
        for symbol, res in pool.imap_unordered(pass2, list(tasks.items())):
            for pid, val in res.items():
                pairs[pid]["random_control"] = val
    pvals = {pid: p_one_sided(p["validation"]) for pid, p in pairs.items() if "validation" in p}
    pvals = {k: v for k, v in pvals.items() if v is not None}
    adjusted = holm(pvals)
    for pid, p in pairs.items():
        if "validation" not in p:
            continue
        v, t, rc = p["validation"], p["test"], p.get("random_control", {})
        p["holm_p"] = round(adjusted.get(pid, 1.0), 4)
        p["p_raw"] = round(pvals.get(pid, 1.0), 4)
        checks = {
            "validation_trades": v["trades"] >= GATES["min_validation_trades"],
            "validation_expectancy": (v["expectancy_r"] or 0) > 0,
            "validation_pf": (v["profit_factor"] or 0) > GATES["validation_pf"],
            "beats_random_p95": rc.get("validation") is not None and (v["expectancy_r"] or -9) > rc["validation"]["p95"],
            "holm": p["holm_p"] < GATES["holm_alpha"],
        }
        gate = all(checks.values())
        qpos = sum(1 for q in p["quarters"] if q["trades"] >= 5 and (q["expectancy_r"] or 0) > 0)
        credible_checks = {
            "test_trades": t["trades"] >= GATES["min_test_trades"], "test_expectancy": (t["expectancy_r"] or 0) > 0,
            "test_pf": (t["profit_factor"] or 0) > GATES["test_pf"],
            "oos_trades": p["oos"]["trades"] >= GATES["credible_oos_trades"],
            "oos_ci_above_zero": (p["oos"]["expectancy_ci95"][0] or -1) > 0,
            "double_costs": (p["oos_2x"]["expectancy_r"] or -1) > 0,
            "quarters": qpos >= GATES["quarters_positive"],
            "test_beats_random_p95": rc.get("test") is not None and (t["expectancy_r"] or -9) > rc["test"]["p95"],
        }
        p["gate_checks"], p["credible_checks"], p["quarters_positive"] = checks, credible_checks, qpos
        p["status"] = ("CREDIBLE" if gate and all(credible_checks.values()) else
                       "PASSED VALIDATION, FAILED TEST" if gate else "FAILED VALIDATION")
        ledger.write(json.dumps({"type": "selected", "program": registry.PROGRAM, "fingerprint": prereg["fingerprint"],
                                 "recorded_at": recorded, "pair": pid, "kind": p["kind"], "config": p.get("config"),
                                 "exit": p.get("exit"), "status": p["status"], "holm_p": p["holm_p"],
                                 "validation": {k: v[k] for k in ("trades", "expectancy_r", "profit_factor")},
                                 "test": {k: t[k] for k in ("trades", "expectancy_r", "profit_factor")}}, default=str) + "\n")
    # peer consistency for survivors of validation: same family, config and exit on related instruments
    for pid, p in pairs.items():
        if p.get("status", "").startswith(("CREDIBLE", "PASSED")) and p["kind"] == "new":
            peers = {}
            for peer in PEERS.get(p["symbol"], []):
                rows = busy_filter([r for r in results[peer]["trades"] if r[0] == p["family"] and r[1] == p["config_index"] and r[2] == p["exit"]])
                s = stats(split(rows, "validation") + split(rows, "test"))
                peers[peer] = {k: s[k] for k in ("trades", "expectancy_r", "profit_factor")}
            p["peer_consistency"] = peers
    ledger.close()

    # ---- leaderboard ---------------------------------------------------------------------------------------
    tier = {"CREDIBLE": 0, "PASSED VALIDATION, FAILED TEST": 1, "FAILED VALIDATION": 2}
    board = []
    for pid, p in pairs.items():
        if "validation" not in p:
            continue
        o = p["oos"]
        board.append({"pair": pid, "symbol": p["symbol"], "family": p["family"], "kind": p["kind"], "config": p.get("config"),
                      "exit": p.get("exit"), "status": p["status"], "oos_trades": o["trades"], "oos_win_rate": o["win_rate"],
                      "oos_expectancy_r": o["expectancy_r"], "oos_ci95": o["expectancy_ci95"], "oos_profit_factor": o["profit_factor"],
                      "oos_max_drawdown_r": o["max_drawdown_r"], "oos_avg_win_r": o["avg_win_r"], "oos_avg_loss_r": o["avg_loss_r"],
                      "oos_2x_expectancy_r": p["oos_2x"]["expectancy_r"], "train_expectancy_r": p["train"]["expectancy_r"],
                      "train_trades": p["train"]["trades"], "validation_expectancy_r": p["validation"]["expectancy_r"],
                      "validation_trades": p["validation"]["trades"], "test_expectancy_r": p["test"]["expectancy_r"],
                      "test_trades": p["test"]["trades"], "quarters_positive": p["quarters_positive"],
                      "regimes_positive": f"{p['regimes']['regimes_positive']}/{p['regimes']['regimes_tested']}",
                      "random_control": p.get("random_control"), "holm_p": p["holm_p"], "p_raw": p["p_raw"],
                      "peer_consistency": p.get("peer_consistency")})
    board.sort(key=lambda b: (tier[b["status"]], -(b["oos_expectancy_r"] if b["oos_expectancy_r"] is not None else -9),
                              -(b["oos_profit_factor"] or 0), b["oos_max_drawdown_r"] or 0, -b["oos_trades"]))
    summary = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "program": registry.PROGRAM,
               "fingerprint": prereg["fingerprint"], "label": "HISTORICAL RESEARCH (simulated on MT5 history, net of costs; not live results)",
               "trials": {"configuration_x_exit_trials": trials, "selected_pairs_tested_at_validation": len(pvals),
                          "prior_programs_configurations": 227},
               "status_counts": {k: sum(1 for b in board if b["status"] == k) for k in tier},
               "leaderboard": board,
               "regime_maps": {s: pairs[f"{s}|regime_selector"].get("regime_map") for s in TARGETS},
               "ineligible": sorted(pid for pid, p in pairs.items() if str(p.get("status", "")).startswith("INELIGIBLE")),
               "diagnostics": {s: results[s]["diagnostics"] for s in SYMBOLS},
               "large_move_signs": {s: results[s]["large_move_signs"] for s in SYMBOLS},
               "buy_and_hold": {s: results[s]["buy_and_hold"] for s in SYMBOLS},
               "best_by_instrument": {s: next((b for b in board if b["symbol"] == s), None) for s in TARGETS},
               "seconds": round(time.perf_counter() - t0)}
    path = out_dir() / "tournament.json"
    path.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary["status_counts"]), f"trials={trials}", f"({summary['seconds']}s)")
    for b in board[:25]:
        print(f"{b['status'][:26]:26} {b['pair'][:44]:44} {str(b['exit']):9} OOS n={b['oos_trades']:4} WR={b['oos_win_rate']} "
              f"E={b['oos_expectancy_r']} CI={b['oos_ci95']} PF={b['oos_profit_factor']} 2x={b['oos_2x_expectancy_r']} "
              f"val={b['validation_expectancy_r']}({b['validation_trades']}) test={b['test_expectancy_r']}({b['test_trades']}) holm={b['holm_p']}")
    print(f"written {path}")


if __name__ == "__main__":
    main()
