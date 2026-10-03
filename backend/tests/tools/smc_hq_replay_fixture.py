"""Developer tool: a genuine historical SMC observation pair for the Company HQ P04 replay test.

Usage (from backend/, MT5 terminal running):
    python tests/tools/smc_hq_replay_fixture.py SYMBOL "YYYY-MM-DD HH:MM" OUT.json

Read-only. Nothing is written to the live store: TRADEden's own SMC strategy and its own
observation recorder (observations.record_markets) run on real MT5 history inside an
isolated temporary store with a frozen clock, exactly as the live scan would have recorded
them when each M15 bar opened (stop_ab.market_at: closed bars + the forming bar at its open).
The quote of each observation is the bar open (bid) and bid + the bar's recorded MT5 spread
(ask). The time is the bar open through the verified MT5 basis.

Output: {"note", "entry": the observation whose lifecycle_state is CONFIRMED with
strategy_valid, "exit_quote": the first later observation whose quote crosses the confirmed
stop or target (quotes only, no intrabar path)}. The bar time is MT5 server time.
"""
from __future__ import annotations

import bisect
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import golden_support as g  # noqa: E402
import observations  # noqa: E402
import stop_ab  # noqa: E402
from market_time import normalize_mt5_epoch  # noqa: E402
from strategies import smc  # noqa: E402

BASIS = "America/New_York+07:00"      # the verified MT5 time basis (.env)
HORIZON = 480


def load(symbol: str, end: datetime):
    import MetaTrader5 as mt5
    import main
    if not mt5.initialize():
        raise SystemExit("MT5 not available")
    broker = main.mt5_symbol(symbol)
    point = mt5.symbol_info(broker).point
    frames = {}
    for tf, days in (("M15", 40), ("H1", 60), ("H4", 150), ("D1", 400)):
        rates = mt5.copy_rates_range(broker, getattr(mt5, "TIMEFRAME_" + tf), end - timedelta(days=days), end + timedelta(days=8))
        frames[tf] = [{"time": float(r["time"]), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                       "close": float(r["close"]), "spread": int(r["spread"])} for r in rates]
    return broker, point, frames


def market(symbol: str, broker: str, point: float, frames, times, k: int) -> tuple[dict, datetime]:
    bar = frames["M15"][k]
    payload = smc.analyze_smc(stop_ab.market_at(symbol, frames, times, k))
    stamp = normalize_mt5_epoch(bar["time"], BASIS)
    observed = datetime.fromisoformat(stamp["normalized_utc"])
    bid = bar["open"]
    ask = round(bid + bar["spread"] * point, 10)
    provenance = {
        "source_timestamp": stamp["normalized_utc"], "backend_received_at": observed.isoformat(),
        "tick_age_seconds": 0.0, "candle_age_seconds": 0.0,
        "time_provenance": {"bar_open_time": stamp, "tick_time": stamp, "backend_received_at": observed.isoformat(),
                            "observation_time": None, "source_time_basis": BASIS,
                            "timezone_normalization_status": stamp["normalization_status"],
                            "raw_mt5_tick_time_msc": None, "replay": "bar open as tick (historical replay)"},
        "received_bars": 300, "source": "MT5", "timestamp": observed.isoformat()}
    quote = {"symbol": symbol, "broker_symbol": broker, "price": bid, "bid": bid, "ask": ask,
             "spread": ask - bid, "change_pct": 0.0}
    return ({**quote, **payload, **provenance, "timeframe": "M15", "higher_timeframes": ["H1", "H4"], "strategy_id": "smc",
             "strategy_version": smc.STRATEGY_VERSION, "strategy_mode": "LIVE"}, observed)


def main_fixture(symbol: str, when: str, out: Path) -> None:
    at = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)   # MT5 server time
    broker, point, frames = load(symbol, at)
    times = {tf: [b["time"] for b in rows] for tf, rows in frames.items()}
    k = bisect.bisect_left(times["M15"], at.timestamp())
    if k >= len(times["M15"]) or times["M15"][k] != at.timestamp():
        raise SystemExit(f"No M15 bar opens at {when} (server time)")
    with tempfile.TemporaryDirectory() as tmp, g.isolated_store(observations, Path(tmp)):
        # The bars before k are recorded too, so the episode reaches CONFIRMED through the normal lifecycle.
        store, seen, entry, exit_row = Path(tmp) / "setup_observations.jsonl", 0, None, None
        for i in range(k - 4, k + HORIZON):
            m, observed = market(symbol, broker, point, frames, times, i)
            g.FrozenClock.current = observed
            observations.record_markets([m])
            lines = store.read_text(encoding="utf-8").splitlines() if store.exists() else []
            row = json.loads(lines[-1]) if len(lines) > seen else None     # NO SETUP is not recorded
            seen = len(lines)
            if row is None:
                if i == k:
                    raise SystemExit(f"No SMC observation recorded at {when}: {m['state']} / {m['reason']}")
                continue
            if i == k:
                if not (row["lifecycle_state"] == "CONFIRMED" and row["rule_evidence"].get("strategy_valid") is True):
                    raise SystemExit(f"No confirmed SMC setup at {when}: {row['lifecycle_state']} / {m['reason']}")
                entry = row
            elif entry is not None:
                long = entry["direction"] == "LONG"
                bid, ask = m["bid"], m["ask"]
                exit_price = bid if long else ask
                stop, target = entry["proposed_stop_loss"], entry["proposed_take_profit"]
                if (exit_price <= stop or exit_price >= target) if long else (exit_price >= stop or exit_price <= target):
                    exit_row = row
                    break
    if entry is None or exit_row is None:
        raise SystemExit("No exit quote within the horizon")
    for row in (entry, exit_row):
        row["hq_provenance"] = {"source": "TRADEden historical replay (isolated store, frozen clock)",
                                "tool": "backend/tests/tools/smc_hq_replay_fixture.py", "mt5_server_bar_time": None}
    entry["hq_provenance"]["mt5_server_bar_time"] = when
    fixture = {"note": (f"Historical replay of a genuine TRADEden smc-confluence-v1 setup: {symbol} M15 bar {when} MT5 server "
                        "time, produced by TRADEden's own SMC strategy and observation recorder on actual MT5 history in an "
                        "isolated store. Quotes are bar opens with the recorded MT5 spread. No current-market trade is claimed."),
               "entry": entry, "exit_quote": exit_row}
    out.write_text(json.dumps(fixture, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(entry["observed_at"], entry["direction"], entry["setup_type"], entry["proposed_entry"], entry["proposed_stop_loss"],
          entry["proposed_take_profit"], "->", exit_row["observed_at"], exit_row["features"]["bid"], exit_row["features"]["ask"])


if __name__ == "__main__":
    main_fixture(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
