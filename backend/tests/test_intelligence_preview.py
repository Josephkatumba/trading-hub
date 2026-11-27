"""Adversarial research-overlay regressions; no MT5, network or production store."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.intelligence_preview import evaluate, REQUIRED
from market_intel.rules import TF
from market_intel.engine import build

NOW = 1792594800


def frames():
    return {tf: [{'utc': NOW - (600-i)*TF[tf], 'open': 100+i*.01,
                  'close': 100.1+i*.01, 'high': 101+i*.01, 'low': 99+i*.01}
                 for i in range(600)] for tf in REQUIRED}


def quote():
    return {'bid': 106, 'ask': 106.01, 'tick_at': NOW}


class PreviewTests(unittest.TestCase):
    def test_baseline_quote_freshness_regression(self):
        for q in (None, {**quote(), 'tick_at': NOW+600}):
            self.assertFalse(build('BTCUSD', frames(), q, NOW)['stale'])
            self.assertEqual(evaluate('BTCUSD', frames(), q, NOW)['status'], 'BLOCKED')

    def test_baseline_unavailable_h4_can_satisfy_scenario(self):
        f = frames()
        f['H4'] = []
        q = {**quote(), 'bid': 100, 'ask': 100.01}
        baseline = build('BTCUSD', f, q, NOW)
        self.assertTrue(baseline['scenarios']['bullish']['currently_met'])
        preview = evaluate('BTCUSD', f, q, NOW)
        self.assertFalse(preview['analysis']['scenarios']['bullish']['currently_met'])

    def test_valid_context_never_qualifies(self):
        for symbol in ('XAUUSD', 'BTCUSD'):
            result = evaluate(symbol, frames(), quote(), NOW)
            self.assertEqual(result['status'], 'CONTEXT_ONLY')
            self.assertFalse(result['qualified'])
            self.assertFalse(result['production_enabled'])

    def test_quote_failures(self):
        for q in (None, {}, {**quote(), 'tick_at': NOW+1},
                  {**quote(), 'tick_at': NOW-121}, {**quote(), 'ask': 105},
                  {**quote(), 'bid': float('nan')}, {**quote(), 'tick_at': True}):
            with self.subTest(quote=q):
                result = evaluate('XAUUSD', frames(), q, NOW)
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertFalse(result['analysis']['scenarios']['bullish']['currently_met'])

    def test_each_timeframe_freshness_is_independent(self):
        for tf in REQUIRED:
            f = frames()
            f[tf] = f[tf][:-3]
            self.assertIn(f'{tf}: stale or absent history', evaluate('BTCUSD', f, quote(), NOW)['blockers'])

    def test_bad_history_is_not_silently_repaired(self):
        for mutation in ('duplicate', 'unordered', 'nonfinite', 'ohlc', 'timestamp'):
            f = frames()
            if mutation == 'duplicate':
                f['H1'].append(dict(f['H1'][-1]))
            elif mutation == 'unordered':
                f['H1'][-1], f['H1'][-2] = f['H1'][-2], f['H1'][-1]
            elif mutation == 'nonfinite':
                f['H1'][-1]['close'] = float('inf')
            elif mutation == 'ohlc':
                f['H1'][-1]['low'] = 999
            else:
                f['H1'][-1]['utc'] = None
            self.assertIsNone(evaluate('BTCUSD', f, quote(), NOW)['analysis'])

    def test_gaps_and_missing_context_block(self):
        f = frames()
        del f['M15'][-8]
        f['H4'] = []
        r = evaluate('XAUUSD', f, quote(), NOW)
        self.assertEqual(r['data_quality']['M15']['recent_unclassified_gaps'], 1)
        self.assertFalse(r['analysis']['scenarios']['bullish']['currently_met'])

    def test_high_cost_and_zero_atr_block(self):
        self.assertIn('spread exceeds research ATR threshold', evaluate('BTCUSD', frames(), {**quote(), 'ask': 110}, NOW)['blockers'])
        f = frames()
        for b in f['H1']:
            b.update(open=100, high=100, low=100, close=100)
        self.assertIn('spread-to-ATR unavailable', evaluate('BTCUSD', f, quote(), NOW)['blockers'])

    def test_prefix_invariance_and_input_immutability(self):
        f, q = frames(), quote()
        saved = copy.deepcopy(f)
        expected = evaluate('BTCUSD', f, q, NOW)
        self.assertEqual(f, saved)
        for tf in REQUIRED:
            f[tf].append({'utc': NOW, 'open': 900, 'high': 1000, 'low': 1, 'close': 999})
        self.assertEqual(evaluate('BTCUSD', f, q, NOW), expected)


if __name__ == '__main__':
    unittest.main()
