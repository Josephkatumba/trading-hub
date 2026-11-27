"""XAUUSD/BTCUSD intelligence: explicit rules, no look-ahead, honest unavailability, no trade levels."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from market_intel import rules as R
from market_intel.engine import build, render_telegram


def ts(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


def series(start, n, step, slope):
    out = []
    for i in range(n):
        base = 100 + slope * i
        out.append({'utc': start + i * step, 'open': base, 'high': base + 0.5, 'low': base - 0.5, 'close': base + 0.1 * (1 if slope >= 0 else -1)})
    return out


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


class RuleTests(unittest.TestCase):
    def test_trend_rule(self):
        self.assertEqual(R.trend(series(0, 80, 3600, 1))['state'], 'UP')
        self.assertEqual(R.trend(series(0, 80, 3600, -1))['state'], 'DOWN')
        self.assertEqual(R.trend(series(0, 30, 3600, 1))['state'], 'UNAVAILABLE')

    def test_level_events(self):
        bar = lambda c, h=None, l=None: {'utc': 0, 'open': c, 'high': h if h is not None else c, 'low': l if l is not None else c, 'close': c}
        self.assertEqual(R.level_event([bar(99), bar(101), bar(102)], 100, 'above')['event'], 'ACCEPTED')
        self.assertEqual(R.level_event([bar(99), bar(101), bar(99)], 100, 'above')['event'], 'FAILED')
        self.assertEqual(R.level_event([bar(99, h=101), bar(99)], 100, 'above')['event'], 'SWEEP')
        self.assertEqual(R.level_event([bar(99), bar(98)], 100, 'above')['event'], 'UNTESTED')
        self.assertEqual(R.level_event([bar(101), bar(99), bar(98)], 100, 'below')['event'], 'ACCEPTED')

    def test_session_clock_is_dst_aware(self):
        summer, winter = ts(2026, 7, 1, 7, 30), ts(2026, 12, 1, 7, 30)
        self.assertEqual(R.offset('UK', summer), 3600)
        self.assertEqual(R.offset('UK', winter), 0)
        self.assertEqual(R.offset('US', summer), -4 * 3600)
        self.assertEqual(R.offset('US', winter), -5 * 3600)
        self.assertEqual(R.sessions([], summer)['current'], 'London')          # 08:30 London in summer
        self.assertEqual(R.sessions([], winter)['current'], 'Pre-London')      # 07:30 London in winter
        self.assertEqual(R.sessions([], ts(2026, 7, 1, 13, 45))['current'], 'London/New York overlap')
        self.assertEqual(R.sessions([], ts(2026, 10, 24, 12))['current'], 'Weekend')


class EngineTests(unittest.TestCase):
    def frames(self, now):
        return {'M15': series(now - 400 * 900, 400, 900, 0.01), 'H1': series(now - 600 * 3600, 600, 3600, 0.05),
                'H4': series(now - 199 * 14400, 199, 14400, 0.2), 'D1': series(now - 199 * 86400, 199, 86400, 1)}

    def test_no_trade_levels_and_unavailable_data_marked(self):
        now = ts(2026, 10, 21, 15)
        for symbol in ('XAUUSD', 'BTCUSD'):
            intel = build(symbol, self.frames(now), {'bid': 150, 'ask': 150.1, 'tick_at': now - 5}, now)
            forbidden = {k for k in keys(intel) if k in ('entry', 'stop_loss', 'take_profit', 'confidence')}
            self.assertEqual(forbidden, set())
            text = render_telegram(intel)
            self.assertIn('no entry, stop-loss or take-profit implied', text)
            self.assertIn('internal preview', text)
        gold = build('XAUUSD', self.frames(now), None, now)
        self.assertEqual(gold['macro']['us_treasury_yields']['state'], 'UNAVAILABLE')
        self.assertEqual(gold['macro']['economic_calendar']['state'], 'UNAVAILABLE')
        self.assertEqual(gold['macro']['usd_proxy']['state'], 'UNAVAILABLE')  # no FX context supplied
        btc = build('BTCUSD', self.frames(now), None, now)
        for k in ('funding_rates', 'open_interest', 'liquidations'):
            self.assertEqual(btc['crypto'][k]['state'], 'UNAVAILABLE')
        self.assertEqual(btc['crypto']['equity_correlation']['state'], 'UNAVAILABLE')

    def test_every_conclusion_is_explained(self):
        now = ts(2026, 10, 21, 15)
        intel = build('XAUUSD', self.frames(now), None, now)
        for e in intel['explanations']:
            self.assertTrue(e['rules'] and all(r in R.RULES for r in e['rules']))
            for k in ('observations', 'data_timestamp', 'missing', 'conflicts'):
                self.assertIn(k, e)
        self.assertIn(intel['scenarios']['bullish']['rule'], R.RULES)

    def test_stale_data_flagged(self):
        now = ts(2026, 10, 21, 15)
        intel = build('XAUUSD', self.frames(now - 7200), None, now)
        self.assertTrue(intel['stale'])
        self.assertIn('market data is stale', intel['scenarios']['neutral']['reasons'])


@unittest.skipUnless((PROJECT / 'quant_labs/state/shared').exists(), 'shared MT5 snapshot unavailable')
class NoLookAheadOnGenuineData(unittest.TestCase):
    def test_future_candles_never_change_the_analysis(self):
        sys.path.insert(0, str(PROJECT))
        from quant_labs.data import SharedData
        data = SharedData(PROJECT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')
        counts = {'M15': 400, 'H1': 600, 'H4': 199, 'D1': 199}
        for symbol, now in (('XAUUSD', ts(2026, 3, 18, 14, 15)), ('BTCUSD', ts(2026, 6, 10, 15, 30))):
            past, with_future = {}, {}
            for tf, n in counts.items():
                bars = data.read(symbol, tf)
                closed = [b for b in bars if b['utc'] + R.TF[tf] <= now][-n:]
                past[tf] = closed
                with_future[tf] = closed + [b for b in bars if b['utc'] + R.TF[tf] > now][:50]  # includes the forming and future candles
            a = build(symbol, past, None, now)
            b = build(symbol, with_future, None, now)
            self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))
            self.assertNotEqual(a['structure']['H1']['state'], 'UNAVAILABLE')


class ApiGuardTests(unittest.TestCase):
    def test_loopback_only_and_symbols_limited(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from quant_live.api import router
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        self.assertEqual(client.get('/api/quant-labs/intelligence/EURUSD').status_code, 404)
        with unittest.mock.patch.dict(os.environ, {'TRADING_HUB_AUTH_MODE': 'oidc'}):
            self.assertEqual(client.get('/api/quant-labs/intelligence/XAUUSD').status_code, 403)


import unittest.mock  # noqa: E402

if __name__ == '__main__':
    unittest.main()
