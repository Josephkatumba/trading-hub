"""Quant Labs live integration: approved EXPERIMENTAL Telegram delivery, lifecycle, restarts, tracking.

Uses temporary stores and a fake Telegram client only; the live registry and real bot are never touched.
The historical end-to-end test replays the five October 20 strategies on genuine shared MT5 snapshots.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from bisect import bisect_right
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from quant_live.fixtures import ASOF, snapshot
from quant_live.model_host import execute
from quant_live.runtime import Runtime, register_codex, qualify
from quant_live.store import Store
from quant_live.telegram import ExperimentalNotifier, message, DELIVERY_ENV
from quant_live.report import snapshot as report

CODEX = ('codex', 'compression_escape', '0.1.0')
LABS = PROJECT / 'quant_labs/state/labs'
FIVE = [('codex', 'compression_escape', LABS / 'codex/strategies/compression_escape', 'RESEARCH_ONLY'),
        ('claude', 'index_trend_day', LABS / 'claude/strategies/index_trend_day', 'PAPER_CANDIDATE'),
        ('claude', 'crypto_trend_breakout', LABS / 'claude/strategies/crypto_trend_breakout', 'PAPER_CANDIDATE'),
        ('claude', 'hourly_shock_drift', LABS / 'claude/strategies/hourly_shock_drift', 'RESEARCH_ONLY'),
        ('claude', 'index_gap_fade', LABS / 'claude/strategies/index_gap_fade', 'RESEARCH_ONLY')]


class FakeTelegram:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send_message(self, chat_id, text, parse_mode=None):
        if self.error:
            raise self.error
        self.sent.append(text)
        return {'message_id': len(self.sent)}


class HttpError(Exception):
    def __init__(self, status):
        super().__init__(f'HTTP {status}')
        self.status = status


def approval(scope, production=False):
    return {'approved_by': 'CEO Joseph Katumba', 'directive': 'Quant Labs live signal integration (test)', 'production': production,
            'scope': [{'lab': l, 'key': k, 'version': v, 'tier': t} for l, k, v, t in scope]}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        register_codex(self.store)
        self.model = self.store.model(*CODEX)
        self.data = snapshot()
        decision = execute(self.model['source'], self.data)[0]
        self.signal, reason = qualify(self.data, self.model, {**decision, 'rationale': 'Compression escape fixture'}, ASOF)
        self.assertIsNone(reason)
        self.store.record(self.signal, True)
        self.store.queue_message(self.signal['signal_id'], message(self.signal), ASOF)
        self.env = mock.patch.dict(os.environ, {DELIVERY_ENV: '1'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def notify(self, client, at=ASOF, store=None):
        n = ExperimentalNotifier(store or self.store, client, 'chat', sleep=lambda s: None)
        n.process(at)
        return n

    def state(self, store=None):
        return (store or self.store).outbox()[0]['state']

    def test_no_approval_means_dry_run_even_with_flag(self):
        fake = FakeTelegram()
        self.notify(fake)
        self.assertEqual((fake.sent, self.state()), ([], 'DRY_RUN'))

    def test_flag_off_means_dry_run_even_with_approval(self):
        self.store.approve_delivery(approval([CODEX + ('RESEARCH_ONLY',)]))
        fake = FakeTelegram()
        with mock.patch.dict(os.environ, {DELIVERY_ENV: '0'}):
            self.notify(fake)
        self.assertEqual((fake.sent, self.state()), ([], 'DRY_RUN'))

    def test_approved_sends_ceo_format_once_and_never_after_restart(self):
        self.store.approve_delivery(approval([CODEX + ('RESEARCH_ONLY',)]))
        fake = FakeTelegram()
        self.notify(fake)
        self.notify(fake)
        self.assertEqual(self.state(), 'SENT')
        text = fake.sent[0]
        for part in ('🔬 <b>TRADEDEN QUANT LABS SIGNAL</b>', '🤖 Researcher: Codex', '🧠 Strategy: Compression Escape v0.1.0',
                     '📊 Instrument: <b>' + self.signal['symbol'], '📈 Direction: <b>', '⏰ Timeframe: M15', '🎯 Entry: ',
                     '🛑 Stop Loss: ', '💰 Take Profit: ', '⚖️ Risk/Reward: 1:', '📋 <b>WHY THIS SIGNAL?</b>', 'Compression escape fixture',
                     'Session: London (07-12 UTC)', '🔬 Classification: EXPERIMENTAL PAPER SIGNAL · RESEARCH ONLY',
                     '⚠️ Research observation only. Not a validated trading recommendation.', '🆔 ' + self.signal['signal_id']):
            self.assertIn(part, text)
        restarted = Store(self.tmp.name)  # application restart
        self.assertTrue(restarted.recover())
        self.notify(fake, store=restarted)
        Runtime(restarted, lambda *a: {'status': 'COMPLETE', 'decisions': []}).process(self.data, ASOF)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(restarted.signal(self.signal['signal_id'])['signal_id'], self.signal['signal_id'])

    def test_crash_mid_send_and_network_uncertainty_never_replayed(self):
        self.store.approve_delivery(approval([CODEX + ('PAPER_CANDIDATE',)]))
        self.notify(FakeTelegram(error=Exception('network error')))
        self.assertEqual(self.state(), 'DELIVERY_UNKNOWN')
        fake = FakeTelegram()
        self.store.recover()
        self.notify(fake)
        self.assertEqual(fake.sent, [])

    def test_http_rejection_recorded_as_failed(self):
        self.store.approve_delivery(approval([CODEX + ('PAPER_CANDIDATE',)]))
        self.notify(FakeTelegram(error=HttpError(400)))
        self.assertEqual(self.state(), 'FAILED')

    def test_stale_signal_expires_unsent(self):
        self.store.approve_delivery(approval([CODEX + ('PAPER_CANDIDATE',)]))
        fake = FakeTelegram()
        self.notify(fake, at=ASOF + 121)
        self.assertEqual((fake.sent, self.state()), ([], 'EXPIRED'))

    def test_disabling_or_revoking_stops_delivery(self):
        self.store.approve_delivery(approval([CODEX + ('PAPER_CANDIDATE',)]))
        self.store.set_status(*CODEX, 'DISABLED')
        fake = FakeTelegram()
        self.notify(fake)
        self.assertEqual((fake.sent, self.state()), ([], 'SUPPRESSED'))
        self.store.revoke_delivery('test')
        self.assertIsNone(self.store.delivery_approval())
        self.assertFalse(any(m['alert_enabled'] for m in self.store.models()))

    def test_approval_rules(self):
        with self.assertRaises(ValueError):
            self.store.approve_delivery(approval([CODEX + ('RESEARCH_ONLY',)], production=True))
        with self.assertRaises(ValueError):
            self.store.approve_delivery(approval([CODEX + ('PRODUCTION',)]))
        with self.assertRaises(ValueError):
            self.store.approve_delivery(approval([('claude', 'missing', '1.0.0', 'PAPER_CANDIDATE')]))
        with self.assertRaises(ValueError):
            self.store.approve_delivery({**approval([CODEX + ('RESEARCH_ONLY',)]), 'approved_by': ''})

    def test_weekend_aware_context_staleness(self):
        from quant_live.runtime import weekend_seconds
        friday_close = ASOF - 59 * 3600  # fixture ASOF is Monday 08:00 UTC; Friday 21:00 UTC D1 close
        self.assertEqual(weekend_seconds(friday_close, ASOF), 2 * 86400)
        self.assertEqual(weekend_seconds(ASOF, ASOF + 86400), 0)
        model = {**self.model, 'manifest': {**self.model['manifest'], 'requirements': {'M15': 300, 'D1': 20}}}
        decision = execute(self.model['source'], self.data)[0]
        bar = dict(self.data['frames']['M15'][-1])

        def reason(d1_close):
            snap = {**self.data, 'frames': {**self.data['frames'], 'D1': [{**bar, 'utc': d1_close - 86400}]}}
            return qualify(snap, model, decision, ASOF)[1]
        self.assertIsNone(reason(friday_close))                                       # Monday: Friday D1 accepted
        self.assertEqual(reason(ASOF - 5 * 86400), 'STALE_OR_MISSING_MODEL_CONTEXT')   # Wednesday D1: still stale

    def test_outcome_update_only_after_delivery_and_only_once(self):
        self.store.approve_delivery(approval([CODEX + ('PAPER_CANDIDATE',)]))
        fake = FakeTelegram()
        self.notify(fake)
        final = {'status': 'SL', 'r': -1.03, 'simulated_net_r': -1.03, 'actual_realized_r': None, 'exit_at': ASOF + 1800}
        self.store.outcome(self.signal['signal_id'], final, ASOF + 1800)
        self.store.outcome(self.signal['signal_id'], {**final, 'note': 'revision'}, ASOF + 1900)  # later revision: no second update
        self.notify(fake, at=ASOF + 1810)
        self.notify(fake, at=ASOF + 1820)
        self.assertEqual(len(fake.sent), 2)
        self.assertIn('STOP LOSS hit', fake.sent[1])
        self.assertIn('-1.03R', fake.sent[1])

    def test_no_outcome_update_for_undelivered_or_unresolved(self):
        fake = FakeTelegram()
        self.notify(fake)  # no approval: DRY_RUN, nothing delivered
        self.store.outcome(self.signal['signal_id'], {'status': 'TP', 'r': 3.0, 'simulated_net_r': 3.0, 'actual_realized_r': None, 'exit_at': ASOF + 60}, ASOF + 60)
        self.assertFalse(any(r['signal'].endswith('#outcome') for r in self.store.outbox()))
        other = Store(tempfile.mkdtemp(dir=self.tmp.name))
        register_codex(other)
        other.record(self.signal, True)
        other.queue_message(self.signal['signal_id'], message(self.signal), ASOF)
        other.approve_delivery(approval([CODEX + ('PAPER_CANDIDATE',)]))
        self.notify(fake, store=other)
        other.outcome(self.signal['signal_id'], {'status': 'INCOMPLETE', 'r': None, 'simulated_net_r': None, 'actual_realized_r': None}, ASOF + 60)
        self.assertFalse(any(r['signal'].endswith('#outcome') for r in other.outbox()))

    def test_overlapping_signals_do_not_inflate_statistics(self):
        second = {**self.signal, 'signal_id': self.signal['signal_id'] + 'b', 'signal_bar_closed_at': self.signal['signal_bar_closed_at'] + 900,
                  'entry_at': self.signal['entry_at'] + 900}
        self.store.record(second, True)
        for sid in (self.signal['signal_id'], second['signal_id']):
            self.store.outcome(sid, {'status': 'TP', 'r': 3.0, 'simulated_net_r': 3.0, 'actual_realized_r': None, 'exit_at': ASOF + 7200}, ASOF + 7200)
        perf = report(self.store)['breakdown']['model_version']['codex:compression_escape@0.1.0']
        self.assertEqual((perf['confirmed'], perf['overlapping_excluded'], perf['resolved'], perf['net_paper_r']), (2, 1, 1, 3.0))

    def test_diagnostics_distinguish_each_category(self):
        from quant_live.diagnostics import diagnostics
        bars = self.data['frames']['M15']
        def at(k):  # snapshot whose last closed M15 bar is k bars later, with a fresh quote
            frames = {**self.data['frames'], 'M15': bars + [{**bars[-1], 'utc': bars[-1]['utc'] + 900 * i} for i in range(1, k + 1)]}
            return {**self.data, 'frames': frames, 'asof': ASOF + 900 * k, 'quote': {**self.data['quote'], 'tick_at': ASOF + 900 * k}}
        Runtime(self.store, lambda *a: {'status': 'COMPLETE', 'decisions': []}).process(at(1), ASOF + 900)
        Runtime(self.store, lambda *a: {'status': 'COMPLETE', 'decisions': [{'direction': 'LONG', 'stop_loss': 1e9, 'take_profit': 1e9 + 1,
                                                                               'horizon_seconds': 3600, 'atr': 0.1, 'rationale': 'x'}]}).process(at(2), ASOF + 1800)
        Runtime(self.store, lambda *a: {'status': 'TIMED_OUT'}).process(at(3), ASOF + 2700)
        stale = {**at(4), 'quote': {**self.data['quote'], 'tick_at': ASOF}}
        Runtime(self.store, lambda *a: {'status': 'COMPLETE', 'decisions': []}).process(stale, ASOF + 3600)
        short = {**at(5), 'frames': {**at(5)['frames'], 'H1': at(5)['frames']['H1'][-10:]}}
        Runtime(self.store, lambda *a: {'status': 'COMPLETE', 'decisions': []}).process(short, ASOF + 4500)
        d = diagnostics(self.store)['models']['codex:compression_escape@0.1.0']
        self.assertEqual((d['evaluations'], d['no_setup'], d['setups'], d['stale_input_rejected'], d['insufficient_data']), (3, 2, 1, 1, 1))
        self.assertEqual(d['quality_rejected'], {'INVALID_GEOMETRY': 1})
        self.assertEqual(d['worker_failures'], {'TIMED_OUT': 1})
        self.assertEqual(d['last_successful_evaluation'], ASOF + 4500)

    def test_incomplete_signal_never_formatted(self):
        with self.assertRaises(ValueError):
            message({**self.signal, 'stop_loss': None})

    def test_tracking_counts_and_tier_separation(self):
        self.store.approve_delivery(approval([CODEX + ('RESEARCH_ONLY',)]))
        self.store.outcome(self.signal['signal_id'], {'status': 'TP', 'r': 3.1, 'simulated_net_r': 3.1, 'actual_realized_r': None, 'exit_at': ASOF + 3600}, ASOF + 3600)
        r = report(self.store)
        perf = r['breakdown']['model_version']['codex:compression_escape@0.1.0']
        self.assertEqual((perf['confirmed'], perf['triggered_entries'], perf['tp_hits'], perf['sl_hits'], perf['expired_time_exits']), (1, 1, 1, 0, 0))
        self.assertAlmostEqual(perf['net_paper_r'], 3.1)
        self.assertEqual(list(r['breakdown']['evidence_tier']), ['RESEARCH_ONLY'])
        self.assertEqual(r['production_models'], [])
        self.assertEqual(self.store.signal(self.signal['signal_id'])['state'], 'TP_HIT')


@unittest.skipUnless((PROJECT / 'quant_labs/state/shared').exists(), 'shared MT5 snapshot unavailable')
class HistoricalFiveStrategyTests(unittest.TestCase):
    """Real models, real bounded workers, genuine historical MT5 snapshots, fake Telegram."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PROJECT))
        from quant_labs.data import SharedData
        from quant_labs.evaluation.v1.engine import POLICY
        cls.data = SharedData(PROJECT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')
        cls.commission = POLICY['commission_price']

    def snapshot_at(self, manifest, symbol, t):
        tf_s = {'M1': 60, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}
        frames = {}
        for tf, n in manifest['requirements'].items():
            bars = self.data.read(symbol, tf)
            j = bisect_right([b['utc'] + tf_s[tf] for b in bars], t)
            frames[tf] = bars[max(0, j - n):j]
        quote = next(b for b in self.data.read(symbol, 'M15') if b['utc'] == t)
        meta = {**self.data.metadata(symbol), 'commission_price': self.commission[symbol], 'tradable_long': True, 'tradable_short': True}
        return {'symbol': symbol, 'broker_symbol': meta['broker_symbol'], 'source': 'HISTORICAL_TEST', 'source_basis': 'test', 'asof': t,
                'time_verified': True, 'input_sha256': f'hist-{symbol}-{t}', 'data_quality': {}, 'metadata': meta, 'frames': frames,
                'quote': {'bid': quote['open'], 'ask': quote['open'] + quote['spread'], 'tick_at': t}}

    def test_each_strategy_generates_delivers_once_and_resolves(self):
        results = PROJECT / 'quant_labs/state/labs/claude/research/results'
        intents = {'compression_escape': results / 'compression_escape_0.1.0_full_intents.json',
                   'index_trend_day': results / 'index_trend_day_0.2.0_full_intents.json',
                   'crypto_trend_breakout': results / 'crypto_trend_breakout_0.3.0_full_intents.json',
                   'hourly_shock_drift': results / 'hourly_shock_drift_0.1.0_full_intents.json',
                   'index_gap_fade': results / 'index_gap_fade_0.1.0_full_intents.json'}
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {DELIVERY_ENV: '1'}):
            store = Store(folder)
            for lab, key, path, tier in FIVE:
                m = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
                store.register(m, (path / 'model.py').read_text(encoding='utf-8'), m['authorship'])
            scope = [(lab, key, store.models()[[x['key'] for x in store.models()].index(key)]['version'], tier) for lab, key, path, tier in FIVE]
            store.approve_delivery(approval(scope))
            fake = FakeTelegram()
            outcome_states = {}
            for lab, key, path, tier in FIVE:
                intent = json.loads(intents[key].read_text())[-1]  # most recent historical firing
                model = next(x for x in store.models() if x['key'] == key)
                snap = self.snapshot_at(model['manifest'], intent['symbol'], intent['entry_at'])
                with mock.patch('quant_live.telegram.ExperimentalNotifier._transport', lambda self: fake), \
                     mock.patch('quant_live.telegram.MIN_INTERVAL', 0):
                    out = Runtime(store).process(snap, intent['entry_at'])
                    again = Runtime(store).process(snap, intent['entry_at'] + 30)  # same closed bar: no duplicate
                mine = [s for s in out['signals'] if s['model_key'] == key]
                self.assertEqual(len(mine), 1, (key, out))
                self.assertEqual(again['signals'], [])
                s = mine[0]
                tick = s['metadata']['tick_size']  # live gate rounds levels conservatively to the broker tick
                self.assertEqual(s['direction'], intent['direction'])
                self.assertLessEqual(abs(s['stop_loss'] - intent['stop_loss']), tick + 1e-9)
                self.assertLessEqual(abs(s['take_profit'] - intent['take_profit']), tick + 1e-9)
                later = [b for b in self.data.read(s['symbol'], 'M15') if s['entry_at'] - 900 <= b['utc'] <= s['deadline']]
                store.add_candles({'symbol': s['symbol'], 'frames': {'M15': later}, 'asof': s['deadline'] + 900})
                Runtime(store).resolve(s['symbol'], s['deadline'] + 900)
                outcome_states[key] = store.outcomes()[s['signal_id']]['status']
            signals_sent = [t for t in fake.sent if 'TRADEDEN QUANT LABS SIGNAL</b>' in t]
            self.assertEqual(len(signals_sent), 5)
            self.assertEqual(sum('RESEARCH ONLY' in t for t in signals_sent), 3)
            self.assertTrue(all('SIGNAL OUTCOME' in t for t in fake.sent if t not in signals_sent))
            self.assertTrue(all(st in ('TP', 'SL', 'TIME_EXIT', 'INCOMPLETE', 'AMBIGUOUS') for st in outcome_states.values()), outcome_states)
            r = report(store)
            self.assertEqual(sorted(r['breakdown']['evidence_tier']), ['PAPER_CANDIDATE', 'RESEARCH_ONLY'])
            self.assertEqual(sum(v['confirmed'] for v in r['breakdown']['model_version'].values()), 5)
            print('\nhistorical outcomes:', outcome_states)


if __name__ == '__main__':
    unittest.main()
