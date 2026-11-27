"""Milestone 5: unified leaderboard and the Quant Labs section of the daily/weekly reports (temporary stores only)."""
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quant_live.fixtures import ASOF, snapshot
from quant_live.model_host import execute
from quant_live.runtime import register_codex, qualify
from quant_live.store import Store
from quant_live.telegram import message
from quant_live.leaderboard import leaderboard
from quant_live import research_report
import reports


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        register_codex(self.store)

    def add_signal(self, outcome=None):
        model = self.store.models()[0]
        data = snapshot()
        s, reason = qualify(data, model, execute(model['source'], data)[0], ASOF)
        self.assertIsNone(reason)
        self.store.record(s, True)
        self.store.queue_message(s['signal_id'], message(s), ASOF)
        if outcome:
            self.store.outcome(s['signal_id'], outcome, ASOF + 3600)
        return s

    def test_leaderboard_keeps_historical_and_forward_separate(self):
        self.add_signal({'status': 'SL', 'r': -1.02, 'simulated_net_r': -1.02, 'actual_realized_r': None, 'exit_at': ASOF + 3600})
        row = next(r for r in leaderboard(self.store)['rows'] if r['key'] == 'compression_escape')
        self.assertEqual((row['researcher'], row['category']), ('Codex', 'D'))
        self.assertEqual(row['forward']['resolved'], 1)
        self.assertTrue(row['forward']['insufficient_sample'])
        self.assertAlmostEqual(row['forward']['net_paper_r'], -1.02)
        self.assertIsNotNone(row['historical'])  # audit evidence for compression_escape exists
        self.assertGreater(row['historical']['test']['n'], 100)

    def test_report_section_reports_zero_without_fabrication(self):
        s = research_report.summary(self.store, ASOF - 86400, ASOF - 3600)  # window before any activity
        self.assertEqual((s['confirmed'], s['resolved'], s['net_r'], s['evaluations']), (0, 0, 0, 0))
        text = '\n'.join(research_report.lines(s))
        self.assertIn('Confirmed paper signals: 0', text)
        self.assertIn('separate from production', text)

    def test_report_section_counts_window_outcomes(self):
        self.add_signal({'status': 'TP', 'r': 3.1, 'simulated_net_r': 3.1, 'actual_realized_r': None, 'exit_at': ASOF + 3600})
        s = research_report.summary(self.store, ASOF - 60, ASOF + 7200)
        self.assertEqual((s['confirmed'], s['resolved'], s['tp'], s['sl']), (1, 1, 1, 0))
        self.assertAlmostEqual(s['net_r'], 3.1)
        self.assertEqual(s['best'][0], 'codex:Compression Escape v0.1.0')

    def test_fetch_plan_requests_one_extra_candle_for_the_forming_bar(self):
        from quant_live import service
        with mock.patch.object(service, 'store', lambda: self.store), mock.patch.dict(os.environ, {service.ENABLED_ENV: '1'}):
            plan = service.requirements()
        self.assertEqual(plan['M15'], 301)  # compression_escape declares M15: 300 closed candles
        self.assertEqual(plan['M1'], 121)

    def test_daily_and_weekly_reports_include_separated_section(self):
        start, end = datetime(2026, 10, 18, 20, tzinfo=timezone.utc), datetime(2026, 10, 19, 20, tzinfo=timezone.utc)
        empty = dict(confirmations=lambda: [], outcomes=lambda: [], bank_signals=lambda: [], bank_opportunities=lambda: [],
                     first_seen=lambda: {}, lifecycle=lambda: [], beats=lambda: [], live_alerts=lambda: [], bank_alerts=lambda: [],
                     research=lambda a, b: None)
        sources = reports.Sources(**empty, quant_labs=lambda a, b: research_report.summary(self.store, a.timestamp(), b.timestamp()))
        for kind in ('daily', 'weekly'):
            report, text = reports.build(kind, start, end, sources)
            self.assertIn('QUANT LABS (experimental research · separate from production)', text)
            self.assertIn('Confirmed paper signals: 0', text)
        unavailable = reports.Sources(**empty, quant_labs=lambda a, b: None)
        self.assertIn('Quant Labs store unavailable', reports.build('daily', start, end, unavailable)[1])


if __name__ == '__main__':
    unittest.main()
