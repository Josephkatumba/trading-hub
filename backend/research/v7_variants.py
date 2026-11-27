"""V7 strategy-participation audit: historical test of the two implementation fixes it proposes.

Hypotheses (written before the run; nothing is tuned, each variant is one fixed rule change):

  TM  tm-pullback-v2 plans a measured-move target (pullback extreme + impulse) and gates on R:R >= 1.5
      against it, but trade_planning.apply_plan then caps the target at the nearest intervening H1
      swing. In a pullback continuation the impulse extreme is itself such a swing, so the executed
      target is almost always the prior high and qualification rejects ~96% of the strategy's own
      confirmations (V7 funnel). Variant B executes the strategy's documented measured-move target.
  SMC smc-confluence-v1 targets the nearest H1 swing beyond entry, including swings price already
      traded through (their resting liquidity is gone). Variant B (smc-confluence-v2) targets the
      nearest untaken swing, as the strategy's own "external liquidity" concept states.

Decision rule (pre-registered): a variant replaces production only when, on the DEVELOPMENT period
(train + validation) alone, (1) its expectancy is not below the production version's and (2) its
expectancy is above zero after costs. The test period is reported, never used to choose. A variant
that fails stays available as a research version, unregistered.

Same replay (research/replay.py: no look-ahead, production planning + qualification at the next-bar
quote) and simulator (research/simulate.py via v6.run: spread, commission, stop slippage, financing)
as every other ledger.

    python -m research.v7_variants            # writes data/research/v7_variants.json and v7_trades.jsonl.gz
"""
from __future__ import annotations

import json
import multiprocessing
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from research import lab, v6

VARIANTS = {"tm_A_capped": ("trend_momentum", "capped"), "tm_B_measured": ("trend_momentum", "measured"),
            "smc_A_v1": ("smc", "smc-confluence-v1"), "smc_B_v2": ("smc", "smc-confluence-v2")}


def _setup(strategy: Any, market: Any, quote: dict[str, Any], measured: bool) -> dict[str, Any] | None:
    import qualification
    from trade_planning import apply_plan
    try:
        payload = strategy.evaluate(market)
    except Exception:
        return None
    if not payload:
        return None
    setup = {**quote, **payload, "strategy_id": strategy.strategy_id, "strategy_version": strategy.version}
    # The measured-move variant plans without the H1-swing cap (apply_plan caps only with H1 bars).
    apply_plan(setup, None if measured else market.bars)
    qualification.apply(setup)
    return setup


def _symbol(args: tuple[str, float, float]) -> tuple[str, dict[str, list[dict[str, Any]]], dict[str, dict[str, int]], float]:
    symbol, start, end = args
    from research.replay import SymbolHistory
    from strategies import SmcStrategy, TrendMomentumStrategy
    from strategies.smc import SmcV2Strategy
    started = time.perf_counter()
    h = SymbolHistory.load(symbol)
    strategies = {"tm_A_capped": (TrendMomentumStrategy(), False), "tm_B_measured": (TrendMomentumStrategy(), True),
                  "smc_A_v1": (SmcStrategy(), False), "smc_B_v2": (SmcV2Strategy(), False)}
    out: dict[str, list] = defaultdict(list)
    funnel: dict[str, dict[str, int]] = {k: defaultdict(int) for k in strategies}
    previous: dict[str, str | None] = {k: None for k in strategies}
    full = h.full["M15"]
    for i in range(h.first_index(), len(full)):
        utc = full[i]["utc"]
        if utc < start:
            continue
        if utc >= end:
            break
        built = h.market_input(i)
        if built is None:
            previous = {k: None for k in strategies}
            continue
        for key, (strategy, measured) in strategies.items():
            setup = _setup(strategy, *built, measured)
            state = (setup or {}).get("state") or "ERROR"
            funnel[key][state] += 1
            ok = bool(setup and setup.get("strategy_valid") is True and setup.get("direction") in ("LONG", "SHORT"))
            if setup and setup.get("strategy_signal_valid") and not ok:
                funnel[key]["demoted_by_qualification"] += 1
            if ok:
                funnel[key]["confirmed_bars"] += 1
            k = setup.get("direction") if ok else None
            if ok and k != previous[key]:
                out[key].append({"index": i, "utc": utc, "symbol": symbol, "strategy_id": key, "direction": setup["direction"],
                                 "entry": setup.get("entry"), "stop_loss": setup.get("stop_loss"),
                                 "take_profit": setup.get("take_profit"), "spread": built[1]["spread"],
                                 "evidence": {"rr": setup.get("rr")}})
            previous[key] = k
    return symbol, dict(out), {k: dict(v) for k, v in funnel.items()}, time.perf_counter() - started


