"""Telegram categories B (research observations) and C (Gold/BTC briefings) + Intelligence Center.

All market data here is a SYNTHETIC FIXTURE for testing only (temporary stores, fake Telegram);
the live registry and real bot are never touched.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quant_live.store import Store
from quant_live.runtime import register_codex
from quant_live import research_observations as ro
from quant_live.intel_center import center
from market_intel import briefings as br

WED_0510 = datetime(2026, 10, 21, 5, 10, tzinfo=timezone.utc).timestamp()   # 08:10 EAT, 10 min after the morning slot


class Fake:
    def __init__(self):
        self.sent = []

    def send_message(self, chat, text, parse_mode=None):
        self.sent.append(text)
        return {'message_id': len(self.sent)}


def approval():
    return {'approved_by': 'CEO Joseph Katumba', 'directive': 'test', 'production': False}


def synthetic_signal(now, key='compression_escape', lab='codex', **kw):
    return {'signal_id': 'ql_synthetic_' + str(int(now)), 'lab': lab, 'lab_name': 'Codex Quant Lab', 'model_key': key, 'model_name': 'Compression Escape',
            'model_version': '0.1.0', 'symbol': 'XAUUSD', 'timeframe': 'M15', 'direction': 'LONG', 'signal_bar_closed_at': now, 'entry_at': now,
            'input_sha256': 'synthetic', 'entry': 4000.0, 'stop_loss': 3990.0, 'take_profit': 4030.0, 'rationale': 'SYNTHETIC FIXTURE condition',
            'planned_rr': 3.0, 'risk': 10.0, 'deadline': now + 3600,
            'detection': 'REAL_TIME', 'regime_at_entry': 'TRENDING', **kw}


def synthetic_candles(store, symbol, now):
    """SYNTHETIC FIXTURE: closed candles up to `now` on every timeframe the intelligence engine reads."""
    frames = {}
    for tf, sec, n in (('M15', 900, 400), ('H1', 3600, 600), ('H4', 14400, 199), ('D1', 86400, 199)):
        end = now - now % sec
        frames[tf] = [{'utc': end - (n - i) * sec, 'open': 100 + i * 0.01, 'high': 100.5 + i * 0.01, 'low': 99.5 + i * 0.01, 'close': 100.1 + i * 0.01, 'spread': 0.01}
                      for i in range(n)]
    store.add_candles({'symbol': symbol, 'frames': frames, 'asof': now})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        register_codex(self.store)


class CategoryApprovalTests(Base):
    def test_rules(self):
        for bad in ({**approval(), 'approved_by': ''}, {**approval(), 'production': True}):
            with self.assertRaises(ValueError):
                self.store.approve_category('research_observations', bad)
        with self.assertRaises(ValueError):
            self.store.approve_category('trade_signals', approval())
        self.store.approve_category('intel_briefings', approval())
        self.assertTrue(self.store.category_approval('intel_briefings'))
        self.assertIsNone(self.store.category_approval('research_observations'))  # independent
        self.store.revoke_category('intel_briefings', 'test')
        self.assertIsNone(self.store.category_approval('intel_briefings'))


class ObservationTests(Base):
    def record(self, now, **kw):
        s = synthetic_signal(now, **kw)
        self.store.record(s, True)
        return s

    def test_preview_label_and_no_trade_levels(self):
        now = WED_0510
        self.record(now)
        ids = ro.collect(self.store, now)
        row = self.store.notifications('research_observations')[0]
        self.assertEqual((ids, row['state']), (['obs:ql_synthetic_' + str(int(now))], 'PREVIEW'))
        msg = row['message']
        self.assertIn('RESEARCH OBSERVATION: NOT A QUALIFIED TRADING SIGNAL', msg)
        self.assertIn('Directional hypothesis: price higher', msg)
        self.assertIn('Historical evidence: Category D', msg)  # compression_escape is rejected in the audit
        for forbidden in ('4000', '3990', '4030', '🎯', '🛑', '💰'):
            self.assertNotIn(forbidden, msg)
        self.assertEqual(ro.collect(self.store, now), [])  # same event never recorded twice

    def test_approved_models_and_stale_events_not_observed(self):
        now = WED_0510
        self.store.approve_delivery({'approved_by': 'CEO', 'directive': 't', 'production': False,
                                     'scope': [{'lab': 'codex', 'key': 'compression_escape', 'version': '0.1.0', 'tier': 'PAPER_CANDIDATE'}]})
        self.record(now)
        self.assertEqual(ro.collect(self.store, now), [])  # approved signal model: category A, not B
        self.store.revoke_delivery('t')
        self.record(now - 3600, key='compression_escape')
        ro.collect(self.store, now)
        states = {n['id']: n['state'] for n in self.store.notifications('research_observations')}
        self.assertEqual(states['obs:ql_synthetic_' + str(int(now - 3600))], 'SKIPPED_STALE')

    def test_category_scope_limits_which_models_are_queued(self):
        now = WED_0510
        self.record(now)
        self.store.approve_category('research_observations', {**approval(), 'scope': [{'lab': 'codex', 'key': 'trend_reclaim_r4'}]})
        with mock.patch.dict(os.environ, {ro.FLAG: '1'}):
            ro.collect(self.store, now)
        self.assertEqual(self.store.notifications('research_observations')[0]['state'], 'PREVIEW')  # compression_escape not in scope

    def test_recovery_survives_incomplete_signal_record(self):
        self.store.record({**synthetic_signal(WED_0510), 'planned_rr': None}, True)
        self.assertTrue(self.store.recover())
        self.assertEqual(self.store.outbox(), [])

    def test_delivery_requires_approval_and_flag_and_sends_once_across_restart(self):
        now = WED_0510
        self.record(now)
        self.store.approve_category('research_observations', approval())
        with mock.patch.dict(os.environ, {ro.FLAG: '1'}):
            ro.collect(self.store, now)
            fake = Fake()
            with mock.patch('quant_live.research_observations.throttle', lambda s=None: None):
                ro.deliver(self.store, fake, 'chat', now + 5)
                ro.deliver(self.store, fake, 'chat', now + 10)
                restarted = Store(self.tmp.name)
                restarted.recover()
                ro.deliver(restarted, fake, 'chat', now + 15)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(self.store.notifications('research_observations')[0]['state'], 'SENT')


class BriefingTests(Base):
    def test_slots_are_eat(self):
        at, day = br.slot_time('morning', WED_0510)
        self.assertEqual(datetime.fromtimestamp(at, timezone.utc).hour, 5)   # 08:00 EAT = 05:00 UTC all year
        self.assertEqual(datetime.fromtimestamp(br.slot_time('new_york', WED_0510)[0], timezone.utc).hour, 12)

    def test_stale_data_is_skipped_not_sent_and_deduplicated(self):
        self.assertEqual(br.run_due(self.store, {}, WED_0510), ['brief:morning:2026-10-21'])
        self.assertEqual(self.store.notifications('intel_briefings')[0]['state'], 'SKIPPED_STALE_DATA')
        self.assertEqual(br.run_due(self.store, {}, WED_0510 + 60), [])

    def test_late_slot_logged_never_sent_late(self):
        later = WED_0510 + 2 * 3600
        br.run_due(self.store, {}, later)
        self.assertEqual(self.store.notifications('intel_briefings')[0]['state'], 'SKIPPED_LATE')

    def test_weekend_new_york_skipped(self):
        sat_1210 = datetime(2026, 10, 24, 12, 10, tzinfo=timezone.utc).timestamp()
        self.assertEqual(br.compose('new_york', self.store, {}, sat_1210)[0], 'SKIPPED_MARKET_CLOSED')

    def test_fresh_data_preview_then_approved_send_once(self):
        now = WED_0510
        for sym in ('XAUUSD', 'BTCUSD', 'NAS100'):
            synthetic_candles(self.store, sym, now)
        br.run_due(self.store, {}, now)
        row = self.store.notifications('intel_briefings')[0]
        self.assertEqual(row['state'], 'PREVIEW')
        for label in ('TRADEDEN MORNING BRIEFING', 'market analysis only, not trade signals', 'No entry, stop-loss or take-profit is implied', 'funding/open interest: unavailable'):
            self.assertIn(label, row['message'])
        other = Store(tempfile.mkdtemp(dir=self.tmp.name))
        register_codex(other)
        for sym in ('XAUUSD', 'BTCUSD', 'NAS100'):
            synthetic_candles(other, sym, now)
        other.approve_category('intel_briefings', approval())
        fake = Fake()
        with mock.patch.dict(os.environ, {br.FLAG: '1'}), mock.patch('quant_live.research_observations.transport_from_env', lambda: (fake, 'chat')), \
                mock.patch('quant_live.research_observations.throttle', lambda s=None: None):
            br.run_due(other, {}, now)
            br.run_due(other, {}, now + 60)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(other.notifications('intel_briefings')[0]['state'], 'SENT')


class CenterTests(Base):
    def test_center_reports_independent_categories(self):
        runtime = {'enabled': True, 'running': True, 'last_processed': WED_0510, 'latest_inputs': {}}
        c = center(self.store, runtime, WED_0510, intel_fn=lambda *a: (_ for _ in ()).throw(RuntimeError('no data')))
        self.assertEqual(set(c['categories']), {'qualified_signals', 'research_observations', 'intel_briefings'})
        self.assertEqual(c['categories']['research_observations']['mode'], 'PREVIEW')
        self.assertEqual(c['intelligence']['XAUUSD']['status'], 'UNAVAILABLE')
        self.assertEqual(c['broker_execution'], 'DISABLED')


if __name__ == '__main__':
    unittest.main()
