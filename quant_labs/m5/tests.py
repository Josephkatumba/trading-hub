"""Isolated tests for the M5 extension (temporary roots; the real ledger is never touched)."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from ..control import ControlPlane
from ..data import snapshot, SharedData, digest
from ..frozen import VERSION_DIR, verify as verify_v1
from ..evaluation.v1.engine import evaluate as evaluate_v1
from ..queue import run_one as run_one_v1
from ..tests import fixture_cache, spec as v1_spec
from .control import M5Control
from .data import aggregate_m5, M5SharedData
from .engine import evaluate as evaluate_m5
from .queue import run_one
from . import frozen

BASE = Path(__file__).resolve().parents[1]


def m5_spec(key='m5_contract'):
    return {**v1_spec(key), 'timeframe': 'M5', 'name': 'M5 contract fixture'}


class AggregationTests(unittest.TestCase):
    def bar(self, t, o=1.0, h=1.2, l=0.9, c=1.1, s=0.01):
        return {'utc': t, 'time': t, 'open': o, 'high': h, 'low': l, 'close': c, 'spread': s, 'tick_volume': 2}

    def test_complete_bucket_exact_ohlc(self):
        m1 = [self.bar(600 + 60 * k, o=1 + k, h=2 + k, l=0.5 + k, c=1.5 + k, s=0.01 * (k + 1)) for k in range(5)]
        (b,) = aggregate_m5(m1)
        self.assertEqual((b['utc'], b['open'], b['high'], b['low'], b['close']), (600, 1, 6, 0.5, 5.5))
        self.assertAlmostEqual(b['spread'], 0.05)
        self.assertEqual(b['tick_volume'], 10)

    def test_incomplete_bucket_dropped_not_filled(self):
        m1 = [self.bar(600 + 60 * k) for k in (0, 1, 2, 4)] + [self.bar(900 + 60 * k) for k in range(5)]
        self.assertEqual([b['utc'] for b in aggregate_m5(m1)], [900])

    def test_misaligned_start_dropped(self):
        m1 = [self.bar(660 + 60 * k) for k in range(5)]
        self.assertEqual(aggregate_m5(m1), [])


class M5PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tests_m5_', dir=BASE / 'verification')
        self.root = Path(self.temp.name)
        self.start = fixture_cache(self.root / 'cache')
        self.c = ControlPlane(self.root / 'state')
        self.dataset = snapshot(self.root / 'cache', self.c.root / 'shared')
        self.c.initialize(self.dataset, digest((VERSION_DIR / 'freeze.json').read_bytes()))
        self.tokens = json.loads((self.c.root / 'owner/credentials.json').read_text())
        self.m5 = M5Control(self.c.root)
        at = self.start + 12 * 3600 + 300
        self.intents = [{'symbol': 'EURUSD', 'direction': 'LONG', 'signal_bar_closed_at': at, 'entry_at': at,
                         'stop_loss': 99, 'take_profit': 102.06, 'horizon_seconds': 3600}]

    def tearDown(self):
        self.temp.cleanup()

    def register(self, lab='claude'):
        return self.m5.register(self.tokens['lab:' + lab], lab, m5_spec(), '# reviewable infrastructure source\n')

    def test_frozen_v1_untouched_and_extension_sealed(self):
        verify_v1(digest((VERSION_DIR / 'freeze.json').read_bytes()))
        manifest = frozen.verify(frozen.identity())
        self.assertEqual(manifest['wraps_v1_evaluator'], digest((VERSION_DIR / 'freeze.json').read_bytes()))

    def test_v1_ledger_still_rejects_m5_and_m5_ledger_rejects_others(self):
        with self.assertRaises(ValueError):
            self.c.register(self.tokens['lab:claude'], 'claude', m5_spec(), '# source\n')
        with self.assertRaises(ValueError):
            self.m5.register(self.tokens['lab:claude'], 'claude', v1_spec(), '# source\n')

    def test_lab_boundaries(self):
        with self.assertRaises(PermissionError):
            self.m5.register(self.tokens['lab:claude'], 'kimi', m5_spec(), '# source\n')
        self.register()
        with self.assertRaises(PermissionError):
            self.m5.submit(self.tokens['lab:kimi'], 'claude', 'm5_contract', '1.0.0', self.intents)

    def test_versions_and_results_immutable(self):
        self.register()
        with self.assertRaises(sqlite3.IntegrityError):
            self.register()

    def test_submission_semantics(self):
        self.register()
        bad = [{**self.intents[0], 'entry_at': self.intents[0]['entry_at'] + 60, 'signal_bar_closed_at': self.intents[0]['entry_at'] + 60}]
        with self.assertRaises(ValueError):
            self.m5.submit(self.tokens['lab:claude'], 'claude', 'm5_contract', '1.0.0', bad)
        with self.assertRaises(ValueError):
            self.m5.submit(self.tokens['lab:claude'], 'claude', 'm5_contract', '1.0.0', [{**self.intents[0], 'outcome_r': 3}])
        first = self.m5.submit(self.tokens['lab:claude'], 'claude', 'm5_contract', '1.0.0', self.intents)
        again = self.m5.submit(self.tokens['lab:claude'], 'claude', 'm5_contract', '1.0.0', self.intents)
        self.assertEqual((first['state'], again['state'], again['duplicate_of']), ('QUEUED', 'DUPLICATE', first['job']))

    def test_scoring_identical_to_frozen_v1_m1_frame(self):
        shared = SharedData(self.c.root / 'shared', self.dataset)
        signals = [{**self.intents[0], 'entry_at': self.start + h * 3600 + 300 * k, 'signal_bar_closed_at': self.start + h * 3600 + 300 * k}
                   for h, k in ((12, 1), (15, 2), (20, 3))]
        m5 = evaluate_m5(M5SharedData(shared), {'strategy': m5_spec(), 'signals': signals})
        v1 = evaluate_v1(shared, {'strategy': {**m5_spec(), 'timeframe': 'M1'}, 'signals': signals})
        self.assertEqual(m5['trades'], v1['trades'])
        self.assertEqual(m5['periods'], v1['periods'])
        self.assertEqual(m5['m5_admitted'], 3)

    def test_missing_confirming_m5_candle_rejected(self):
        shared = SharedData(self.c.root / 'shared', self.dataset)
        first = int(self.start)
        signals = [{**self.intents[0], 'entry_at': first, 'signal_bar_closed_at': first}]
        result = evaluate_m5(M5SharedData(shared), {'strategy': m5_spec(), 'signals': signals})
        self.assertEqual(result['rejections'].get('m5_confirming_bar_unavailable'), 1)
        self.assertEqual(result['trades'], [])

    def test_operator_only_bounded_worker_and_separate_queue(self):
        self.register()
        job = self.m5.submit(self.tokens['lab:claude'], 'claude', 'm5_contract', '1.0.0', self.intents)['job']
        with self.assertRaises(PermissionError):
            run_one(self.m5, self.tokens['lab:claude'])
        self.assertEqual(run_one_v1(self.c, self.tokens['operator:owner'])['status'], 'EMPTY')  # v1 never sees M5 jobs
        answer = run_one(self.m5, self.tokens['operator:owner'], wall_seconds=20, memory_mb=256)
        self.assertEqual(answer['status'], 'COMPLETE', answer)
        self.assertTrue(answer['resources']['enforced'])
        self.assertEqual(answer['resources']['max_processes'], 1)
        with self.m5.connect() as c:
            body = json.loads(c.execute('SELECT body FROM results WHERE job=?', (job,)).fetchone()[0])
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('UPDATE results SET body="{}" WHERE job=?', (job,))
        self.assertEqual(body['m5_admitted'], 1)
        self.assertFalse(body['profitability_certified'])
        self.assertEqual(self.m5.public()['qualified_leaderboard'], [])
        exports = (self.c.workspace('claude') / 'm5_performance.jsonl').read_text().strip().splitlines()
        self.assertEqual(len(exports), 1)


if __name__ == '__main__':
    unittest.main()
