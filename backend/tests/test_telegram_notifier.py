"""T-031 Telegram alerts: client, signal selection, duplicates, retries, outcomes, isolation."""
from __future__ import annotations

import inspect
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

import telegram_notifier as tg

BACKEND = Path(__file__).resolve().parents[1]
TOKEN = "123456789:AAHfakeTokenForTestsOnly_abcdefghijk"
NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)


class FakeTelegram:
    """httpx transport standing in for api.telegram.org."""

    def __init__(self, responses=None):
        self.sent: list[dict] = []
        self.urls: list[str] = []
        self.responses = list(responses or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            if response is not None:
                return response
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        if method == "sendMessage":
            self.sent.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {
                "message_id": len(self.sent), "chat": {"id": int(payload["chat_id"])}, "text": payload["text"]}})
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 1, "message": {"chat": {"id": 555000111, "type": "private", "first_name": "Owner"}}},
                {"update_id": 2, "message": {"chat": {"id": -100, "type": "group"}}}]})
        return httpx.Response(200, json={"ok": True, "result": {"username": "tradeden_bot"}})

    def client(self) -> tg.TelegramClient:
        return tg.TelegramClient(TOKEN, transport=httpx.MockTransport(self.handler))


def snapshot(observation_id, direction="LONG", qualified=True, valid=True, entry=2650.0, stop=2645.0, target=2662.5):
    return {"observation_id": observation_id, "observed_at": NOW.isoformat(), "direction": direction,
            "timeframe": "M15", "strategy_version": "trendline-first-v5.1", "reference_price": entry,
            "proposed_entry": entry, "proposed_stop_loss": stop, "proposed_take_profit": target,
            "invalidation_price": stop, "setup_type": "BREAK",
            "features": {"rr": 2.4321, "trendline": "Trendline resistance break retest rejected" if direction == "LONG"
                         else "Trendline support break retest rejected",
                         "structure": "Higher highs + higher lows", "price_action": "Bullish price action", "momentum": "BEARISH"},
            "rule_evidence": {"strategy_valid": valid, "qualification": {"qualified": qualified, "executable_rr": 2.4321}}}


class FakeSource:
    def __init__(self):
        self.snapshots: dict[str, dict] = {}
        self.lifecycle: dict[str, str] = {}
        self.modes = {"trendline_v5": "LIVE", "smc": "LIVE", "trend_momentum": "LIVE", "trendline_v5_shadow": "SHADOW"}
        self.outcomes: dict[str, tuple] = {}

    def snapshot(self, observation_id):
        return self.snapshots.get(observation_id)

    def lifecycle_state(self, setup_id):
        return self.lifecycle.get(setup_id, "CONFIRMED")

    def strategy_mode(self, strategy_id):
        return self.modes.get(strategy_id, "UNREGISTERED")

    def verified_outcome(self, confirmation, snapshot):
        return self.outcomes.get(confirmation["setup_id"], ("pending", None, None))


class Harness:
    def __init__(self, directory: Path, transport: FakeTelegram | None = None, source: FakeSource | None = None):
        self.dir = directory
        self.confirmations = directory / "setup_confirmations.jsonl"
        self.confirmations.touch()
        self.telegram = transport or FakeTelegram()
        self.source = source or FakeSource()
        self.now = NOW
        self.sleeps: list[float] = []
        self.notifier = self.restart()

    def restart(self) -> tg.TelegramNotifier:
        self.notifier = tg.TelegramNotifier(self.telegram.client(), "555000111",
                                            tg.NotificationStore(self.dir / "telegram_notifications.jsonl"),
                                            self.confirmations, self.source, clock=lambda: self.now,
                                            sleep=self.sleeps.append)
        return self.notifier

    def confirm(self, setup_id, strategy_id="trendline_v5", age_seconds=5, symbol="XAUUSD", direction="LONG", **extra):
        observation_id = "obs_" + setup_id
        self.source.snapshots.setdefault(observation_id, snapshot(observation_id, direction))
        row = {"record_type": "setup_confirmation", "confirmation_event_id": "cnf_" + setup_id, "setup_id": setup_id,
               "confirmed_at": (self.now - timedelta(seconds=age_seconds)).isoformat(), "observation_id": observation_id,
               "strategy_id": strategy_id, "strategy_version": "trendline-first-v5.1", "symbol": symbol,
               "direction": direction, **extra}
        with self.confirmations.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return row

    def activated(self):
        """First activation over an empty history (baseline)."""
        self.notifier.tick()
        return self

    def status(self, key):
        return (self.notifier.store.get(key) or {}).get("status")


