"""Developer tool: capture real MT5 bars as scanner test fixtures (read-only).

Usage (from backend/, with the MT5 terminal open):
    python tests/tools/capture_scanner_fixtures.py

Writes tests/fixtures/scanner/real_<SYMBOL>.json containing exactly the inputs
main.market_snapshot passes to scanner.analyze_symbol: M15 rows (300), H1 rows
(160) and the spread. Nothing is traded, subscribed or written to MT5.
Session context is deliberately left out: it depends on wall-clock time.

Re-capturing replaces the fixtures, so the golden file must be regenerated
deliberately afterwards (tests/tools/regen_scanner_golden.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

OFFICIAL_SCAN = ["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "NAS100", "US500", "GER40"]
EXTRA_ALIASES = {"GER40": ["GER40", "DE40", "DAX40", "GER30", "DE30"]}   # not in main.SYMBOL_ALIASES yet


def rows_from(rates):
    return [{"time": float(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])} for r in rates]


def main() -> int:
    import MetaTrader5 as mt5
    import main as engine
    if not mt5.initialize():
        print("MT5 terminal unavailable:", mt5.last_error())
        return 1
    out_dir = Path(__file__).resolve().parents[1] / "fixtures" / "scanner"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        for symbol in OFFICIAL_SCAN:
            engine.SYMBOL_ALIASES.setdefault(symbol, EXTRA_ALIASES.get(symbol, [symbol]))
            actual = engine.mt5_symbol(symbol)
            if not actual:
                print(f"{symbol}: not available at this broker, skipped")
                continue
            rates = mt5.copy_rates_from_pos(actual, mt5.TIMEFRAME_M15, 0, 300)
            h1 = mt5.copy_rates_from_pos(actual, mt5.TIMEFRAME_H1, 0, 160)
            tick = mt5.symbol_info_tick(actual)
            if rates is None or h1 is None or tick is None:
                print(f"{symbol}: no data, skipped")
                continue
            spread = abs(float(tick.ask) - float(tick.bid)) if tick.ask and tick.bid else 0.0
            fixture = {"name": "real_" + symbol, "symbol": symbol, "broker_symbol": actual,
                       "source": "MT5 capture (read-only)", "spread": spread,
                       "rows": rows_from(rates), "higher_rows": rows_from(h1), "session_context": None}
            (out_dir / f"real_{symbol}.json").write_text(json.dumps(fixture, separators=(",", ":")), encoding="utf-8")
            print(f"{symbol}: {actual} captured ({len(fixture['rows'])} M15, {len(fixture['higher_rows'])} H1)")
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
