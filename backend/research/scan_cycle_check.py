"""One complete scanner cycle over the cached MT5 history, without the live engine (verification tool).

Runs, for every symbol of the production universe, at the latest cached bar:
  * every enabled strategy of the live scanner registry (strategies.REGISTRY.evaluate, then the
    production planning + qualification exactly as main._market_snapshot applies them), and
  * every scanned strategy-bank rule (rules.scanned(): EXPERIMENTAL + RESEARCH, after load_expansion)
    through engine.confirm, as strategy_bank.worker does on a bar close,
and reports, per strategy, that it was evaluated, its state/decision counts and any exception. It
records nothing, alerts nothing and never contacts MT5 or Telegram.

    python -m research.scan_cycle_check            # prints a JSON summary
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Any


def run() -> dict[str, Any]:
    import qualification
    from research import lab
    from research.replay import SymbolHistory
    from strategies import REGISTRY
    from strategy_bank import engine, rules
    from trade_planning import apply_plan
    rules.load_expansion()
    started = time.perf_counter()
    live: dict[str, Counter] = defaultdict(Counter)
    bank: dict[str, Counter] = defaultdict(Counter)
    errors: list[str] = []
    for symbol in lab.SYMBOLS:
        h = SymbolHistory.load(symbol)
        built = h.market_input(len(h.full["M15"]) - 1)
        if built is None:
            errors.append(f"{symbol}: no market input")
            continue
        market, quote = built
        for sid, result in REGISTRY.evaluate(market).items():
            if not result.ok:
                live[sid]["error"] += 1
                errors.append(f"{symbol} {sid}: {result.error!r}")
                continue
            setup = {**quote, **result.payload, "strategy_id": sid, "strategy_version": result.strategy_version}
            apply_plan(setup, market.bars)
            qualification.apply(setup)
            live[sid]["evaluated"] += 1
            live[sid]["state:" + str(setup.get("state"))] += 1
            if setup.get("strategy_valid"):
                live[sid]["confirmed"] += 1
        ctx = rules.Ctx(symbol, {tf: h.full[tf] for tf in ("M15", "H1", "H4", "D1")})
        for spec in rules.scanned():
            if symbol not in spec["instruments"]:
                continue
            tf = spec["timeframe"]
            i = len(ctx.a[tf]["close"]) - 1
            try:
                d = spec["decide"](ctx, i)
                bank[spec["key"]]["evaluated"] += 1
                if d is not None:
                    bank[spec["key"]]["decisions"] += 1
                    bid = float(ctx.a[tf]["close"][i])
                    signal, _ = engine.confirm(spec, d, ctx, i, {"bid": bid, "ask": bid, "tick_age_seconds": 0.0},
                                               ctx.close_utc(tf, i), check_freshness=False)
                    if signal:
                        bank[spec["key"]]["confirmed"] += 1
                        bank[spec["key"]]["regime_tagged"] += signal.get("regime") is not None
            except Exception as exc:                     # a failing rule is reported, never hidden
                bank[spec["key"]]["error"] += 1
                errors.append(f"{symbol} {spec['key']}: {exc!r}")
    expected_bank = {s["key"] for s in rules.scanned()}
    return {"seconds": round(time.perf_counter() - started, 1), "symbols": len(lab.SYMBOLS),
            "live_registry": {k: dict(v) for k, v in live.items()},
            "live_registry_all_evaluated": set(REGISTRY.enabled()) <= {k for k, v in live.items() if v["evaluated"]},
            "bank": {k: dict(v) for k, v in sorted(bank.items())},
            "bank_not_evaluated": sorted(expected_bank - {k for k, v in bank.items() if v["evaluated"]}),
            "errors": errors}


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    print(json.dumps(run(), indent=1))