class ClientTests(unittest.TestCase):
    def test_send_message_posts_text_to_chat(self):
        fake = FakeTelegram()
        result = fake.client().send_message("555000111", tg.TEST_MESSAGE)
        self.assertEqual(result["message_id"], 1)
        self.assertEqual(fake.sent, [{"chat_id": "555000111", "text": tg.TEST_MESSAGE, "disable_web_page_preview": True}])
        self.assertTrue(fake.urls[0].endswith("/sendMessage"))

    def test_error_classification_and_retry_after(self):
        cases = [(httpx.Response(429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}}), True, 7.0),
                 (httpx.Response(502, text="bad gateway"), True, None),
                 (httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"}), False, None),
                 (httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}), False, None),
                 (httpx.ConnectError("boom"), True, None)]
        for response, retryable, retry_after in cases:
            with self.subTest(response=response):
                with self.assertRaises(tg.TelegramError) as caught:
                    FakeTelegram([response]).client().send_message("1", "x")
                self.assertEqual(caught.exception.retryable, retryable)
                self.assertEqual(caught.exception.retry_after, retry_after)

    def test_token_never_leaks(self):
        leaky = httpx.Response(400, json={"ok": False, "description": f"Bad url /bot{TOKEN}/sendMessage"})
        for response in (leaky, httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{TOKEN}/x")):
            with self.assertRaises(tg.TelegramError) as caught:
                FakeTelegram([response]).client().send_message("1", "x")
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(caught.exception.__suppress_context__ or caught.exception.__context__ is None)
        self.assertNotIn(TOKEN, repr(FakeTelegram().client()))
        # httpx would log the request URL (with the token) at INFO.
        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)
        with self.assertRaises(ValueError) as caught:
            tg.TelegramClient("not-a-token")
        self.assertNotIn("not-a-token", str(caught.exception))

    def test_private_chat_discovery(self):
        chats = tg.private_chats(FakeTelegram().client().get_updates())
        self.assertEqual(list(chats), ["555000111"])


class SignalTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self._temp.name)).activated()

    def tearDown(self):
        self._temp.cleanup()

    def test_confirmed_signal_is_sent_with_every_field(self):
        self.h.confirm("stp_a", symbol="XAUUSD", direction="LONG")
        self.assertEqual(self.h.notifier.tick(), 1)
        sent = self.h.telegram.sent[0]
        text = sent["text"]
        lines = text.splitlines()
        self.assertEqual(lines[0], "📊 <b>XAUUSD</b> · 🟢 <b>BUY</b>")          # instrument first, then direction
        self.assertEqual(lines[1], "Trendline · Break &amp; Retest · M15")
        for expected in ("➡️ Entry: <b>2650</b>", "🛑 Stop loss: <b>2645</b>", "🎯 Take profit: <b>2662.5</b>",
                         "⚖️ Risk/reward: 1:2.43", "🕒 Confirmed: 19 Oct 2026, 08:59 EAT", "💡 <b>Trade rationale</b>",
                         "Price broke the falling resistance trendline, retested it and closed above it with a "
                         "rejection candle on M15, with a higher-high, higher-low structure and bullish price action, "
                         "although momentum remains bearish.",
                         tg.DISCLAIMER):
            self.assertIn(expected, text)
        # Internal identifiers are kept, but never shown.
        for hidden in ("stp_a", "Signal ID", "trendline-first-v5.1", "trendline_v5"):
            self.assertNotIn(hidden, text)
        self.assertEqual((sent["chat_id"], sent["parse_mode"]), ("555000111", "HTML"))
        record = self.h.notifier.store.get("signal:stp_a")
        self.assertEqual(record["status"], "sent")
        self.assertEqual((record["setup_id"], record["strategy_version"], record["confirmation_event_id"]),
                         ("stp_a", "trendline-first-v5.1", "cnf_stp_a"))
        self.assertEqual((record["setup_type"], record["setup_name"]), ("BREAK", "Break & Retest"))
        self.assertEqual(record["rationale"]["basis"], "evidence")
        self.assertEqual(record["rationale"]["cautions"], ["momentum remains bearish"])
        self.assertIn(record["rationale"]["text"], sent["text"])

    def test_sell_direction(self):
        self.h.source.snapshots["obs_stp_s"] = snapshot("obs_stp_s", "SHORT", entry=1.1, stop=1.102, target=1.095)
        self.h.confirm("stp_s", direction="SHORT", symbol="EURUSD")
        self.h.notifier.tick()
        self.assertIn("🔴 <b>SELL</b>", self.h.telegram.sent[0]["text"])

    def test_unconfirmed_and_non_live_signals_are_not_sent(self):
        source = self.h.source
        self.h.confirm("stp_shadow", shadow=True)
        self.h.confirm("stp_research", strategy_id="trendline_v5_shadow")
        self.h.confirm("stp_unknown", strategy_id="crt")
        source.snapshots["obs_stp_unq"] = snapshot("obs_stp_unq", qualified=False)
        self.h.confirm("stp_unq")
        source.snapshots["obs_stp_invalid"] = snapshot("obs_stp_invalid", valid=False)
        self.h.confirm("stp_invalid")
        source.snapshots["obs_stp_noplan"] = snapshot("obs_stp_noplan", target=None)
        self.h.confirm("stp_noplan")
        for state in ("INVALIDATED", "EXPIRED", "RESOLVED"):
            source.lifecycle["stp_" + state] = state
            self.h.confirm("stp_" + state)
        self.h.confirm("stp_old", age_seconds=tg.MAX_SIGNAL_AGE_SECONDS + 1)
        self.h.notifier.tick()
        self.assertEqual(self.h.telegram.sent, [])
        reasons = {row["setup_id"]: row["reason"] for row in self.h.notifier.store.items() if row.get("kind") == "signal"}
        self.assertEqual(reasons, {"stp_shadow": "shadow_strategy", "stp_research": "strategy_not_live",
                                   "stp_unknown": "strategy_not_live", "stp_unq": "not_qualified",
                                   "stp_invalid": "not_qualified", "stp_noplan": "incomplete_plan",
                                   "stp_INVALIDATED": "lifecycle_invalidated", "stp_EXPIRED": "lifecycle_expired",
                                   "stp_RESOLVED": "lifecycle_resolved", "stp_old": "stale_not_new"})

    def test_waits_for_snapshot_then_gives_up_when_stale(self):
        row = self.h.confirm("stp_late")
        del self.h.source.snapshots[row["observation_id"]]
        self.h.notifier.tick()
        self.assertIsNone(self.h.status("signal:stp_late"))
        self.h.source.snapshots[row["observation_id"]] = snapshot(row["observation_id"])
        self.h.notifier.tick()
        self.assertEqual(self.h.status("signal:stp_late"), "sent")

    def test_duplicates_prevented_across_repeats_and_restarts(self):
        self.h.confirm("stp_dup")
        self.h.confirm("stp_dup")                     # a repeated line for the same setup
        for _ in range(3):
            self.h.notifier.tick()
        self.h.restart().tick()                        # engine restart: history reloaded from disk
        self.h.restart().tick()
        self.assertEqual(len(self.h.telegram.sent), 1)

    def test_history_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            h = Harness(Path(temp))
            for index in range(5):
                h.confirm(f"stp_hist{index}", age_seconds=1)  # even recent ones predate activation
            h.notifier.tick()
            self.assertEqual(h.telegram.sent, [])
            self.assertEqual({h.status(f"signal:stp_hist{i}") for i in range(5)}, {"baseline"})
            h.restart().tick()
            self.assertEqual(h.telegram.sent, [])
            # Confirmed while the engine/notifier was down, found too late: not a new alert.
            h.confirm("stp_downtime", age_seconds=tg.MAX_SIGNAL_AGE_SECONDS * 3)
            h.confirm("stp_fresh")
            h.restart().tick()
            self.assertEqual(len(h.telegram.sent), 1)
            self.assertEqual([r["setup_id"] for r in h.notifier.store.items() if r.get("status") == "sent"], ["stp_fresh"])

    def test_partial_trailing_line_is_read_once_complete(self):
        row = {"record_type": "setup_confirmation", "setup_id": "stp_part", "observation_id": "obs_stp_part",
               "confirmed_at": NOW.isoformat(), "strategy_id": "trendline_v5", "symbol": "XAUUSD"}
        self.h.source.snapshots["obs_stp_part"] = snapshot("obs_stp_part")
        text = json.dumps(row)
        with self.h.confirmations.open("a") as handle:
            handle.write(text[:20])
        self.h.notifier.tick()
        with self.h.confirmations.open("a") as handle:
            handle.write(text[20:] + "\n")
        self.h.notifier.tick()
        self.assertEqual(len(self.h.telegram.sent), 1)


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.dir = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_temporary_failures_are_retried_with_backoff(self):
        h = Harness(self.dir, FakeTelegram([httpx.Response(500), httpx.ConnectError("down")])).activated()
        h.confirm("stp_r")
        h.notifier.tick()
        record = h.notifier.store.get("signal:stp_r")
        self.assertEqual((record["status"], record["attempts"]), ("pending", 1))
        h.notifier.tick()                              # backoff not elapsed: no request
        self.assertEqual(len(h.telegram.urls), 1)
        h.now += timedelta(seconds=3)
        h.notifier.tick()                              # second failure (network)
        h.now += timedelta(seconds=5)
        h.restart().tick()                             # a pending alert survives a restart
        self.assertEqual(h.status("signal:stp_r"), "sent")
        self.assertEqual(len(h.telegram.sent), 1)

    def test_rate_limit_respects_retry_after_and_pauses_the_queue(self):
        limited = httpx.Response(429, json={"ok": False, "description": "Too Many Requests: retry after 30",
                                            "parameters": {"retry_after": 30}})
        h = Harness(self.dir, FakeTelegram([limited])).activated()
        h.confirm("stp_1")
        h.confirm("stp_2")
        h.notifier.tick()
        self.assertEqual(len(h.telegram.urls), 1)      # the second alert waited too
        h.now += timedelta(seconds=10)
        h.notifier.tick()
        self.assertEqual(h.status("signal:stp_1"), "pending")
        h.now += timedelta(seconds=21)
        h.notifier.tick()
        self.assertEqual(len(h.telegram.sent), 2)
        self.assertTrue(all(0 < pause <= tg.MIN_SEND_INTERVAL_SECONDS for pause in h.sleeps))

    def test_permanent_failure_is_not_retried(self):
        h = Harness(self.dir, FakeTelegram([httpx.Response(400, json={"ok": False, "description": "chat not found"})])).activated()
        h.confirm("stp_p")
        h.notifier.tick()
        h.now += timedelta(minutes=5)
        h.notifier.tick()
        self.assertEqual(h.status("signal:stp_p"), "failed")
        self.assertEqual(len(h.telegram.urls), 1)

    def test_undelivered_signal_expires_instead_of_arriving_late(self):
        h = Harness(self.dir, FakeTelegram([httpx.Response(503)] * 3)).activated()
        h.confirm("stp_e")
        h.notifier.tick()
        h.now += timedelta(seconds=tg.MAX_DELIVERY_DELAY_SECONDS + 1)
        h.notifier.tick()
        self.assertEqual(h.status("signal:stp_e"), "expired")
        self.assertEqual(h.telegram.sent, [])


