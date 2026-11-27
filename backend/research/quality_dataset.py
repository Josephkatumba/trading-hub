"""Historical signal dataset for quality research: every signal, its causal features, and its outcome
under alternative entry and exit rules, net of trading costs.

Signals
  - the 18 scanned Strategy Bank strategies (same decide() and confirm() gates as live; research/bank_backtest)
  - production strategies replayed by research/replay (trendline_v5 split into break-retest and bounce,
    support_resistance, smc, trend_momentum), from data/research/signals/*.jsonl
Every raw signal is kept (no one-position filter here): a quality filter decides which signals trade,
and the evaluation applies the one-position-per-strategy-and-symbol rule AFTER filtering.

Outcomes (research/simulate.simulate: spread on the correct side, commission, 0.5-spread stop slippage,
overnight financing, M1 tie-break, ambiguous = stop) for each variant, at 1x and 2x costs:
  base        the strategy's own entry, stop and target
  t1/t1.5/t2/t3  same stop, target at 1 / 1.5 / 2 / 3 R
  atr         stop 1.5 x H1 ATR from the entry, target 2R           (volatility-sized stop)
  wide        stop 1.5 x the original distance, original target price  (looser stop, same target)
  trail       original stop, no fixed target, 1.5 x H1 ATR trailing stop (dynamic take profit)
  confirm     wait for the entry M15 bar to close in the trade direction without touching the stop;
              enter at the next bar's open with the original stop and target prices
  pullback    limit order 0.3R better than the entry within 4 M15 bars, original stop and target prices;
              not filled -> no trade

    python -m research.quality_dataset        # writes data/research/quality/dataset.jsonl.gz
"""
from __future__ import annotations

import gzip
import json
import multiprocessing
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from research import lab
from storage_config import data_directory

LINKED = ("trendline_v5", "support_resistance", "smc", "trend_momentum")
TARGET_RS = {"t1": 1.0, "t1.5": 1.5, "t2": 2.0, "t3": 3.0}
VARIANTS = ("base", *TARGET_RS, "atr", "wide", "trail", "confirm", "pullback")


def out_path() -> Path:
    return data_directory() / "research" / "quality" / "dataset.jsonl.gz"


def _linked(symbol: str) -> list[dict[str, Any]]:
    rows = []
    for sid in LINKED:
        try:
            signals = lab.load_signals(sid)
        except FileNotFoundError:
            continue
        for s in signals:
            if s["symbol"] != symbol:
                continue
            key = sid
            if sid == "trendline_v5":
                fam = str(s["evidence"].get("setup_family", "")).upper()
                key = "trendline_break_retest" if fam == "BREAK" else "trendline_bounce"
            rows.append({**{k: s[k] for k in ("index", "utc", "symbol", "direction", "entry", "stop_loss", "take_profit", "spread")},
                         "strategy_id": key, "max_bars": s.get("max_bars", 480), "evidence": {"score": s["evidence"].get("score")}})
    return rows


def _sim(simulate, signal: dict[str, Any], h: Any, cost: float, **kw: Any) -> dict[str, Any]:
    res = simulate(signal, h, cost_multiplier=cost, max_bars=kw.pop("max_bars", signal.get("max_bars", 480)), **kw)
    return res


