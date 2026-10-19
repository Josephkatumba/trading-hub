"""T-032 Phases 5-7: daily/weekly report content, schedule, catch-up and duplicate prevention."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import reports

KLA = reports.KAMPALA
LIVE = {"trendline_v5", "support_resistance", "trend_momentum", "smc"}


def outcome(setup, status, hit, confirmed, strategy="trendline_v5", symbol="EURUSD", r=None, direction="LONG"):
    return {"setup_id": setup, "status": status, "hit_at": hit.isoformat() if hit else None,
            "confirmed_at": confirmed.isoformat(), "recorded_at": (hit or confirmed).isoformat(), "strategy_id": strategy,
            "symbol": symbol, "direction": direction, "shadow": False, "hours_to_hit": 0.5,
            "r_multiple": r if r is not None else (2.0 if status == "TARGET_HIT" else -1.0 if status == "STOP_HIT" else None)}


def kla(*args):
    return datetime(*args, tzinfo=KLA)


class FakeClient:
    def __init__(self, fail=None):
        self.messages, self.documents, self.fail = [], [], list(fail or [])

    def send_message(self, chat_id, text):
        if self.fail:
            raise self.fail.pop(0)
        self.messages.append(text)
        return {"message_id": len(self.messages)}

    def send_document(self, chat_id, path, caption=""):
        self.documents.append((Path(path).name, Path(path).stat().st_size, caption))
        return {"message_id": 99}


class ScheduleTests(unittest.TestCase):
    def test_weekday_23_and_sunday_19_kampala(self):
        after, now = kla(2026, 10, 16, 12, 0), kla(2026, 10, 19, 23, 30)      # Fri noon -> Mon 23:30
        self.assertEqual(reports.due_slots("daily", after, now), [kla(2026, 10, 16, 23), kla(2026, 10, 19, 23)])
        self.assertEqual(reports.due_slots("weekly", after, now), [kla(2026, 10, 18, 19)])
        self.assertEqual(kla(2026, 10, 19, 23).utcoffset(), timedelta(hours=3))

    def test_windows_cover_every_hour_once(self):
        monday = reports.window("daily", kla(2026, 10, 19, 23))
        self.assertEqual(monday, (kla(2026, 10, 16, 23), kla(2026, 10, 19, 23)))      # includes the weekend
        tuesday = reports.window("daily", kla(2026, 10, 20, 23))
        self.assertEqual(tuesday[0], monday[1])
        self.assertEqual(reports.window("weekly", kla(2026, 10, 18, 19)), (kla(2026, 10, 11, 19), kla(2026, 10, 18, 19)))


class ContentTests(unittest.TestCase):
    def setUp(self):
        slot = kla(2026, 10, 20, 23)
        today, yesterday = kla(2026, 10, 20, 10), kla(2026, 10, 18, 10)
        self.outcomes = [
            outcome("a", "TARGET_HIT", today + timedelta(hours=2), today),                 # confirmed + realised today
            outcome("b", "STOP_HIT", today + timedelta(hours=1), yesterday, symbol="XAUUSD"),  # earlier signal, realised today
            outcome("c", "STOP_HIT", today + timedelta(hours=3), yesterday, strategy="smc", symbol="XAUUSD"),
            outcome("d", "PENDING", None, today, strategy="support_resistance"),
            outcome("e", "AMBIGUOUS", today + timedelta(hours=4), yesterday),
            outcome("f", "TARGET_HIT", today, today, strategy="trendline-first-v5-shadow"),   # not live: excluded
            outcome("g", "STOP_HIT", yesterday + timedelta(hours=1), yesterday),           # realised before the window
        ]
        self.confirmations = [{"setup_id": "a", "confirmed_at": today.isoformat(), "strategy_id": "trendline_v5",
                               "symbol": "EURUSD", "direction": "LONG", "score": 81},
                              {"setup_id": "d", "confirmed_at": today.isoformat(), "strategy_id": "support_resistance",
                               "symbol": "GBPUSD", "direction": "SHORT", "score": 90},
                              {"setup_id": "s", "confirmed_at": today.isoformat(), "strategy_id": "smc", "shadow": True}]
        beats = [kla(2026, 10, 19, 23) + timedelta(minutes=m) for m in range(0, 24 * 60, 1)]
        self.report = reports.compute("daily", slot, self.outcomes, self.confirmations, beats, LIVE)

    def test_counts_separate_confirmed_today_from_realised_today(self):
        r = self.report
        self.assertEqual(r["new_confirmed"], 2)
        self.assertEqual((r["take_profits"], r["stop_losses"], r["ambiguous"], r["active"]), (1, 2, 1, 1))
        self.assertEqual(r["win_rate"], round(1 / 3, 3))
        self.assertEqual(r["net_r"], 0.0)
        self.assertEqual(r["by_instrument"]["XAUUSD"], {"tp": 0, "sl": 2, "other": 0, "net_r": -2.0, "win_rate": 0.0})
        self.assertEqual(r["best_strategy"], "Trendline")
        self.assertEqual(r["worst_strategy"], "Smart Money Concepts")
        self.assertEqual(r["uptime"]["coverage"], 1.0)

    def test_text_is_labelled_theoretical(self):
        text = reports.render_text(self.report)
        for expected in ("📊 TRADEDEN DAILY PERFORMANCE", "CONFIRMED IN THIS WINDOW", "OUTCOMES REALISED IN THIS WINDOW",
                         "Take profits: 1   Stop losses: 2", "Win rate (resolved): 33%", "Net theoretical R: +0.00R",
                         "Signals still active: 1", "Not trading profit", "cannot scan markets", "EURUSD LONG" if False else "EURUSD BUY"):
            self.assertIn(expected, text)
        self.assertNotIn("profit of", text.lower())

    def test_downtime_is_reported(self):
        # The uptime record existed before the window (a beat the day before), so the gap is real downtime.
        beats = [kla(2026, 10, 18, 9)] + [kla(2026, 10, 20, 12) + timedelta(minutes=m) for m in range(0, 11 * 60)]
        report = reports.compute("daily", kla(2026, 10, 20, 23), self.outcomes, self.confirmations, beats, LIVE)
        self.assertAlmostEqual(report["uptime"]["offline_hours"], 13.0, delta=0.1)
        self.assertTrue(any("offline" in note for note in report["observations"]))

    def test_time_before_the_first_heartbeat_is_not_called_downtime(self):
        report = reports.compute("daily", kla(2026, 10, 20, 23), self.outcomes, self.confirmations, [], LIVE)
        self.assertIsNone(report["uptime"]["coverage"])
        self.assertFalse(any("offline for" in note for note in report["observations"]))
        self.assertIn("not measured", reports.render_text(report))
        beats = [kla(2026, 10, 20, 12) + timedelta(minutes=m) for m in range(0, 11 * 60)]   # record starts mid-window
        report = reports.compute("daily", kla(2026, 10, 20, 23), self.outcomes, self.confirmations, beats, LIVE)
        self.assertEqual(report["uptime"]["coverage"], 1.0)
        self.assertIn("since Tue 20 Oct 12:00", reports.render_text(report))

    def test_weekly_report_and_pdf(self):
        slot = kla(2026, 10, 25, 19)
        report = reports.compute("weekly", slot, self.outcomes, self.confirmations, [], LIVE)
        self.assertIn("by_session", report)
        self.assertEqual(report["max_drawdown_r"], 1.0)      # -1, +2, -1 in hit order
        self.assertEqual(len(report["previous_weeks"]), 4)
        self.assertTrue(report["recommendations"])
        with tempfile.TemporaryDirectory() as temp:
            path = reports.render_pdf(report, self.outcomes, Path(temp) / "w.pdf")
            self.assertTrue(path.read_bytes().startswith(b"%PDF"))


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.dir = Path(self._temp.name)
        self.now = {"t": kla(2026, 10, 16, 12, 0)}

    def tearDown(self):
        self._temp.cleanup()

    def scheduler(self, client):
        return reports.ReportScheduler(client, "1", reports.ReportLedger(self.dir / "reports.jsonl"),
                                       outcomes=lambda: [], confirmations=lambda: [], beats=lambda: [],
                                       live=lambda: LIVE, clock=lambda: self.now["t"], folder=self.dir)

    def test_no_backfill_before_activation_then_on_time_and_no_duplicates(self):
        client = FakeClient()
        s = self.scheduler(client)
        self.assertEqual(s.tick(), 0)                          # activation (Fri 12:00): nothing earlier is sent
        self.now["t"] = kla(2026, 10, 16, 23, 0, 30)
        self.assertEqual(s.tick(), 1)
        self.assertEqual(s.tick(), 0)
        self.assertEqual(self.scheduler(client).tick(), 0)     # restart: still not duplicated
        self.assertIn("DAILY", client.messages[0])
        self.assertNotIn("Late", client.messages[0])

    def test_missed_reports_are_generated_after_restart(self):
        client = FakeClient()
        self.scheduler(client).tick()
        self.now["t"] = kla(2026, 10, 19, 9, 0)                # engine was off Fri 23:00 and Sun 19:00
        self.assertEqual(self.scheduler(client).tick(), 2)
        self.assertEqual(len(client.documents), 1)
        self.assertTrue(client.documents[0][0].endswith(".pdf"))
        self.assertTrue(all("Late" in m for m in client.messages if "PERFORMANCE" in m))
        for kind, day in (("daily", "2026-10-16"), ("weekly", "2026-10-18")):
            for suffix in (".json", ".txt"):
                self.assertTrue((self.dir / kind / (day + suffix)).exists())

    def test_retry_then_send(self):
        from telegram_notifier import TelegramError
        client = FakeClient(fail=[TelegramError("down", 502, True)])
        self.scheduler(client).tick()
        self.now["t"] = kla(2026, 10, 16, 23, 1)
        self.assertEqual(self.scheduler(client).tick(), 0)
        self.now["t"] += timedelta(minutes=3)
        self.assertEqual(self.scheduler(client).tick(), 1)
        rows = [json.loads(line) for line in (self.dir / "reports.jsonl").read_text().splitlines()]
        self.assertEqual([r.get("status") for r in rows if r["key"].startswith("daily")], ["pending", "sent"])


if __name__ == "__main__":
    unittest.main()