class FormatCompatibilityTests(unittest.TestCase):
    def test_queued_plain_text_record_is_sent_without_html(self):
        with tempfile.TemporaryDirectory() as temp:
            h = Harness(Path(temp)).activated()
            h.notifier.store.record("signal:stp_old", kind="signal", setup_id="stp_old", status="pending", attempts=0,
                                    confirmed_at=NOW.isoformat(), text="Old <plain> & text")
            h.notifier.deliver()
            self.assertEqual(h.telegram.sent[0]["text"], "Old <plain> & text")
            self.assertNotIn("parse_mode", h.telegram.sent[0])

    def test_html_is_escaped(self):
        confirmation = {"symbol": "A<B&C", "strategy_id": "support_resistance", "confirmed_at": NOW.isoformat()}
        text = tg.signal_message(confirmation, {"direction": "SHORT", "entry": 1, "stop_loss": 2, "take_profit": 0.5, "rr": 1.5})
        self.assertIn("<b>A&lt;B&amp;C</b>", text)
        self.assertIn("Support &amp; Resistance", text)
        self.assertIn("🔴 <b>SELL</b>", text)


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.h = Harness(Path(self._temp.name)).activated()
        self.h.confirm("stp_o")
        self.h.notifier.tick()
        self.assertEqual(self.h.status("signal:stp_o"), "sent")

    def tearDown(self):
        self._temp.cleanup()

    def advance(self, minutes=2):
        self.h.now += timedelta(minutes=minutes)
        self.h.notifier.tick()

    def test_take_profit_follow_up_sent_once(self):
        self.h.source.outcomes["stp_o"] = ("verified_target", "1h", {"time_to_favorable_movement": "0:45:00"})
        for _ in range(3):
            self.advance()
        self.h.restart().tick()
        outcome = [m["text"] for m in self.h.telegram.sent if "PROFIT HIT" in m["text"] or "LOSS HIT" in m["text"]]
        self.assertEqual(len(outcome), 1)
        lines = outcome[0].splitlines()
        self.assertEqual(lines[0], "🎯 <b>XAUUSD</b> · <b>TAKE PROFIT HIT</b>")
        self.assertEqual(lines[1], "Trendline · Break &amp; Retest · BUY · M15")
        for expected in ("➡️ Entry: 2650", "🎯 Take profit: <b>2662.5</b> reached before the stop loss",
                         "📈 Signal result: <b>+2.43R</b>", "🕒 Confirmed: 19 Oct 2026, 08:59 EAT",
                         "⏱️ Reached: 19 Oct 2026, 09:44 EAT (M15 candle)", "Not an executed trade", "1h window",
                         tg.DISCLAIMER):
            self.assertIn(expected, outcome[0])
        self.assertNotIn("stp_o", outcome[0])
        self.assertEqual(self.h.telegram.sent[-1]["parse_mode"], "HTML")

    def test_stop_loss_follow_up(self):
        self.h.source.outcomes["stp_o"] = ("verified_stop", "15m", {"time_to_adverse_movement": "0:15:00"})
        self.advance()
        text = self.h.telegram.sent[-1]["text"]
        self.assertIn("🛑 <b>XAUUSD</b> · <b>STOP LOSS HIT</b>", text)
        self.assertIn("🛑 Stop loss: <b>2645</b> reached before the take profit", text)
        self.assertIn("📉 Signal result: <b>-1.00R</b>", text)

    def test_unverified_or_undecided_outcomes_send_nothing(self):
        for kind in ("pending", "unverified", "verified_other"):
            self.h.source.outcomes["stp_o"] = (kind, None, None)
            self.advance()
        self.assertEqual(len(self.h.telegram.sent), 1)
        self.h.now += timedelta(seconds=tg.OUTCOME_TRACK_SECONDS + 1)
        self.h.notifier.tick()
        self.assertEqual(self.h.status("outcome:stp_o"), "skipped")
        self.h.source.outcomes["stp_o"] = ("verified_target", "24h", {})
        self.advance()                                 # tracking ended: nothing inferred later
        self.assertEqual(len(self.h.telegram.sent), 1)

    def test_signals_never_alerted_get_no_outcome(self):
        self.h.confirm("stp_skip", shadow=True)
        self.h.source.outcomes["stp_skip"] = ("verified_target", "1h", {})
        self.advance()
        self.assertEqual(len(self.h.telegram.sent), 1)


