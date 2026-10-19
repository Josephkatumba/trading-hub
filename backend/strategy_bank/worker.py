"""Live Strategy Bank loop (only when TRADEDEN_STRATEGY_BANK_ENABLED=1; its own thread).

Every POLL_SECONDS it checks whether a new M15 bar has closed; if so, for each watched symbol it
fetches recent M15/H1/H4/D1 bars from MT5, drops each timeframe's still-forming bar, converts bar
times to UTC through the verified broker basis, reads the live quote, and runs the bank. Open
signals' outcomes are resolved every OUTCOME_SECONDS through signal_outcomes.resolve. Telegram
delivery runs only when TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED=1 as well. Never touches the
production scanner, its stores or the live notifier.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from market_time import normalize_mt5_epoch
from strategy_bank import engine, rules
from strategy_bank import telegram as bank_telegram

LOGGER = logging.getLogger("trading_hub.strategy_bank")
ENABLED_ENV = "TRADEDEN_STRATEGY_BANK_ENABLED"
POLL_SECONDS = 20.0
OUTCOME_SECONDS = 300.0
COUNTS = {"M15": 400, "H1": 400, "H4": 260, "D1": 60}
_STATUS: dict[str, Any] = {"running": False, "last_scan_at": None, "last_error": None, "signals_this_session": 0}


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "").strip() == "1"


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "telegram_enabled": bank_telegram.enabled(), **_STATUS}


def closed_bars(mt5: Any, broker: str, timeframe: str, count: int, basis: str, point: float) -> list[dict[str, Any]] | None:
    rates = mt5.copy_rates_from_pos(broker, getattr(mt5, f"TIMEFRAME_{timeframe}"), 0, count + 1)
    if rates is None or len(rates) < 2:
        return None
    bars = []
    for r in list(rates)[:-1]:                         # drop the forming bar: completed candles only
        stamp = normalize_mt5_epoch(int(r["time"]), basis)
        if stamp.get("normalization_status") != "VERIFIED":
            return None
        bars.append({"utc": datetime.fromisoformat(stamp["normalized_utc"]).timestamp(), "open": float(r["open"]),
                     "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]),
                     "tick_volume": int(r["tick_volume"]), "spread": int(r["spread"]) * point})
    return bars


def scan_symbol(mt5: Any, bank: engine.Bank, symbol: str, broker: str, basis: str, now: float) -> list[dict[str, Any]]:
    info, tick = mt5.symbol_info(broker), mt5.symbol_info_tick(broker)
    if info is None or tick is None:
        return []
    frames = {}
    for tf, count in COUNTS.items():
        bars = closed_bars(mt5, broker, tf, count, basis, float(info.point))
        if not bars:
            return []
        frames[tf] = bars
    raw = float(tick.time_msc) / 1000 if getattr(tick, "time_msc", 0) else float(tick.time)
    stamp = normalize_mt5_epoch(raw, basis)
    age = (now - datetime.fromisoformat(stamp["normalized_utc"]).timestamp()) if stamp.get("normalization_status") == "VERIFIED" else None
    quote = {"bid": float(tick.bid), "ask": float(tick.ask), "tick_age_seconds": age,
             "basis": f"live MT5 quote at confirmation (tick age {age:.0f}s)" if age is not None else "live MT5 quote"}
    return bank.scan(rules.Ctx(symbol, frames), quote, now)


def resolve_open(bank: engine.Bank, fetch: Callable, broker_of: Callable[[str], str | None]) -> int:
    updated = 0
    now = datetime.now(timezone.utc)
    for s in list(bank.store.signals.values()):
        if s.get("outcome_status") in engine.FINAL:
            continue
        broker = broker_of(s["symbol"])
        confirmed = datetime.fromisoformat(s["confirmed_at"])
        if not broker:
            continue
        m15 = fetch(broker, "M15", confirmed - timedelta(minutes=15), now)
        if m15 is None:
            continue
        m1 = fetch(broker, "M1", confirmed - timedelta(minutes=1), now) or []
        result = engine.resolve_signal(s, m15, m1, now)
        if result["status"] != s.get("outcome_status"):
            bank.store.put_signal({**s, "outcome_status": result["status"], "r_multiple": result.get("r_multiple"),
                                   "outcome_at": result.get("hit_at"), "outcome_method": result.get("method"),
                                   "outcome_reason": result.get("reason")})
            updated += 1
    return updated


def run(stop: threading.Event, mt5: Any, ensure: Callable[[], tuple[bool, str | None]],
        broker_of: Callable[[str], str | None], watchlist: list[str]) -> None:
    import signal_outcomes
    basis = os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE")
    if not basis:
        _STATUS["last_error"] = "TRADING_HUB_MT5_SOURCE_TIMEZONE not set: bar times unverifiable, bank not started"
        return
    from observations import confirmation_events
    bank = engine.Bank(production_confirmations=lambda: confirmation_events()[-200:])
    fetch = signal_outcomes.mt5_fetch(mt5, ensure, basis)
    alerts = None
    if bank_telegram.enabled():
        import telegram_notifier as tn
        try:
            alerts = bank_telegram.BankAlerts(tn.TelegramClient(os.getenv(tn.TOKEN_ENV, "")), os.getenv(tn.CHAT_ENV, ""), bank.store)
        except ValueError as exc:
            _STATUS["last_error"] = f"bank Telegram not started: {exc}"
    _STATUS["running"] = True
    last_bar = last_outcomes = 0.0
    try:
        while not stop.is_set():
            try:
                now = time.time()
                bar = now - now % 900
                if bar > last_bar and now - bar >= 5:          # a new M15 bar closed (5 s settling time)
                    ok, error = ensure()
                    if ok:
                        for symbol in watchlist:
                            broker = broker_of(symbol)
                            if broker:
                                _STATUS["signals_this_session"] += len(scan_symbol(mt5, bank, symbol, broker, basis, now))
                        last_bar = bar
                        _STATUS.update(last_scan_at=datetime.now(timezone.utc).isoformat(), last_error=None)
                    else:
                        _STATUS["last_error"] = f"MT5 unavailable: {error}"
                if now - last_outcomes >= OUTCOME_SECONDS:
                    resolve_open(bank, fetch, broker_of)
                    last_outcomes = now
                if alerts:
                    alerts.deliver()
            except Exception as exc:
                _STATUS["last_error"] = f"{type(exc).__name__}: {exc}"
                LOGGER.exception("Strategy bank cycle failed")
            stop.wait(POLL_SECONDS)
    finally:
        _STATUS["running"] = False
