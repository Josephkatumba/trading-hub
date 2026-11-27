"""Kimi Quant Lab causal research harness (local research only).

Replays pure detect() model sources against the shared content-addressed snapshot
using only completed bars (causal windows identical in shape to the live provider
contract declared in each model's manifest). Intent locks, chronological boundary
purges, entry reconstruction and cost accounting mirror quant_labs.evaluation.v1
exactly, so a local run is a faithful replication of what the frozen shared
evaluator will compute for the same intents. Official results still come from
the shared queue run by the trusted operator.
"""
import argparse
import bisect
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
if not (REPO / "quant_labs" / "evaluation").is_dir():
    raise SystemExit("cannot locate trading-hub repository root")
sys.path.insert(0, str(REPO))

from quant_labs.data import SharedData
from quant_labs.evaluation.v1 import foundation as F
from quant_labs.evaluation.v1 import engine as E

DATASET = "bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3"
TF = {"M1": 60, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
START = E.epoch(E.POLICY["train_start"])
VAL = E.epoch(E.POLICY["validation_start"])
TEST = E.epoch(E.POLICY["test_start"])
END = E.epoch(E.POLICY["test_end"])
GEN_HI = END  # --screen lowers this to TEST so no test-period intents are generated


def load_module(path):
    name = "kimi_model_" + str(abs(hash(str(path))))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_symbol(ds, symbol):
    """Frames truncated exactly like engine.evaluate: completed bars only up to test_end."""
    out = {}
    for tf in ("M15", "H1", "H4", "D1", "M1"):
        bars = ds.read(symbol, tf)
        bars = [b for b in bars if b["utc"] + TF[tf] <= END]
        out[tf] = bars
    return out


def window(bars, times, dur, t, count):
    k = bisect.bisect_right(times, t - dur)
    return bars[max(0, k - count):k]


def build_snapshot(symbol, frames, times, reqs, t):
    snap = {"symbol": symbol, "asof": float(t), "time_verified": True, "frames": {}}
    for tf, count in reqs.items():
        if tf not in frames:
            continue
        snap["frames"][tf] = window(frames[tf], times[tf], TF[tf], t, count)
    return snap


def check_decision(d, entry_ref, spread):
    """Harness-side acceptance mirroring live qualify gates (superset of engine checks)."""
    try:
        direction = d["direction"]
        stop = float(d["stop_loss"])
        target = float(d["take_profit"])
        horizon = float(d["horizon_seconds"])
        atr = float(d["atr"])
    except (KeyError, TypeError, ValueError):
        return None
    if direction not in ("LONG", "SHORT"):
        return None
    if not all(map(lambda v: v > 0 and v == v and abs(v) != float("inf"), (stop, target, atr))):
        return None
    if not 60 <= horizon <= 604800:
        return None
    long = direction == "LONG"
    risk = (entry_ref - stop) if long else (stop - entry_ref)
    reward = (target - entry_ref) if long else (entry_ref - target)
    if risk <= 0 or reward <= 0 or reward / risk < 2.0:
        return None
    if spread / risk > 0.1:
        return None
    if not 0.5 * atr <= risk <= 5 * atr:
        return None
    return risk, reward


def generate(ds, module, manifest, symbols, hours=None, limit=None, verbose=True):
    reqs = manifest["requirements"]
    intents = []
    stats = {}
    for symbol in symbols:
        frames = load_symbol(ds, symbol)
        times = {tf: [b["utc"] for b in frames[tf]] for tf in frames}
        m15 = frames["M15"]
        meta = ds.metadata(symbol)
        tick = float(meta["tick_size"])
        commission = E.POLICY["commission_price"][symbol]
        lock_until = 0.0
        count = 0
        t0 = time.time()
        for i in range(len(m15) - 1):
            bar = m15[i]
            t = bar["utc"] + 900
            if t < START or t >= GEN_HI:
                continue
            if hours is not None and (int(t) // 3600) % 24 not in hours:
                continue
            if t < lock_until:
                continue
            snap = build_snapshot(symbol, frames, times, reqs, t)
            try:
                decisions = module.detect(snap) or []
            except Exception as exc:  # noqa: BLE001 - research harness records and continues
                stats[symbol + ":detect_error"] = stats.get(symbol + ":detect_error", 0) + 1
                continue
            if not decisions:
                continue
            # entry bar = next M15 bar (utc == t); engine reconstructs entry from it
            nxt = m15[i + 1]
            if nxt["utc"] != t:
                continue
            accepted = False
            for d in decisions[:1]:
                entry_ref = float(bar["close"])
                chk = check_decision(d, entry_ref, float(nxt["spread"]))
                if chk is None:
                    continue
                risk, reward = chk
                long = d["direction"] == "LONG"
                entry = float(nxt["open"]) + (float(nxt["spread"]) if long else 0.0)
                stop = F.rounded(float(d["stop_loss"]), tick, not long)
                target = F.rounded(float(d["take_profit"]), tick, not long)
                erisk = (entry - stop) if long else (stop - entry)
                ereward = (target - entry) if long else (entry - target)
                if erisk <= 0 or ereward <= 0 or float(nxt["spread"]) / erisk > E.POLICY["max_spread_to_risk"]:
                    continue
                horizon = int(d["horizon_seconds"])
                split = VAL if t < VAL else (TEST if t < TEST else END)
                if t + horizon >= split:
                    continue
                plan = F.Plan(str(i), symbol, d["direction"], float(t), float(t), entry, stop, target,
                              float(t + horizon), erisk, float(nxt["spread"]))
                sim = F.simulate(plan, frames["M15"], frames["M1"], END, commission, meta, 1,
                                 times["M15"], times["M1"])
                lock_until = sim["exit_at"] if sim.get("r") is not None else float(t + horizon)
                intents.append({
                    "symbol": symbol,
                    "direction": d["direction"],
                    "signal_bar_closed_at": float(t),
                    "entry_at": float(t),
                    "stop_loss": float(d["stop_loss"]),
                    "take_profit": float(d["take_profit"]),
                    "horizon_seconds": horizon,
                })
                count += 1
                accepted = True
                break
            if accepted and limit and count >= limit:
                break
        stats[symbol] = count
        if verbose:
            print(f"  {symbol}: {count} intents ({time.time() - t0:.1f}s)", flush=True)
    intents.sort(key=lambda s: (s["symbol"], s["entry_at"]))
    return intents, stats


def local_evaluate(ds, spec, intents):
    request = {"strategy": spec, "signals": intents, "purpose": "RESEARCH", "lab": "kimi"}
    return E.evaluate(ds, request)


def compact(periods):
    rows = {}
    for period in ("train", "validation", "test"):
        for scenario in ("normal", "stress"):
            m = periods[period][scenario]
            rows[f"{period}:{scenario}"] = {
                "attempted": m["attempted"], "resolved": m["resolved"], "unknown": m["unknown"],
                "win_rate": None if m["win_rate"] is None else round(m["win_rate"], 4),
                "net_expectancy_r": None if m["net_expectancy_r"] is None else round(m["net_expectancy_r"], 4),
                "total_r": None if m["total_r"] is None else round(m["total_r"], 3),
                "profit_factor": None if m["profit_factor"] is None else round(m["profit_factor"], 3),
                "max_dd_r": m["max_realized_drawdown_r"], "longest_losing_streak": m["longest_losing_streak"],
                "planned_rr_mean": None if m["planned_rr_mean"] is None else round(m["planned_rr_mean"], 2),
                "opp_per_month": round(m["opportunities_per_month"], 2),
                "weeks": m["independent_entry_weeks"],
                "sign_flip_p": round(m["weekly_sign_flip_p"], 4),
            }
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["generate", "evaluate", "run"])
    p.add_argument("--model", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--symbols", default="EURUSD,GBPUSD,GBPJPY,XAUUSD,BTCUSD,ETHUSD")
    p.add_argument("--hours", default=None, help="comma list of UTC bar-close hours to scan (harness prefilter)")
    p.add_argument("--limit", type=int, default=None, help="max intents per symbol (smoke tests)")
    p.add_argument("--screen", action="store_true", help="train+validation only; no test intents generated")
    p.add_argument("--tag", required=True)
    p.add_argument("--outroot", default=str(Path(__file__).resolve().parent / "results"))
    args = p.parse_args()

    if args.screen:
        global GEN_HI
        GEN_HI = TEST  # generate train+validation intents only; test period never emitted

    outdir = Path(args.outroot) / args.tag
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    hours = set(int(h) for h in args.hours.split(",")) if args.hours else None

    ds = SharedData(str(REPO / "quant_labs" / "state" / "shared"), DATASET)
    module = load_module(args.model)

    if args.command in ("generate", "run"):
        print(f"[{args.tag}] generating intents for {symbols} ...", flush=True)
        intents, stats = generate(ds, module, manifest, symbols, hours=hours, limit=args.limit)
        (outdir / "intents.json").write_text(json.dumps(intents, indent=1), encoding="utf-8")
        (outdir / "gen_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
        print(f"[{args.tag}] generated {len(intents)} intents", flush=True)
    else:
        intents = json.loads((outdir / "intents.json").read_text(encoding="utf-8"))

    if args.command in ("evaluate", "run"):
        print(f"[{args.tag}] running frozen evaluator replication ...", flush=True)
        t0 = time.time()
        result = local_evaluate(ds, spec, intents)
        (outdir / "local_result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        summary = {"tag": args.tag, "intents": len(intents), "rejections": result["rejections"],
                   "gen_stats": stats if args.command == "run" else None,
                   "periods": compact(result["periods"]), "elapsed_s": round(time.time() - t0, 1)}
        (outdir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(json.dumps(summary, indent=1), flush=True)


if __name__ == "__main__":
    main()