class IsolationTests(unittest.TestCase):
    def test_disabled_by_default(self):
        previous = os.environ.pop(tg.ENABLED_ENV, None)
        try:
            self.assertIsNone(tg.start_notifier(threading.Event()))
            self.assertFalse(tg.status()["enabled"])
        finally:
            if previous is not None:
                os.environ[tg.ENABLED_ENV] = previous

    def test_scanner_never_calls_telegram(self):
        import main
        for function in (main._market_snapshot, main.autonomous_market_worker, main.market_snapshot):
            self.assertNotIn("telegram", inspect.getsource(function))

    def test_hanging_telegram_does_not_block_other_threads(self):
        release = threading.Event()

        def hang(request):
            release.wait(5)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        with tempfile.TemporaryDirectory() as temp:
            h = Harness(Path(temp)).activated()
            h.notifier.client = tg.TelegramClient(TOKEN, transport=httpx.MockTransport(hang))
            h.confirm("stp_h")
            worker = threading.Thread(target=h.notifier.tick, daemon=True)
            worker.start()
            started = time.perf_counter()
            busy = sum(range(200000))                  # stands in for a scan on another thread
            self.assertLess(time.perf_counter() - started, 1.0)
            self.assertTrue(busy)
            self.assertTrue(worker.is_alive())
            release.set()
            worker.join(5)
            self.assertEqual(h.status("signal:stp_h"), "sent")

    def test_tick_cost_with_large_history(self):
        with tempfile.TemporaryDirectory() as temp:
            h = Harness(Path(temp))
            with h.confirmations.open("a") as handle:
                for index in range(2000):
                    handle.write(json.dumps({"record_type": "setup_confirmation", "setup_id": f"stp_{index}",
                                             "confirmed_at": NOW.isoformat(), "observation_id": "o"}) + "\n")
            h.notifier.tick()
            started = time.perf_counter()
            for _ in range(20):
                h.notifier.tick()                       # steady state: only appended bytes are read
            self.assertLess((time.perf_counter() - started) / 20, 0.05)


