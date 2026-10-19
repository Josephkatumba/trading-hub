"""MT5 bar history for research: downloaded once, cached locally, normalised to UTC.

Each cached bar keeps the raw MT5 epoch (`time`, what production strategies receive)
and the verified UTC open time (`utc`, what the simulator and reports use). Bars whose
time cannot be normalised through the verified broker basis are dropped, never guessed.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from market_time import normalize_mt5_epoch
from storage_config import data_directory

TIMEFRAME_SECONDS = {"M1": 60, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
WARMUP_DAYS = {"M15": 60, "H1": 60, "H4": 90, "D1": 420}
DEFAULT_BASIS = "America/New_York+07:00"      # verified for IC Markets (TIMESTAMP_AUDIT_REPORT.md)


def cache_dir() -> Path:
    return data_directory() / "research" / "bars"


def basis() -> str:
    return os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE") or DEFAULT_BASIS


def _path(symbol: str, timeframe: str) -> Path:
    return cache_dir() / f"{symbol}_{timeframe}.json.gz"


def load(symbol: str, timeframe: str) -> list[dict[str, Any]]:
    path = _path(symbol, timeframe)
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def save(symbol: str, timeframe: str, bars: list[dict[str, Any]]) -> None:
    path = _path(symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        json.dump(bars, handle, separators=(",", ":"))
    tmp.replace(path)


def normalise(rates: Any, point: float, source_basis: str | None = None) -> list[dict[str, Any]]:
    source_basis = source_basis or basis()
    bars = []
    for rate in rates:
        stamp = normalize_mt5_epoch(int(rate["time"]), source_basis)
        if stamp.get("normalization_status") != "VERIFIED":
            continue
        bars.append({"time": float(rate["time"]),
                     "utc": datetime.fromisoformat(stamp["normalized_utc"]).timestamp(),
                     "open": float(rate["open"]), "high": float(rate["high"]),
                     "low": float(rate["low"]), "close": float(rate["close"]),
                     "tick_volume": int(rate["tick_volume"]),
                     "spread": int(rate["spread"]) * point})       # price units, as the broker recorded it
    return bars


def download(mt5: Any, broker_symbol: str, timeframe: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Bars in [start, end] (server-time request window, padded by a day on each side)."""
    info = mt5.symbol_info(broker_symbol)
    if info is None:
        mt5.symbol_select(broker_symbol, True)
        info = mt5.symbol_info(broker_symbol)
    if info is None:
        raise LookupError(f"{broker_symbol} is not available on this terminal")
    code = getattr(mt5, f"TIMEFRAME_{timeframe}")
    lo, hi = (start - timedelta(days=1)).replace(tzinfo=None), (end + timedelta(days=1)).replace(tzinfo=None)
    if timeframe == "M1":
        # The terminal caps one request at max_bars; M1 is fetched in 30-day chunks.
        rates, cursor = [], lo
        while cursor < hi:
            chunk = mt5.copy_rates_range(broker_symbol, code, cursor, min(hi, cursor + timedelta(days=30)))
            if chunk is not None:
                rates.extend(chunk)
            cursor += timedelta(days=30)
    else:
        rates = mt5.copy_rates_range(broker_symbol, code, lo, hi)
        rates = [] if rates is None else list(rates)
    seen, unique = set(), []
    for rate in sorted(rates, key=lambda r: int(r["time"])):
        if int(rate["time"]) not in seen:
            seen.add(int(rate["time"]))
            unique.append(rate)
    return normalise(unique, float(info.point))


def symbol_meta(mt5: Any, broker_symbol: str) -> dict[str, Any]:
    info = mt5.symbol_info(broker_symbol)
    return {"broker_symbol": broker_symbol, "digits": info.digits, "point": info.point,
            "tick_size": info.trade_tick_size or info.point, "tick_value": info.trade_tick_value,
            "contract_size": info.trade_contract_size,
            # Overnight financing (simulate.financing_per_night): the broker's CURRENT swap spec,
            # used as an approximation of historical rates.
            "swap_mode": info.swap_mode, "swap_long": info.swap_long, "swap_short": info.swap_short,
            "swap_rollover3days": info.swap_rollover3days,
            "swap_snapshot_utc": datetime.now(timezone.utc).isoformat()}


def refresh(symbols: dict[str, str], start: datetime, end: datetime | None = None,
            timeframes: tuple[str, ...] = ("M15", "H1", "H4", "D1", "M1")) -> dict[str, Any]:
    """Download and cache every timeframe for {symbol: broker_symbol}; returns a manifest."""
    import MetaTrader5 as mt5
    end = end or datetime.now(timezone.utc)
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    manifest: dict[str, Any] = {"basis": basis(), "start": start.isoformat(), "end": end.isoformat(), "symbols": {}}
    try:
        for symbol, broker in symbols.items():
            entry = {"meta": symbol_meta(mt5, broker)} if mt5.symbol_info(broker) else {"error": "unavailable"}
            if "error" not in entry:
                for timeframe in timeframes:
                    # Strategies need COUNTS closed bars before the first evaluated bar
                    # (200 D1 bars is ~290 calendar days).
                    warmup = timedelta(days=WARMUP_DAYS.get(timeframe, 0))
                    bars = download(mt5, broker, timeframe, start - warmup, end)
                    save(symbol, timeframe, bars)
                    entry[timeframe] = {"bars": len(bars),
                                        "first": datetime.fromtimestamp(bars[0]["utc"], timezone.utc).isoformat() if bars else None,
                                        "last": datetime.fromtimestamp(bars[-1]["utc"], timezone.utc).isoformat() if bars else None}
            manifest["symbols"][symbol] = entry
    finally:
        mt5.shutdown()
    (cache_dir() / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def manifest() -> dict[str, Any]:
    path = cache_dir() / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
