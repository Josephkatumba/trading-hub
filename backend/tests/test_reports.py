"""Daily (every day 23:00 EAT) and weekly (Friday 23:00 EAT) Telegram reports: schedule, windows,
Friday ordering, duplicates, delayed catch-up and report contents from recorded data only."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import reports

KLA = reports.KAMPALA


def kla(*args):
    return datetime(*args, tzinfo=KLA)


def iso(value):
    return value.isoformat()


# 2026-10-23 is a Friday; 2026-10-17 the Saturday that opens its week.
FRI = kla(2026, 10, 23, 23, 0)
TODAY = kla(2026, 10, 23, 10, 0)


def fake_sources(**extra):
    confirmations = [
        {"setup_id": "p1", "strategy_id": "trendline_v5", "setup_type": "REVERSAL", "symbol": "EURUSD", "direction": "LONG", "confirmed_at": iso(TODAY)},
        {"setup_id": "p2", "strategy_id": "support_resistance", "symbol": "XAUUSD", "direction": "SHORT", "confirmed_at": iso(TODAY - timedelta(days=2))},
        {"setup_id": "p3", "strategy_id": "trendline_v5", "setup_type": "BREAK", "symbol": "XAUUSD", "direction": "LONG", "confirmed_at": iso(TODAY), "shadow": True},
        {"setup_id": "p4", "strategy_id": "trendline", "symbol": "GBPUSD", "confirmed_at": iso(TODAY)},          # retired: excluded
    ]
    outcomes = [
        {"setup_id": "p1", "status": "TARGET_HIT", "hit_at": iso(TODAY + timedelta(hours=2)), "r_multiple": 2.0, "entry": 1.0, "stop_loss": 0.99, "take_profit": 1.02},
        {"setup_id": "p2", "status": "STOP_HIT", "hit_at": iso(TODAY + timedelta(hours=1)), "r_multiple": -1.0, "entry": 2.0, "stop_loss": 2.01, "take_profit": 1.98},
    ]
    bank = [
        {"signal_id": "b1", "strategy_key": "ema_crossover", "strategy_name": "EMA Crossover", "status": "EXPERIMENTAL", "symbol": "XAUUSD",
         "direction": "LONG", "confirmed_at": iso(TODAY), "rr": 2.0, "outcome_status": "STOP_HIT", "outcome_at": iso(TODAY + timedelta(hours=3)),
         "r_multiple": -1.0, "opportunity_id": "o1"},
        {"signal_id": "b2", "strategy_key": "macd_momentum", "strategy_name": "MACD Momentum", "status": "EXPERIMENTAL", "symbol": "XAUUSD",
         "direction": "LONG", "confirmed_at": iso(TODAY), "rr": 2.0, "outcome_status": "PENDING", "opportunity_id": "o1"},
        {"signal_id": "b3", "strategy_key": "london_breakout", "strategy_name": "London Session Breakout", "status": "EXPERIMENTAL", "symbol": "USDCAD",
         "direction": "SHORT", "confirmed_at": iso(TODAY), "rr": 2.0, "outcome_status": "TIME_EXIT", "outcome_at": iso(TODAY + timedelta(hours=5)), "r_multiple": 0.4},
    ]
    seen = {"p1": {"at": iso(TODAY - timedelta(hours=1)), "strategy_id": "trendline_v5", "shadow": False, "setup_type": "REVERSAL"},
            "d1": {"at": iso(TODAY), "strategy_id": "support_resistance", "shadow": False, "setup_type": "SR_BOUNCE"},
            "d2": {"at": iso(TODAY), "strategy_id": "trendline-first-v5-shadow", "shadow": True, "setup_type": "BREAK"},
            "old": {"at": iso(TODAY - timedelta(days=3)), "strategy_id": "smc", "shadow": False, "setup_type": "X"}}
    lifecycle = [{"setup_id": "d1", "to_state": "INVALIDATED", "occurred_at": iso(TODAY + timedelta(hours=1))},
                 {"setup_id": "p1", "to_state": "EXPIRED", "occurred_at": iso(TODAY + timedelta(hours=4))},
                 {"setup_id": "d2", "to_state": "EXPIRED", "occurred_at": iso(TODAY)}]                 # shadow: excluded
    beats = [FRI - timedelta(days=1) + timedelta(minutes=m) for m in range(0, 24 * 60)]
    base = dict(confirmations=lambda: confirmations, outcomes=lambda: outcomes, bank_signals=lambda: bank,
                bank_opportunities=lambda: [{"opportunity_id": "o1", "strategies": ["EMA Crossover", "MACD Momentum"], "first_confirmed_at": iso(TODAY)}],
                first_seen=lambda: seen, lifecycle=lambda: lifecycle, beats=lambda: beats,
                live_alerts=lambda: [{"key": "signal:p1", "status": "sent", "sent_at": iso(TODAY)}],
                bank_alerts=lambda: [{"key": "bank:o1", "status": "sent", "sent_at": iso(TODAY)}, {"key": "bank:o2", "status": "expired", "updated_at": iso(TODAY)}],
                health=lambda: {"scanner": "CONNECTED", "mt5": "connected", "bank": "running", "outcomes": "running"},
                research=lambda start, end: {"new": [{"name": "Volatility Squeeze V2"}], "promoted": [], "demoted": [], "testing": ["Volatility Squeeze V2"],
                                             "rejected": ["Gap Fade"], "counts": {"registered": 30, "qualified": 0}, "discoveries": ["Gap fades lose after costs"]})
    base.update(extra)
    return reports.Sources(**base)


class ScheduleTests(unittest.TestCase):
    def test_daily_every_day_and_weekly_on_friday_at_23_kampala(self):
        after, now = kla(2026, 10, 22, 12, 0), kla(2026, 10, 25, 23, 30)            # Thu noon -> Sun 23:30
        self.assertEqual(reports.due_slots("daily", after, now), [kla(2026, 10, d, 23) for d in (22, 23, 24, 25)])
        self.assertEqual(reports.due_slots("weekly", after, now), [FRI])
        self.assertEqual(FRI.utcoffset(), timedelta(hours=3))

    def test_windows(self):
        self.assertEqual(reports.window("daily", FRI), (kla(2026, 10, 22, 23), FRI))
        self.assertEqual(reports.window("weekly", FRI), (kla(2026, 10, 17, 0, 0), FRI), "Saturday 00:00 -> Friday 23:00")
        self.assertEqual(reports.latest_daily_window(kla(2026, 10, 23, 15, 0)), (kla(2026, 10, 22, 23), kla(2026, 10, 23, 15)))
        self.assertEqual(reports.latest_daily_window(kla(2026, 10, 23, 23, 30))[0], FRI)


class ContentTests(unittest.TestCase):
    def test_daily_report_from_recorded_data(self):
        report = reports.compute_daily(*reports.window("daily", FRI), fake_sources())
        self.assertEqual(report["detected"], 2, "first observations in the window; shadow and old setups excluded")
        self.assertEqual((report["confirmed"], report["confirmed_production"], report["confirmed_bank"]), (4, 1, 3))
        self.assertEqual((report["take_profits"], report["stop_losses"], report["time_exits"]), (1, 2, 1))
        self.assertEqual(report["win_rate"], round(1 / 3, 3))
        self.assertEqual(report["net_r"], 0.4)
        self.assertEqual((report["active"], report["invalidated"], report["expired"]), (1, 1, 1))
        self.assertEqual(set(report["by_strategy"]), {"Trendline Bounce", "Support & Resistance", "EMA Crossover", "London Session Breakout"})
        self.assertEqual(report["by_instrument"]["XAUUSD"]["sl"], 2)
        self.assertEqual(report["best"][0], "Trendline Bounce")
        self.assertEqual(report["uptime"]["coverage"], 1.0)
        self.assertEqual(report["delivery"]["bank_alerts"], {"sent": 1, "failed": 0, "expired": 1})
        text = reports.render_daily(report)
        for expected in ("📊 TRADEDEN DAILY REPORT", "1. Detected", "2. Confirmed: 4", "3. Reached TP: 1", "4. Reached SL: 2",
                         "5. Active (open): 1", "6. Invalidated: 1   Expired: 1", "7. Win rate (TP ÷ TP+SL): 33%", "8. BY STRATEGY",
                         "9. BY INSTRUMENT", "10. BEST / WORST", "11-12. STRATEGY RESEARCH", "New strategies registered: Volatility Squeeze V2",
                         "13-14. SYSTEM HEALTH AND DELIVERY", "Engine uptime: 100%", "15. OBSERVATIONS",
                         "Paper signals", "Executed trades: none", "small sample"):
            self.assertIn(expected, text)

    def test_weekly_report_sections_and_cutoff(self):
        start, end = reports.window("weekly", FRI)
        report = reports.compute_weekly(start, end, fake_sources())
        self.assertEqual(report["confirmed"], 5)                          # p2 two days earlier is in the week
        self.assertEqual(report["avg_rr"], 2.0)
        self.assertTrue(all(item["small"] for item in report["top"]))
        self.assertEqual(report["correlation"]["multi_strategy_opportunities"], 1)
        self.assertEqual(report["streaks"], {"wins": 1, "losses": 1})        # SL, TP, SL, time exit (+0.4R) in hit order
        text = reports.render_weekly(report)
        for expected in ("📈 TRADEDEN WEEKLY PERFORMANCE REVIEW", "Sat 17 Oct 00:00 → Fri 23 Oct 23:00", "Cutoff 23:00", "A. WEEKLY PERFORMANCE",
                         "By session", "B. STRATEGY LEADERBOARD", "⚠ small sample", "Need further testing", "C. STRATEGY RESEARCH",
                         "Rejected / archived: Gap Fade", "(backtest: simulated)", "D. RISK ANALYSIS", "Max drawdown", "Longest streaks",
                         "Correlation: 1 opportunities", "E. NEXT WEEK'S RESEARCH PRIORITIES"):
            self.assertIn(expected, text)

    def test_nothing_after_the_cutoff(self):
        late = [{"signal_id": "late", "strategy_key": "ema_pullback", "strategy_name": "EMA Pullback", "symbol": "EURUSD", "direction": "LONG",
                 "confirmed_at": iso(FRI + timedelta(minutes=5)), "outcome_status": "TARGET_HIT", "outcome_at": iso(FRI + timedelta(minutes=30)), "r_multiple": 2.0}]
        report = reports.compute_weekly(*reports.window("weekly", FRI), fake_sources(bank_signals=lambda: late))
        # Only the production TP from inside the week counts; the bank TP after 23:00 does not.
        self.assertEqual((report["confirmed_bank"], report["take_profits"], report["net_r"]), (0, 1, 1.0))

    def test_research_unavailable_is_stated_not_invented(self):
        report = reports.compute_daily(*reports.window("daily", FRI), fake_sources(research=lambda s, e: None))
        self.assertIn("Research registry unavailable", reports.render_daily(report))


class FakeClient:
    def __init__(self, fail=None):
        self.messages, self.documents, self.fail = [], [], list(fail or [])

    def send_message(self, chat_id, text, parse_mode=None):
        if self.fail:
            raise self.fail.pop(0)
        self.messages.append(text)
        return {"message_id": len(self.messages)}

    def send_document(self, chat_id, path, caption=""):
        self.documents.append(Path(path).name)
        return {"message_id": 99}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.dir = Path(self._temp.name)
        self.now = {"t": kla(2026, 10, 22, 12, 0)}                 # Thursday noon: activation

    def tearDown(self):
        self._temp.cleanup()

    def scheduler(self, client):
        return reports.ReportScheduler(client, "1", fake_sources(), reports.ReportLedger(self.dir / "reports.jsonl"),
                                       clock=lambda: self.now["t"], folder=self.dir, pdf=False)

    def heads(self, client):
        return [m.splitlines()[0] for m in client.messages if m.startswith(("📊", "📈"))]

    def test_daily_then_weekly_on_friday_without_duplicates(self):
        client = FakeClient()
        self.assertEqual(self.scheduler(client).tick(), 0)            # activation: nothing earlier is sent
        self.now["t"] = kla(2026, 10, 22, 23, 0, 20)
        self.assertEqual(self.scheduler(client).tick(), 1)            # Thursday daily
        self.now["t"] = kla(2026, 10, 23, 23, 0, 20)
        s = self.scheduler(client)
        self.assertEqual(s.tick(), 2)                                 # Friday: daily, then weekly
        self.assertEqual(s.tick(), 0)
        self.assertEqual(self.scheduler(client).tick(), 0)           # restart: still no duplicate
        self.assertEqual(self.heads(client), ["📊 TRADEDEN DAILY REPORT", "📊 TRADEDEN DAILY REPORT", "📈 TRADEDEN WEEKLY PERFORMANCE REVIEW"])
        self.assertFalse(any("DELAYED" in m for m in client.messages))
        ledger = [json.loads(line) for line in (self.dir / "reports.jsonl").read_text(encoding="utf-8").splitlines()]
        sent = [row["key"] for row in ledger if row.get("status") == "sent"]
        self.assertEqual(sent, ["daily:2026-10-22", "daily:2026-10-23", "weekly:2026-10-23"])
        for kind, day in (("daily", "2026-10-23"), ("weekly", "2026-10-23")):
            self.assertTrue((self.dir / kind / (day + ".txt")).exists())

    def test_missed_reports_are_sent_after_restart_labelled_delayed(self):
        client = FakeClient()
        self.scheduler(client).tick()
        self.now["t"] = kla(2026, 10, 24, 9, 0)                       # offline Thu 23:00 and Fri 23:00
        self.assertEqual(self.scheduler(client).tick(), 3)
        self.assertEqual(self.heads(client), ["📊 TRADEDEN DAILY REPORT"] * 2 + ["📈 TRADEDEN WEEKLY PERFORMANCE REVIEW"])
        self.assertTrue(all("⏰ DELAYED" in m for m in client.messages if m.startswith(("📊", "📈"))))

    def test_failed_daily_holds_the_weekly_back_then_both_send_in_order(self):
        from telegram_notifier import TelegramError
        client = FakeClient(fail=[TelegramError("down", 502, True)])
        self.scheduler(client).tick()
        self.now["t"] = kla(2026, 10, 23, 23, 1)
        self.scheduler(client).tick()
        self.assertEqual(self.heads(client), [])          # the first (Thursday) daily failed: nothing later jumps ahead of it
        self.now["t"] += timedelta(minutes=3)
        self.scheduler(client).tick()
        self.assertEqual(self.heads(client), ["📊 TRADEDEN DAILY REPORT", "📊 TRADEDEN DAILY REPORT", "📈 TRADEDEN WEEKLY PERFORMANCE REVIEW"])

    def test_weekly_pdf_is_attached(self):
        client = FakeClient()
        self.scheduler(client).tick()
        self.now["t"] = kla(2026, 10, 23, 23, 2)
        s = reports.ReportScheduler(client, "1", fake_sources(), reports.ReportLedger(self.dir / "reports.jsonl"),
                                    clock=lambda: self.now["t"], folder=self.dir, pdf=True)
        s.tick()
        self.assertEqual(client.documents, ["2026-10-23.pdf"])
        self.assertTrue((self.dir / "weekly" / "2026-10-23.pdf").read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