INTEGRATION = r'''
import json, sys
from datetime import datetime, timedelta, timezone
import httpx
import observations, outcomes, qualification
import telegram_notifier as tg

sent = []
def handler(request):
    payload = json.loads(request.content)
    sent.append(payload["text"])
    return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

now = datetime.now(timezone.utc)
def market(strategy_valid=True, symbol="XAUUSD", qualified=True):
    m = {"symbol": symbol, "state": "CONFIRMING", "direction": "LONG", "setup_family": "REVERSAL", "timeframe": "M15",
         "price": 2650.0, "bid": 2649.9, "ask": 2650.0, "tick_age_seconds": 2.0, "atr": 5.0,
         "entry": 2650.0, "stop_loss": 2645.0, "take_profit": 2662.0 if qualified else 2651.0,
         "trendline_identity": {"orientation": "ASCENDING_SUPPORT", "anchors": [{"time": "a", "price": 2640}, {"time": "b", "price": 2645}]},
         "strategy_valid": strategy_valid, "trendline_gate": True, "confirmation_alignment": True, "score": 80,
         "strategy_id": "trendline_v5", "source_timestamp": now.isoformat(),
         "time_provenance": {"timezone_normalization_status": "VERIFIED", "source_time_basis": "UTC"}}
    return qualification.apply(m)

client = tg.TelegramClient("123456789:AAHfakeTokenForTestsOnly_abcdefghijk", transport=httpx.MockTransport(handler))
clock = {"now": now}
notifier = tg.TelegramNotifier(client, "1", tg.NotificationStore(), observations.CONFIRMATIONS_FILE,
                               clock=lambda: clock["now"], sleep=lambda s: None)
notifier.tick()                                     # activation baseline (empty store)

observations.record_markets([market(symbol="XAUUSD")])       # confirmed + qualified
observations.record_markets([market(strategy_valid=False, symbol="EURUSD")])   # detected only
observations.record_markets([market(symbol="GBPUSD", qualified=False)])        # fails 1.5R at the executable price
clock["now"] = datetime.now(timezone.utc)
notifier.tick()
observations.record_markets([market(symbol="XAUUSD")])       # same setup again: no new alert
notifier.tick()
signals = list(sent)

# Outcome engine: completed M15 candles after the confirmation; the second reaches the target.
confirmations = observations.confirmation_events()
snapshots = observations.snapshots_by_observation_id(str(r["observation_id"]) for r in confirmations)
start = int(now.timestamp()) // 900 * 900
bars = [{"time": start + 900 * i, "open": 2650.0, "high": 2652.0 if i != 2 else 2663.0, "low": 2648.0,
         "close": 2651.0} for i in range(-2, 12)]
later = now + timedelta(hours=2)
for outcome in outcomes.resolve_due_market_outcomes(confirmations, snapshots, {"XAUUSD": bars}, [], ("15m", "1h"), now=later):
    outcomes.append_market_outcome(outcome)
clock["now"] = later
notifier.discover_outcomes(force=True); notifier.deliver()
notifier.discover_outcomes(force=True); notifier.deliver()
print(json.dumps({"signals": signals, "all": sent}))
'''


class EngineIntegrationTests(unittest.TestCase):
    """Real observation, confirmation, qualification and outcome stores (own data directory)."""

    def test_confirmed_signal_and_verified_outcome_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {**os.environ, "TRADING_HUB_DATA_DIR": temp}
            result = subprocess.run([sys.executable, "-c", INTEGRATION], cwd=BACKEND, env=env,
                                    text=True, capture_output=True, encoding="utf-8")
            if result.returncode:
                raise AssertionError(result.stderr)
            payload = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(len(payload["signals"]), 1, payload["signals"])
        self.assertIn("📊 <b>XAUUSD</b>", payload["signals"][0])
        self.assertIn("🟢 <b>BUY</b>", payload["signals"][0])
        self.assertEqual(len(payload["all"]), 2, payload["all"])
        self.assertIn("TAKE PROFIT HIT", payload["all"][1])
        self.assertIn("Not an executed trade", payload["all"][1])
        self.assertIn("Trendline · Bounce · M15", payload["signals"][0])     # recorded REVERSAL family
        self.assertIn("💡 <b>Trade rationale</b>", payload["signals"][0])


if __name__ == "__main__":
    unittest.main()
