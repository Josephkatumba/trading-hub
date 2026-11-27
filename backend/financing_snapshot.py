"""Read-only, append-only record of broker financing metadata (prepared 2026-10-20).

Purpose: make future overnight evaluation (e.g. index CFDs, swap modes 2/3) possible by
recording, once per UTC day and symbol, what the broker states at that time:
currencies, contract size and the swap specification. History before capture starts
stays unknown; nothing here is back-filled or assumed.

* Uses `symbol_info` objects the scanner has ALREADY fetched (no extra MT5 calls, no new
  session) and only the account currency string (no login, balance or credentials).
* Never computes a cost it cannot verify: `price_units_per_lot_night` is filled only for
  swap mode 1 (points) and for modes 2/3 when the swap currency equals the profit currency.
  Everything else is recorded raw with `price_units_per_lot_night: null` and a reason.
* Dividend adjustments on index CFDs are not exposed by MT5 and are NOT included.
* Append-only JSONL; existing lines are never rewritten. Off unless
  TRADEDEN_FINANCING_SNAPSHOT_ENABLED=1.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENABLED_ENV = "TRADEDEN_FINANCING_SNAPSHOT_ENABLED"
SWAP_MODES = {0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL", 3: "CURRENCY_MARGIN", 4: "CURRENCY_DEPOSIT",
              5: "INTEREST_CURRENT", 6: "INTEREST_OPEN", 7: "REOPEN_CURRENT", 8: "REOPEN_BID"}
FIELDS = ("currency_base", "currency_profit", "currency_margin", "trade_contract_size", "point", "trade_tick_size",
          "trade_tick_value", "swap_mode", "swap_long", "swap_short", "swap_rollover3days")
_lock = threading.Lock()
_seen: set[tuple[str, str]] = set()


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "").strip() == "1"


def default_path() -> Path:
    from storage_config import data_directory
    return data_directory() / "financing" / "swap_snapshots.jsonl"


def _value(info: Any, name: str) -> Any:
    value = info.get(name) if isinstance(info, dict) else getattr(info, name, None)
    return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def price_units(record: dict[str, Any], side: str) -> tuple[float | None, str]:
    """Swap per lot per night in price units, only where the conversion is verifiable."""
    mode, swap = record["swap_mode"], record[f"swap_{side}"]
    if swap is None or mode is None:
        return None, "swap specification unavailable"
    if mode == 0:
        return 0.0, "swaps disabled"
    if mode == 1:
        return (swap * record["point"], "points x point") if record["point"] else (None, "point unavailable")
    if mode in (2, 3):
        currency = record["currency_base"] if mode == 2 else record["currency_margin"]
        if not currency or currency != record["currency_profit"]:
            return None, f"swap currency {currency} differs from profit currency {record['currency_profit']}; conversion not assumed"
        size = record["trade_contract_size"]
        return (swap / size, "money per lot / contract size (same currency)") if size else (None, "contract size unavailable")
    return None, f"mode {SWAP_MODES.get(mode, mode)} not converted"


def record_from_info(product: str, broker_symbol: str, info: Any, account_currency: str | None, at: datetime) -> dict[str, Any]:
    record = {"captured_utc": at.astimezone(timezone.utc).isoformat(), "utc_day": at.astimezone(timezone.utc).date().isoformat(),
              "product": product, "broker_symbol": broker_symbol, "account_currency": account_currency,
              **{name: _value(info, name) for name in FIELDS}}
    record["swap_mode_name"] = SWAP_MODES.get(record["swap_mode"])
    for side in ("long", "short"):
        record[f"price_units_per_lot_night_{side}"], record[f"conversion_{side}"] = price_units(record, side)
    record["excluded"] = "index CFD dividend adjustments (not exposed by MT5); historical rates before first capture"
    record["source"] = "MT5 symbol_info already fetched by the scanner (read-only)"
    return record


def offer(product: str, broker_symbol: str, info: Any, account_currency: str | None = None,
          path: Path | None = None, now: datetime | None = None) -> bool:
    """Append one record per (product, UTC day). Returns True when a line was written."""
    if not enabled() or info is None:
        return False
    now = now or datetime.now(timezone.utc)
    key = (product, now.astimezone(timezone.utc).date().isoformat())
    path = Path(path or default_path())
    with _lock:
        if key in _seen:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():  # survive restarts without duplicating the day
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    _seen.add((row["product"], row["utc_day"]))
            if key in _seen:
                return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record_from_info(product, broker_symbol, info, account_currency, now), allow_nan=False) + "\n")
        _seen.add(key)
        return True
