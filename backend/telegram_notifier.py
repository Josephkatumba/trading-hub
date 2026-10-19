"""Telegram delivery of confirmed TRADEden signals and of their verified outcomes.

Read-only with respect to the engine: the notifier never changes strategy logic, risk
parameters, qualification or execution. It follows two existing stores, in its own
thread, so a slow or failing Telegram API can never delay a market scan:

  setup_confirmations.jsonl  a new LIVE, non-shadow confirmation whose snapshot passed
                             the executable-price qualification -> one signal alert
  market_outcomes.jsonl      a verified WIN/LOSS (strategy_lab.classify_outcome, the same
                             rule as the Strategy Lab and performance report) of a signal
                             that was alerted -> one outcome follow-up

Never replayed: on first activation every existing confirmation is recorded as
`baseline` and never sent; afterwards a confirmation first seen more than
MAX_SIGNAL_AGE_SECONDS after it was confirmed (engine or notifier was down) is skipped,
and an alert still undelivered MAX_DELIVERY_DELAY_SECONDS after confirmation expires.

Every decision is appended to telegram_notifications.jsonl in the data directory (the
latest record per key wins), so duplicates are prevented across restarts.

Configuration (environment, e.g. backend/.env; never committed):
  TRADEDEN_TELEGRAM_BOT_TOKEN       the BotFather token (secret; never logged or printed)
  TRADEDEN_TELEGRAM_CHAT_ID         the private chat to deliver to (telegram_setup.py discover)
  TRADEDEN_TELEGRAM_ALERTS_ENABLED  "1" starts the notifier with the engine (default off)
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from storage_config import data_directory

LOGGER = logging.getLogger("trading_hub.telegram")
# httpx logs every request URL at INFO, and a Bot API URL contains the token.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

API_BASE = "https://api.telegram.org"
TOKEN_ENV = "TRADEDEN_TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TRADEDEN_TELEGRAM_CHAT_ID"
ENABLED_ENV = "TRADEDEN_TELEGRAM_ALERTS_ENABLED"
TEST_MESSAGE = "✅ Tradeden Telegram integration successful. Your trading alerts are now connected."

EAT = timezone(timedelta(hours=3), "EAT")
POLL_SECONDS = 5.0
OUTCOME_POLL_SECONDS = 60.0
MAX_SIGNAL_AGE_SECONDS = 600.0          # older when first seen: never sent as a new alert
MAX_DELIVERY_DELAY_SECONDS = 1800.0     # an undelivered signal alert is dropped after this
OUTCOME_TRACK_SECONDS = 48 * 3600.0     # longest outcome horizon (24h) plus resolution slack
MIN_SEND_INTERVAL_SECONDS = 1.1         # Telegram: about one message per second per chat
MAX_ATTEMPTS = 8
MAX_BACKOFF_SECONDS = 300.0
TERMINAL_LIFECYCLE = ("INVALIDATED", "EXPIRED", "RESOLVED")
STRATEGY_NAMES = {"trendline": "Trendline", "trendline_v5": "Trendline", "support_resistance": "Support & Resistance",
                  "trend_momentum": "Trend / Momentum", "smc": "Smart Money Concepts"}
DISCLAIMER = "Signal only: not an executed trade and not financial advice. TRADEden execution is disabled."


def notifications_file() -> Path:
    return data_directory() / "telegram_notifications.jsonl"


def alerts_enabled() -> bool:
    return os.getenv(ENABLED_ENV, "").strip() == "1"


def _redact(text: str, token: str | None) -> str:
    text = str(text)
    if token:
        text = text.replace(token, "<token>")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]{20,}", "bot<token>", text)


# ----- Bot API client -------------------------------------------------------------------

class TelegramError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status, self.retryable, self.retry_after = status, retryable, retry_after


class TelegramClient:
    """Minimal Bot API client. Errors never carry the token (no exception chaining: an
    httpx exception's request holds the URL, which contains the token)."""

    def __init__(self, token: str, timeout: float = 10.0, transport: httpx.BaseTransport | None = None) -> None:
        if not token or not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token.strip()):
            raise ValueError(f"{TOKEN_ENV} is missing or not a BotFather token")
        self._token = token.strip()
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:
        return "TelegramClient(<token>)"

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            response = self._http.post(f"{API_BASE}/bot{self._token}/{method}", json=payload or {})
        except httpx.HTTPError as exc:
            raise TelegramError(f"network error ({type(exc).__name__})", retryable=True) from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and body.get("ok") is True:
            return body.get("result")
        status = response.status_code
        retry_after = (body.get("parameters") or {}).get("retry_after") if isinstance(body, dict) else None
        description = _redact(str(body.get("description") or f"HTTP {status}"), self._token)
        raise TelegramError(description, status, retryable=status == 429 or status >= 500,
                            retry_after=float(retry_after) if isinstance(retry_after, (int, float)) else None)

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe")

    def get_updates(self) -> list[dict[str, Any]]:
        return self._call("getUpdates", {"timeout": 0, "allowed_updates": ["message", "my_chat_member"]}) or []

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        return self._call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})