def _variant(name: str, s: dict[str, Any], h: Any, atr: float, simulate) -> dict[str, Any] | None:
    """Simulated outcome of a variant at 1x and 2x costs, or None when the variant does not trade."""
    long = s["direction"] == "LONG"
    sign = 1 if long else -1
    entry, sl, tp = s["entry"], s["stop_loss"], s["take_profit"]
    risk = abs(entry - sl)
    bars = h.full["M15"]
    sig, kw = dict(s), {}
    if name == "base":
        pass
    elif name in TARGET_RS:
        kw["target"] = entry + sign * TARGET_RS[name] * risk
    elif name == "atr":
        if not atr or atr <= 0:
            return None
        kw["stop"] = entry - sign * 1.5 * atr
        kw["target"] = entry + sign * 3.0 * atr
    elif name == "wide":
        kw["stop"] = entry - sign * 1.5 * risk
    elif name == "trail":
        if not atr or atr <= 0:
            return None
        kw["trail"] = 1.5 * atr
        kw["target"] = None
        sig["take_profit"] = None
    elif name == "confirm":
        j = s["index"]
        if j + 1 >= len(bars):
            return None
        b = bars[j]
        stop_touched = b["low"] <= sl if long else b["high"] + b["spread"] >= sl
        target_touched = b["high"] >= tp if long else b["low"] + b["spread"] <= tp
        if stop_touched or target_touched or sign * (b["close"] - b["open"]) <= 0:
            return None
        nb = bars[j + 1]
        new_entry = nb["open"] + (nb["spread"] if long else 0.0)
        if not ((sl < new_entry < tp) if long else (tp < new_entry < sl)):
            return None
        sig.update(index=j + 1, entry=new_entry)
    elif name == "pullback":
        j = s["index"]
        limit = entry - sign * 0.3 * risk
        fill = None
        for k in range(j, min(len(bars), j + 4)):
            b = bars[k]
            ask_low, ask_high = b["low"] + b["spread"], b["high"] + b["spread"]
            if (ask_low <= limit) if long else (b["high"] >= limit):
                fill = k
                break
            if (b["high"] >= tp) if long else (b["low"] + b["spread"] <= tp):
                return None                      # target reached before the limit filled: no trade
        if fill is None:
            return None
        b = bars[fill]
        stop_in_fill_bar = b["low"] <= sl if long else b["high"] + b["spread"] >= sl
        new_risk = abs(limit - sl)
        if stop_in_fill_bar:                     # pessimistic: the fill bar also reached the stop
            slip = 0.5 * b["spread"]
            r = -(new_risk + slip) / new_risk
            return {"r": round(r, 4), "r2": round(-(new_risk + 2 * slip) / new_risk, 4), "outcome": "SL",
                    "exit_index": fill, "entry_index": fill}
        if fill + 1 >= len(bars):
            return None
        sig.update(index=fill + 1, entry=limit)
    one = simulate(sig, h, cost_multiplier=1.0, max_bars=s.get("max_bars", 480), **kw)
    if one.get("r") is None:
        return None if one["outcome"] in ("INVALID_PLAN", "OPEN") else {"r": None, "outcome": one["outcome"]}
    two = simulate(sig, h, cost_multiplier=2.0, max_bars=s.get("max_bars", 480), **kw)
    return {"r": one["r"], "r2": two.get("r"), "outcome": one["outcome"], "exit_index": one.get("exit_index"),
            "entry_index": sig["index"], "mfe": one.get("mfe_r"), "mae": one.get("mae_r")}


def build_symbol(symbol: str) -> tuple[str, list[dict[str, Any]], float]:
    from research.bank_backtest import _symbol_signals
    from research.simulate import simulate
    from signal_quality import features
    from strategy_bank import rules
    started = time.perf_counter()
    h = lab.history_for(symbol)
    _, bank, _, _ = _symbol_signals(symbol)
    signals = [s for rows in bank.values() for s in rows] + _linked(symbol)
    ctx = rules.Ctx(symbol, {tf: h.full[tf] for tf in ("M15", "H1", "H4", "D1")})
    m15 = h.full["M15"]
    rows = []
    for s in sorted(signals, key=lambda x: (x["utc"], x["strategy_id"])):
        feat = features.compute(ctx, s["utc"], s["strategy_id"], s["direction"], s["entry"], s["stop_loss"], s["take_profit"])
        atr = feat["raw"].get("atr_h1")
        outcomes = {}
        for name in VARIANTS:
            res = _variant(name, s, h, atr, simulate)
            if res is not None:
                outcomes[name] = res
        base = outcomes.get("base")
        if not base or base.get("r") is None:
            continue
        exit_utc = {k: m15[v["exit_index"]]["utc"] for k, v in outcomes.items() if v.get("exit_index") is not None}
        rows.append({"utc": s["utc"], "symbol": symbol, "strategy": s["strategy_id"], "direction": s["direction"],
                     "index": s["index"], "entry": s["entry"], "stop_loss": s["stop_loss"], "take_profit": s["take_profit"],
                     "score": (s.get("evidence") or {}).get("score"), "features": feat["features"],
                     "raw": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in feat["raw"].items() if k != "regime"},
                     "outcomes": {k: {**v, "exit_utc": exit_utc.get(k)} for k, v in outcomes.items()}})
    return symbol, rows, time.perf_counter() - started


def main(symbols: tuple[str, ...] = lab.SYMBOLS, processes: int = 16) -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    path = out_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = defaultdict(int)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle, multiprocessing.Pool(min(processes, len(symbols))) as pool:
        for symbol, rows, seconds in pool.imap_unordered(build_symbol, symbols):
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
                counts[row["strategy"]] += 1
            print(f"  {symbol}: {len(rows)} signals ({seconds:.0f}s)", flush=True)
    tmp.replace(path)
    print(json.dumps(dict(sorted(counts.items())), indent=1))
    print(f"written {path}")


def load(path: Path | None = None) -> list[dict[str, Any]]:
    with gzip.open(path or out_path(), "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


if __name__ == "__main__":
    import sys
    main(tuple(sys.argv[1:]) or lab.SYMBOLS)
