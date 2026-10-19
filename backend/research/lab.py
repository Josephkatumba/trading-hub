"""Research lab driver: generate signals, evaluate variants, keep the experiment ledger.

    python -m research.lab generate              replay production strategies over cached history
    python -m research.lab baseline              production strategies, development + holdout
    python -m research.lab experiments           every experiment in experiments.py
    python -m research.lab report                print the ledger

Periods are fixed so every strategy is compared on identical markets:
  DEVELOPMENT  2024-10-15 .. 2026-04-01   walk-forward: quarterly test folds; a variant with
                                          parameters is tuned only on the 6 months before each fold
  HOLDOUT      2026-04-01 .. 2026-10-12   untouched until a variant is final; scored once, never
                                          used to choose
Everything is written under <data dir>/research (git-ignored). Failed experiments are
recorded exactly like successful ones.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from storage_config import data_directory

SYMBOLS = ("XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "NAS100", "US500", "GER40",
           "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "XAGUSD", "EURJPY")
UTC = timezone.utc
DEV_START, DEV_END = datetime(2024, 10, 15, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC)
HOLDOUT_START, HOLDOUT_END = DEV_END, datetime(2026, 10, 12, tzinfo=UTC)
FOLDS = [(datetime(y, m, 1, tzinfo=UTC), datetime(y2, m2, 1, tzinfo=UTC)) for (y, m, y2, m2) in (
    (2024, 10, 2025, 1), (2025, 1, 2025, 4), (2025, 4, 2025, 7), (2025, 7, 2025, 10),
    (2025, 10, 2026, 1), (2026, 1, 2026, 4))]


def root() -> Path:
    return data_directory() / "research"


def _ts(value: datetime) -> float:
    return value.timestamp()


# ----- signal generation ------------------------------------------------------------------

def _generate_symbol(args: tuple[str, list[str], float, float]) -> tuple[str, dict[str, list[dict[str, Any]]], float]:
    symbol, strategy_ids, start, end = args
    import time
    from research.replay import SymbolHistory, signals
    from research import experiments
    started = time.perf_counter()
    history_ = SymbolHistory.load(symbol)
    out = {}
    for strategy_id in strategy_ids:
        strategy = experiments.strategy(strategy_id)
        out[strategy_id] = list(signals(history_, strategy, start, end))
    return symbol, out, time.perf_counter() - started


def generate(strategy_ids: list[str], start: datetime = DEV_START, end: datetime = HOLDOUT_END,
             processes: int = 16) -> dict[str, int]:
    folder = root() / "signals"
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [(symbol, strategy_ids, _ts(start), _ts(end)) for symbol in SYMBOLS]
    collected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with multiprocessing.Pool(min(processes, len(jobs))) as pool:
        for symbol, out, seconds in pool.imap_unordered(_generate_symbol, jobs):
            print(f"  {symbol}: " + ", ".join(f"{k}={len(v)}" for k, v in out.items()) + f" ({seconds:.0f}s)", flush=True)
            for strategy_id, rows in out.items():
                collected[strategy_id].extend(rows)
    counts = {}
    for strategy_id, rows in collected.items():
        rows.sort(key=lambda row: (row["utc"], row["symbol"]))
        with (folder / f"{strategy_id}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        counts[strategy_id] = len(rows)
    return counts


def load_signals(strategy_id: str) -> list[dict[str, Any]]:
    path = root() / "signals" / f"{strategy_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"no signals for {strategy_id}; run: python -m research.lab generate")
    return [json.loads(line) for line in path.open(encoding="utf-8")]


# ----- evaluation ----------------------------------------------------------------------------

_HISTORIES: dict[str, Any] = {}


def history_for(symbol: str):
    from research.replay import SymbolHistory
    if symbol not in _HISTORIES:
        _HISTORIES[symbol] = SymbolHistory.load(symbol)
    return _HISTORIES[symbol]


Transform = Callable[[dict[str, Any], Any], "dict[str, Any] | None"]


def trades(signals_: Iterable[dict[str, Any]], transform: Transform | None = None, start: datetime | None = None,
           end: datetime | None = None, **simulate_kwargs: Any) -> list[dict[str, Any]]:
    """Simulate signals in order; a strategy holds one position per symbol at a time.
    `transform(signal, history)` may return None (filtered), or a dict of overrides
    (stop_loss, take_profit, max_bars) for the simulation."""
    from research.simulate import simulate
    busy_until: dict[tuple[str, str], int] = {}
    out = []
    for signal in signals_:
        if start and signal["utc"] < _ts(start) or end and signal["utc"] >= _ts(end):
            continue
        history_ = history_for(signal["symbol"])
        key = (signal["strategy_id"], signal["symbol"])
        if signal["index"] <= busy_until.get(key, -1):
            continue
        overrides: dict[str, Any] = {}
        if transform is not None:
            changed = transform(signal, history_)
            if changed is None:
                continue
            overrides = changed
        result = simulate({**signal, **{k: v for k, v in overrides.items() if k in ("entry", "direction")}}, history_,
                          stop=overrides.get("stop_loss"), target=overrides.get("take_profit"),
                          max_bars=overrides.get("max_bars", signal.get("max_bars", simulate_kwargs.get("max_bars", 480))),
                          cost_multiplier=simulate_kwargs.get("cost_multiplier", 1.0),
                          trail=overrides.get("trail", signal.get("trail")))
        if result["outcome"] in ("INVALID_PLAN",):
            continue
        busy_until[key] = result.get("exit_index", signal["index"])
        out.append({**{k: signal[k] for k in ("utc", "symbol", "strategy_id", "direction")},
                    "score": signal["evidence"].get("score"), "index": signal["index"], **result})
    return out


def months(start: datetime, end: datetime) -> float:
    return (end - start).days / 30.44


def evaluate(signals_: list[dict[str, Any]], transform: Transform | None = None, **kwargs: Any) -> dict[str, Any]:
    from research.metrics import summarize
    dev = trades(signals_, transform, DEV_START, DEV_END, **kwargs)
    hold = trades(signals_, transform, HOLDOUT_START, HOLDOUT_END, **kwargs)
    folds = []
    for start, end in FOLDS:
        fold = [t for t in dev if _ts(start) <= t["utc"] < _ts(end)]
        s = summarize(fold, months(start, end))
        folds.append({"from": start.date().isoformat(), "trades": s["trades"], "expectancy_r": s["expectancy_r"],
                      "total_r": s["total_r"]})
    positive = sum(1 for f in folds if (f["expectancy_r"] or 0) > 0)
    stressed = trades(signals_, transform, DEV_START, DEV_END, cost_multiplier=2.0)
    return {"development": summarize(dev, months(DEV_START, DEV_END)), "folds": folds,
            "positive_folds": f"{positive}/{len(folds)}",
            "development_double_costs": summarize(stressed, months(DEV_START, DEV_END)),
            "holdout": summarize(hold, months(HOLDOUT_START, HOLDOUT_END)),
            "_trades": {"development": dev, "holdout": hold}}


TRAIN_MONTHS = 6
MIN_TRAIN_TRADES = 30


def _shift_months(value: datetime, months_back: int) -> datetime:
    month = value.month - months_back
    year = value.year + (month - 1) // 12
    return value.replace(year=year, month=(month - 1) % 12 + 1)


def walk_forward(signals_: list[dict[str, Any]], family: dict[str, Transform | None], default: str,
                 **kwargs: Any) -> dict[str, Any]:
    """Out-of-sample evaluation of a parameterised variant. For each development fold the
    family member with the best expectancy over the TRAIN_MONTHS before the fold is applied to
    the fold (the pre-registered `default` when no member has MIN_TRAIN_TRADES there); the
    holdout uses the member chosen on the last TRAIN_MONTHS of development. Only fold results
    (never training results) enter the reported statistics."""
    from research.metrics import summarize
    cache: dict[tuple[str, float, float], list[dict[str, Any]]] = {}

    def run(name: str, start: datetime, end: datetime, **extra: Any) -> list[dict[str, Any]]:
        key = (name, _ts(start), _ts(end), extra.get("cost_multiplier", 1.0))
        if key not in cache:
            cache[key] = trades(signals_, family[name], start, end, **{**kwargs, **extra})
        return cache[key]

    def choose(end: datetime) -> str:
        start = max(DEV_START, _shift_months(end, TRAIN_MONTHS))
        best, best_e = default, None
        for name in family:
            s = summarize(run(name, start, end))
            if s["trades"] >= MIN_TRAIN_TRADES and (best_e is None or s["expectancy_r"] > best_e):
                best, best_e = name, s["expectancy_r"]
        return best

    out_of_sample, stressed, folds = [], [], []
    for start, end in FOLDS:
        chosen = choose(start) if start > DEV_START else default
        fold = run(chosen, start, end)
        out_of_sample += fold
        stressed += run(chosen, start, end, cost_multiplier=2.0)
        s = summarize(fold, months(start, end))
        folds.append({"from": start.date().isoformat(), "chosen": chosen, "trades": s["trades"],
                      "expectancy_r": s["expectancy_r"], "total_r": s["total_r"]})
    holdout_choice = choose(DEV_END)
    hold = run(holdout_choice, HOLDOUT_START, HOLDOUT_END)
    positive = sum(1 for f in folds if (f["expectancy_r"] or 0) > 0)
    return {"development": summarize(out_of_sample, months(DEV_START, DEV_END)), "folds": folds,
            "positive_folds": f"{positive}/{len(folds)}",
            "development_double_costs": summarize(stressed, months(DEV_START, DEV_END)),
            "holdout_choice": holdout_choice, "holdout": summarize(hold, months(HOLDOUT_START, HOLDOUT_END)),
            "_trades": {"development": out_of_sample, "holdout": hold}}


def breakdown(trade_list: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    from research.metrics import summarize
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for trade in trade_list:
        groups[key(trade)].append(trade)
    return {str(k): {f: v for f, v in summarize(rows).items() if f in ("trades", "win_rate", "expectancy_r", "total_r", "expectancy_ci95")}
            for k, rows in sorted(groups.items(), key=lambda kv: str(kv[0]))}


# ----- ledger --------------------------------------------------------------------------------

def record(entry: dict[str, Any]) -> None:
    path = root() / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"recorded_at": datetime.now(UTC).isoformat(), **{k: v for k, v in entry.items() if not k.startswith("_")}}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def ledger() -> list[dict[str, Any]]:
    path = root() / "ledger.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")] if path.exists() else []


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "baseline", "experiments", "report"))
    parser.add_argument("--strategies", default="")
    args = parser.parse_args()
    from research import experiments
    if args.command == "generate":
        ids = [s for s in args.strategies.split(",") if s] or experiments.GENERATED
        print(generate(ids))
    elif args.command == "baseline":
        experiments.run_baseline()
    elif args.command == "experiments":
        experiments.run_all()
    else:
        for row in ledger():
            d, h = row.get("development", {}), row.get("holdout", {})
            print(f"{row['name']:42} dev n={d.get('trades')} E={d.get('expectancy_r')} CI={d.get('expectancy_ci95')} "
                  f"| holdout n={h.get('trades')} E={h.get('expectancy_r')} | {row.get('verdict')}")


if __name__ == "__main__":
    sys.exit(main())