def private_chats(updates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{chat_id: chat} of the private chats that wrote to (or started) the bot."""
    chats: dict[str, dict[str, Any]] = {}
    for update in updates:
        for key in ("message", "my_chat_member", "edited_message"):
            chat = (update.get(key) or {}).get("chat") or {}
            if chat.get("type") == "private" and chat.get("id") is not None:
                chats[str(chat["id"])] = chat
    return chats


# ----- notification history ---------------------------------------------------------------

class NotificationStore:
    """Append-only history; the latest record per key is the current state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or notifications_file()
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            with self.path.open("rb") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(row, dict) and row.get("key"):
                        self._state[str(row["key"])] = row

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._state.get(key)

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._state.values())

    def record(self, key: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            row = {**self._state.get(key, {}), **fields, "key": key,
                   "record_type": "telegram_notification", "updated_at": datetime.now(timezone.utc).isoformat()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as handle:
                if handle.tell() > 0:
                    with self.path.open("rb") as reader:
                        reader.seek(-1, os.SEEK_END)
                        if reader.read(1) != b"\n":
                            handle.write(b"\n")
                handle.write((json.dumps(row, separators=(",", ":"), default=str) + "\n").encode("utf-8"))
            self._state[key] = row
            return row


# ----- engine data source -------------------------------------------------------------------

class EngineSource:
    """The engine's stores, read through their indexes (never a full outcome-file read)."""

    def snapshot(self, observation_id: str) -> dict[str, Any] | None:
        from observations import snapshots_by_observation_id
        return snapshots_by_observation_id([observation_id]).get(observation_id)

    def lifecycle_state(self, setup_id: str) -> str | None:
        from observations import lifecycle_events
        events = [row for row in lifecycle_events(setup_id) if row.get("to_state")]
        return events[-1]["to_state"] if events else None

    def strategy_mode(self, strategy_id: str) -> str:
        from strategies import REGISTRY
        try:
            return REGISTRY.mode(strategy_id)
        except KeyError:
            return "UNREGISTERED"

    def verified_outcome(self, confirmation: dict[str, Any], snapshot: dict[str, Any] | None
                         ) -> tuple[str, str | None, dict[str, Any] | None]:
        """(kind, horizon, deciding outcome) by the Strategy Lab rule: only outcomes that pass
        the dataset integrity checks count; the shortest verified WIN/LOSS horizon decides."""
        from outcomes import MARKET_OUTCOMES_FILE, outcomes_for_setup
        from strategy_lab import classify_outcome
        rows = outcomes_for_setup(str(confirmation.get("setup_id")), MARKET_OUTCOMES_FILE)
        kind, horizon = classify_outcome(confirmation, rows, snapshot)
        deciding = next((row for row in rows if row.get("horizon") == horizon and
                         str(row.get("observation_id")) == str(confirmation.get("observation_id"))), None)
        return kind, horizon, deciding


# ----- message formatting --------------------------------------------------------------------

def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _price(value: Any) -> str:
    number = _number(value)
    return "unavailable" if number is None else (f"{number:.8f}".rstrip("0").rstrip("."))


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def eat(value: datetime | None) -> str:
    return value.astimezone(EAT).strftime("%Y-%m-%d %H:%M:%S EAT (UTC+3)") if value else "unavailable"


def strategy_name(strategy_id: str | None) -> str:
    return STRATEGY_NAMES.get(str(strategy_id), str(strategy_id or "unknown").replace("_", " ").title())


def side(direction: Any) -> str:
    return {"LONG": "BUY", "SHORT": "SELL"}.get(str(direction), "UNKNOWN")


def signal_message(confirmation: dict[str, Any], plan: dict[str, Any]) -> str:
    direction = side(plan.get("direction"))
    rr = _number(plan.get("rr"))
    lines = [("🟢" if direction == "BUY" else "🔴") + " TRADEden CONFIRMED SIGNAL",
             "",
             f"Instrument: {confirmation.get('symbol')}",
             f"Direction: {direction}",
             f"Strategy: {strategy_name(confirmation.get('strategy_id'))} ({confirmation.get('strategy_version')})",
             f"Entry: {_price(plan.get('entry'))}",
             f"Stop loss: {_price(plan.get('stop_loss'))}",
             f"Take profit: {_price(plan.get('take_profit'))}",
             f"Risk/reward: 1:{rr:.2f} (at the executable price, spread included)" if rr is not None
             else "Risk/reward: unavailable",
             f"Confirmed: {eat(_parse_time(confirmation.get('confirmed_at')))}",
             f"Signal ID: {confirmation.get('setup_id')}",
             "",
             DISCLAIMER]
    return "\n".join(lines)


def _delta(text: Any) -> timedelta | None:
    """str(timedelta) back to a timedelta ('0:45:00', '1 day, 2:00:00')."""
    match = re.fullmatch(r"(?:(\d+) days?, )?(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", str(text or ""))
    if not match:
        return None
    days, hours, minutes, seconds = match.groups()
    return timedelta(days=int(days or 0), hours=int(hours), minutes=int(minutes), seconds=float(seconds))


def outcome_message(signal: dict[str, Any], kind: str, horizon: str | None, outcome: dict[str, Any] | None,
                    r_multiple: float | None) -> str:
    target = kind == "verified_target"
    confirmed = _parse_time(signal.get("confirmed_at"))
    lines = [("🎯 TRADEden SIGNAL OUTCOME: TAKE PROFIT REACHED" if target
              else "🛑 TRADEden SIGNAL OUTCOME: STOP LOSS REACHED"),
             "",
             f"Instrument: {signal.get('symbol')} · {side(signal.get('direction'))} · {strategy_name(signal.get('strategy_id'))}",
             f"Signal ID: {signal.get('setup_id')}",
             f"Signal confirmed: {eat(confirmed)}",
             (f"Take profit {_price(signal.get('take_profit'))} was reached before the stop loss."
              if target else f"Stop loss {_price(signal.get('stop_loss'))} was reached before the take profit.")]
    offset = _delta((outcome or {}).get("time_to_favorable_movement" if target else "time_to_adverse_movement"))
    if confirmed and offset is not None:
        lines.append(f"Reached during the {signal.get('timeframe') or 'M15'} candle opening {eat(confirmed + offset)}.")
    if r_multiple is not None:
        lines.append(f"Signal result: {r_multiple:+.2f}R")
    lines += [f"Verified from completed MT5 candles ({horizon} window).",
              "",
              "This is the outcome of the signal's market path, NOT of an executed trade. TRADEden opened no position."]
    return "\n".join(lines)


# ----- notifier -------------------------------------------------------------------------------------

class TelegramNotifier:
    def __init__(self, client: TelegramClient, chat_id: str, store: NotificationStore,
                 confirmations_file: Path | None = None, source: Any = None,
                 clock: Callable[[], datetime] | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        if confirmations_file is None:
            from observations import CONFIRMATIONS_FILE
            confirmations_file = CONFIRMATIONS_FILE
        self.client, self.chat_id, self.store = client, str(chat_id), store
        self.confirmations_file = Path(confirmations_file)
        self.source = source or EngineSource()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self._offset: int | None = None
        self._last_send = 0.0
        self._last_outcome_poll: datetime | None = None
        self._waiting: dict[str, dict[str, Any]] = {}   # confirmations whose snapshot is not readable yet

    # -- discovery ------------------------------------------------------------------------------
    def _new_confirmations(self) -> list[dict[str, Any]]:
        """Complete lines appended since the last call (all lines on the first call)."""
        path = self.confirmations_file
        if not path.exists():
            return []
        size = path.stat().st_size
        if self._offset is None or size < self._offset:
            self._offset = 0
        if size == self._offset:
            return []
        with path.open("rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read(size - self._offset)
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        self._offset += end + 1
        rows = []
        for line in chunk[:end].splitlines():
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(row, dict) and row.get("setup_id"):
                rows.append(row)
        return rows

    def discover_signals(self) -> None:
        first_pass = self._offset is None
        rows = self._new_confirmations()
        if first_pass and self.store.get("meta:baseline") is None:
            # First activation: everything already confirmed is history, never an alert.
            for row in rows:
                if self.store.get(f"signal:{row['setup_id']}") is None:
                    self.store.record(f"signal:{row['setup_id']}", kind="signal", setup_id=row["setup_id"],
                                      status="baseline", confirmed_at=row.get("confirmed_at"))
            self.store.record("meta:baseline", kind="meta", status="baseline", count=len(rows),
                              offset=self._offset)
            return
        for row in rows:
            self._waiting.setdefault(str(row["setup_id"]), row)
        for setup_id, row in list(self._waiting.items()):
            if self._consider(row):
                self._waiting.pop(setup_id, None)

    def _consider(self, confirmation: dict[str, Any]) -> bool:
        """Queue or skip one confirmation; False to look at it again next tick."""
        setup_id = str(confirmation["setup_id"])
        key = f"signal:{setup_id}"
        if self.store.get(key) is not None:
            return True
        base = {"kind": "signal", "setup_id": setup_id, "confirmed_at": confirmation.get("confirmed_at"),
                "observation_id": confirmation.get("observation_id")}

        def skip(reason: str) -> bool:
            self.store.record(key, **base, status="skipped", reason=reason)
            return True

        if confirmation.get("record_type") not in (None, "setup_confirmation"):
            return skip("not_a_confirmation")
        if confirmation.get("shadow") is True:
            return skip("shadow_strategy")
        if self.source.strategy_mode(str(confirmation.get("strategy_id") or "trendline")) != "LIVE":
            return skip("strategy_not_live")
        confirmed_at = _parse_time(confirmation.get("confirmed_at"))
        if confirmed_at is None:
            return skip("confirmation_time_unavailable")
        if (self.clock() - confirmed_at).total_seconds() > MAX_SIGNAL_AGE_SECONDS:
            return skip("stale_not_new")
        snapshot = self.source.snapshot(str(confirmation.get("observation_id")))
        if snapshot is None:
            return False          # the snapshot index may not have caught up yet
        evidence = snapshot.get("rule_evidence") or {}
        if evidence.get("strategy_valid") is not True or (evidence.get("qualification") or {}).get("qualified") is not True:
            return skip("not_qualified")
        from observations import confirmed_plan
        plan = confirmed_plan(snapshot) or {}
        if plan.get("direction") not in ("LONG", "SHORT") or any(
                _number(plan.get(name)) is None for name in ("entry", "stop_loss", "take_profit")):
            return skip("incomplete_plan")
        state = self.source.lifecycle_state(setup_id)
        if state in TERMINAL_LIFECYCLE:
            return skip(f"lifecycle_{state.lower()}")
        self.store.record(key, **base, status="pending", attempts=0, next_attempt_at=None,
                          symbol=confirmation.get("symbol"), direction=plan.get("direction"),
                          strategy_id=confirmation.get("strategy_id"), timeframe=snapshot.get("timeframe"),
                          entry=plan.get("entry"), stop_loss=plan.get("stop_loss"), take_profit=plan.get("take_profit"),
                          text=signal_message(confirmation, plan))
        return True

    # -- outcomes ---------------------------------------------------------------------------------
    def discover_outcomes(self, force: bool = False) -> None:
        now = self.clock()
        if not force and self._last_outcome_poll and (now - self._last_outcome_poll).total_seconds() < OUTCOME_POLL_SECONDS:
            return
        self._last_outcome_poll = now
        for signal in self.store.items():
            if signal.get("kind") != "signal" or signal.get("status") != "sent":
                continue
            key = f"outcome:{signal['setup_id']}"
            if self.store.get(key) is not None:
                continue
            confirmed_at = _parse_time(signal.get("confirmed_at"))
            snapshot = self.source.snapshot(str(signal.get("observation_id")))
            kind, horizon, outcome = self.source.verified_outcome(
                {"setup_id": signal["setup_id"], "observation_id": signal.get("observation_id")}, snapshot)
            if kind in ("verified_target", "verified_stop"):
                from performance import _plan_r, _r_multiple
                self.store.record(key, kind="outcome", setup_id=signal["setup_id"], status="pending", attempts=0,
                                  next_attempt_at=None, outcome=kind, horizon=horizon,
                                  text=outcome_message(signal, kind, horizon, outcome, _r_multiple(kind, _plan_r(snapshot))))
            elif confirmed_at is None or (now - confirmed_at).total_seconds() > OUTCOME_TRACK_SECONDS:
                # No verified TP/SL: nothing is inferred and nothing is sent.
                self.store.record(key, kind="outcome", setup_id=signal["setup_id"], status="skipped",
                                  reason=f"no_verified_tp_sl ({kind})")

    # -- delivery ---------------------------------------------------------------------------------
    def deliver(self) -> int:
        sent = 0
        now = self.clock()
        pending = sorted((row for row in self.store.items() if row.get("status") == "pending"),
                         key=lambda row: str(row.get("confirmed_at") or row.get("updated_at")))
        for row in pending:
            due = _parse_time(row.get("next_attempt_at"))
            if due and due > now:
                continue
            confirmed_at = _parse_time(row.get("confirmed_at"))
            if (row.get("kind") == "signal" and confirmed_at and
                    (now - confirmed_at).total_seconds() > MAX_DELIVERY_DELAY_SECONDS):
                self.store.record(row["key"], status="expired", reason="undelivered_too_long")
                continue
            wait = MIN_SEND_INTERVAL_SECONDS - (time.monotonic() - self._last_send)
            if wait > 0:
                self.sleep(wait)
            self._last_send = time.monotonic()
            attempts = int(row.get("attempts") or 0) + 1
            try:
                result = self.client.send_message(self.chat_id, row["text"])
            except TelegramError as exc:
                if exc.retryable and attempts < MAX_ATTEMPTS:
                    delay = max(exc.retry_after or 0.0, min(MAX_BACKOFF_SECONDS, 2.0 ** attempts))
                    self.store.record(row["key"], attempts=attempts, error=str(exc),
                                      next_attempt_at=(self.clock() + timedelta(seconds=delay)).isoformat())
                    LOGGER.warning("Telegram delivery of %s failed (%s); retry in %.0fs", row["key"], exc, delay)
                    if exc.status == 429:
                        break           # rate limited: nothing else may be sent before retry_after
                else:
                    self.store.record(row["key"], status="failed", attempts=attempts, error=str(exc))
                    LOGGER.error("Telegram delivery of %s failed permanently: %s", row["key"], exc)
                continue
            self.store.record(row["key"], status="sent", attempts=attempts, error=None,
                              sent_at=self.clock().isoformat(), message_id=(result or {}).get("message_id"))
            sent += 1
        return sent

    def tick(self) -> int:
        self.discover_signals()
        self.discover_outcomes()
        return self.deliver()


# ----- engine integration -------------------------------------------------------------------------

_STATUS: dict[str, Any] = {"running": False, "last_tick_at": None, "last_error": None}


def status() -> dict[str, Any]:
    """For /api/health: never the token or chat id."""
    return {"enabled": alerts_enabled(), "configured": bool(os.getenv(TOKEN_ENV) and os.getenv(CHAT_ENV)),
            **_STATUS}


def run_notifier(stop: threading.Event, poll_seconds: float = POLL_SECONDS) -> None:
    token, chat_id = os.getenv(TOKEN_ENV, ""), os.getenv(CHAT_ENV, "").strip()
    try:
        client = TelegramClient(token)
    except ValueError as exc:
        LOGGER.error("Telegram alerts not started: %s", exc)
        _STATUS["last_error"] = str(exc)
        return
    if not chat_id:
        LOGGER.error("Telegram alerts not started: %s is not set", CHAT_ENV)
        _STATUS["last_error"] = f"{CHAT_ENV} is not set"
        client.close()
        return
    notifier = TelegramNotifier(client, chat_id, NotificationStore())
    _STATUS["running"] = True
    LOGGER.info("Telegram alerts running")
    try:
        while not stop.is_set():
            try:
                notifier.tick()
                _STATUS.update(last_tick_at=datetime.now(timezone.utc).isoformat(), last_error=None)
            except Exception as exc:
                _STATUS["last_error"] = _redact(type(exc).__name__ + ": " + str(exc), token)
                LOGGER.error("Telegram notifier tick failed: %s", _STATUS["last_error"])
            stop.wait(poll_seconds)
    finally:
        _STATUS["running"] = False
        client.close()


def start_notifier(stop: threading.Event) -> threading.Thread | None:
    """Start the notifier thread when TRADEDEN_TELEGRAM_ALERTS_ENABLED=1, else None."""
    if not alerts_enabled():
        LOGGER.info("Telegram alerts disabled (%s is not 1)", ENABLED_ENV)
        return None
    thread = threading.Thread(target=run_notifier, args=(stop,), name="tradeden-telegram-notifier", daemon=True)
    thread.start()
    return thread
