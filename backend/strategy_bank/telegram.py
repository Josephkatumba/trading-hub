"""Strategy Bank Telegram alerts (behind TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED, default off).

Reuses the live notifier's client, notification store class, formatting helpers and disclaimer
WITHOUT modifying telegram_notifier.py or signal_presentation.py: bank alerts use their own
dedupe file (data/strategy_bank/telegram_notifications.jsonl), so the live alert stream is untouched.

One alert per OPPORTUNITY (the first strategy that confirmed it); later confirmations of the same
symbol and direction are merged and attributed, never re-alerted. Opportunities already alerted by
a production strategy (#1-3 or SMC / Trend-Momentum) are not re-sent. Alerts older than
MAX_ALERT_AGE are never sent late.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from strategy_bank import engine

LOGGER = logging.getLogger("trading_hub.strategy_bank.telegram")
ENABLED_ENV = "TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED"
MAX_ALERT_AGE = 600.0
DISCLAIMER = "⚠️ Experimental signal. This strategy has not demonstrated reliable profitability. Trading involves risk."


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "").strip() == "1"


def message(signal: dict[str, Any]) -> str:
    """Trader-facing HTML alert (T-034 format): no internal ids or version numbers. The
    contradicting-evidence line appears only when the bank recorded such a condition."""
    import telegram_notifier as tn
    from signal_presentation import esc
    direction = "BUY" if signal["direction"] == "LONG" else "SELL"
    notes = [str(n) for n in (signal.get("contradictions") or [])][:2]
    lines = [f"📊 <b>{esc(signal['symbol'])}</b> | {'🟢' if direction == 'BUY' else '🔴'} <b>{direction}</b>",
             f"📈 Strategy: {esc(signal['strategy_name'])}",
             f"⏱ Timeframe: {esc(signal['timeframe'])}",
             "",
             f"➡️ Entry: <b>{tn._price(signal['entry'])}</b>",
             f"🛑 Stop Loss: <b>{tn._price(signal['stop_loss'])}</b>",
             f"🎯 Take Profit: <b>{tn._price(signal['take_profit'])}</b>",
             f"⚖️ Risk/Reward: 1:{float(signal['rr']):.2f}",
             f"🕒 Confirmed: {tn.eat(datetime.fromisoformat(signal['confirmed_at']))}"]
    if signal.get("time_exit_at"):
        lines.append(f"⌛ Time exit: {tn.eat(datetime.fromisoformat(signal['time_exit_at']))}")
    lines += ["", "💡 <b>Trade rationale:</b>", esc(signal["explanation"])]
    if notes:
        lines += ["", "⚖️ <b>Contradicting evidence:</b>", esc(" ".join(f"{n[0].upper()}{n[1:]}." for n in notes))]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


class BankAlerts:
    def __init__(self, client: Any, chat_id: str, store: engine.BankStore, clock=lambda: time.time()) -> None:
        import telegram_notifier as tn
        self.client, self.chat_id, self.store, self.clock = client, str(chat_id), store, clock
        self.sent = tn.NotificationStore(store.folder / "telegram_notifications.jsonl")
        self._last = 0.0

    def deliver(self) -> int:
        import telegram_notifier as tn
        sent = 0
        now = self.clock()
        for s in sorted(self.store.signals.values(), key=lambda s: s["confirmed_at"]):
            if s.get("alert") != "primary":
                continue
            key = "bank:" + s["opportunity_id"]
            state = self.sent.get(key)
            if state and state.get("status") in ("sent", "failed", "expired"):
                continue
            if now - datetime.fromisoformat(s["confirmed_at"]).timestamp() > MAX_ALERT_AGE:
                self.sent.record(key, status="expired", signal_id=s["signal_id"])
                continue
            wait = tn.MIN_SEND_INTERVAL_SECONDS - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            attempts = int((state or {}).get("attempts") or 0) + 1
            try:
                result = self.client.send_message(self.chat_id, message(s), parse_mode="HTML")
            except tn.TelegramError as exc:
                final = not exc.retryable or attempts >= tn.MAX_ATTEMPTS
                self.sent.record(key, status="failed" if final else "pending", attempts=attempts, error=str(exc),
                                 signal_id=s["signal_id"])
                if exc.status == 429:
                    break
                continue
            self.sent.record(key, status="sent", attempts=attempts, signal_id=s["signal_id"],
                             message_id=(result or {}).get("message_id"), sent_at=datetime.now(timezone.utc).isoformat())
            sent += 1
        return sent