def evaluate(signals: list[dict[str, Any]]) -> dict[str, Any]:
    signals = sorted(signals, key=lambda s: (s["utc"], s["symbol"]))
    dev = (v6.TRAIN[0], v6.VALID[1])
    full = (v6.TRAIN[0], v6.TEST[1])
    out = {name: v6.stats(v6.run(signals, w), w) for name, w in (("train", v6.TRAIN), ("validation", v6.VALID),
                                                                  ("test", v6.TEST), ("development", dev), ("all_periods", full))}
    out["all_periods_x2_costs"] = v6.stats(v6.run(signals, full, cost_multiplier=2.0), full)
    out["walk_forward"] = [{"start": str(a.date()), "end": str(b.date()),
                            **{k: v for k, v in v6.stats(v6.run(signals, (a, b)), (a, b)).items() if k in ("trades", "expectancy_r", "win_rate", "profit_factor")}}
                           for a, b in list(lab.FOLDS) + [v6.TEST]]
    out["signals"] = len(signals)
    out["_trades"] = [{k: t.get(k) for k in ("utc", "symbol", "strategy_id", "direction", "outcome", "r", "exit_index", "index", "entry")}
                      for t in v6.run(signals, full)]
    return out


def main() -> None:
    from dotenv import load_dotenv
    from pathlib import Path
    from research.strategy_intel import _install_fast_bootstrap
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    _install_fast_bootstrap()
    start, end = v6.TRAIN[0].timestamp(), v6.TEST[1].timestamp()
    collected: dict[str, list] = defaultdict(list)
    funnel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    t0 = time.perf_counter()
    with multiprocessing.Pool(16) as pool:
        for symbol, out, fun, seconds in pool.imap_unordered(_symbol, [(s, start, end) for s in lab.SYMBOLS]):
            print(f"  {symbol}: " + ", ".join(f"{k}={len(v)}" for k, v in out.items()) + f" ({seconds:.0f}s)", flush=True)
            for k, v in out.items():
                collected[k] += v
            for k, v in fun.items():
                for state, n in v.items():
                    funnel[k][state] += n
    result: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "label": "HISTORICAL REPLAY (simulated with costs; not live results)",
                              "decision_rule": "adopt only if development expectancy >= production and > 0; test reported, never used",
                              "periods": {"train": [str(x.date()) for x in v6.TRAIN], "validation": [str(x.date()) for x in v6.VALID],
                                          "test": [str(x.date()) for x in v6.TEST]},
                              "variants": {}}
    import gzip
    trades_path = lab.root() / "v7_trades.jsonl.gz"
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(trades_path, "wt", encoding="utf-8") as fh:
        for key in VARIANTS:
            sig = collected.get(key, [])
            perf = evaluate(sig) if sig else None
            for t in perf.pop("_trades", []) if perf else []:
                fh.write(json.dumps({"strategy": key, **t}, default=str) + "\n")
            result["variants"][key] = {"strategy": VARIANTS[key][0], "variant": VARIANTS[key][1], "funnel": dict(funnel.get(key, {})),
                                       "performance": perf}
            print(f"  evaluated {key}: {len(sig)} signals ({time.perf_counter() - t0:.0f}s)", flush=True)
    for strategy, a, b in (("trend_momentum", "tm_A_capped", "tm_B_measured"), ("smc", "smc_A_v1", "smc_B_v2")):
        pa = (result["variants"][a]["performance"] or {}).get("development") or {}
        pb = (result["variants"][b]["performance"] or {}).get("development") or {}
        ea, eb = pa.get("expectancy_r"), pb.get("expectancy_r")
        adopt = eb is not None and eb > 0 and (ea is None or eb >= ea)
        result.setdefault("decisions", {})[strategy] = {
            "production": a, "candidate": b, "development_expectancy": {a: ea, b: eb}, "adopt": adopt,
            "reason": ("candidate meets the pre-registered rule" if adopt else
                       "candidate not adopted: development expectancy " + ("is not above zero" if eb is None or eb <= 0 else "is below production"))}
    path = lab.root() / "v7_variants.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["decisions"], indent=1))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
