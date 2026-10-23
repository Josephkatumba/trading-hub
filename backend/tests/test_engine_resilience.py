"""Engine health summary and conservative watchdog (fakes only; never launches or kills a real process)."""
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quant_live.store import Store
from quant_live.runtime import register_codex
from quant_live.health import health, market_closed
from ops.watchdog import Watchdog, FAILS_BEFORE_LAUNCH, GRACE_SECONDS, MAX_LAUNCHES_PER_HOUR

WED = datetime(2026, 10, 21, 12, tzinfo=timezone.utc).timestamp()
SAT = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        register_codex(self.store)

    def status(self, now, age, enabled=True, running=True):
        return {'enabled': enabled, 'running': running, 'last_processed': now - 5,
                'latest_inputs': {'XAUUSD': {'asof': now - age}, 'BTCUSD': {'asof': now - age}}}

    def test_ok_when_fresh(self):
        h = health(self.store, self.status(WED, 20), WED, beats=[])
        self.assertEqual(h['status'], 'OK', h['reasons'])

    def test_stale_input_degrades_but_weekend_closure_does_not(self):
        self.assertEqual(health(self.store, self.status(WED, 900), WED, beats=[])['status'], 'DEGRADED')
        weekend = health(self.store, self.status(SAT, 900), SAT, beats=[])
        self.assertEqual(weekend['inputs']['XAUUSD']['state'], 'MARKET_CLOSED')
        self.assertEqual(weekend['inputs']['BTCUSD']['state'], 'STALE')  # crypto trades at weekends
        self.assertTrue(market_closed('XAUUSD', SAT) and not market_closed('BTCUSD', SAT))

    def test_stopped_consumer_is_down(self):
        self.assertEqual(health(self.store, self.status(WED, 20, running=False), WED, beats=[])['status'], 'DOWN')


class WatchdogTests(unittest.TestCase):
    def make(self, port_states, dry_run=False):
        self.t = [1000.0]
        self.launched = []
        states = iter(port_states)
        dog = Watchdog(probe_port=lambda: next(states), probe_health=lambda: (True, {'mt5_connected': True}),
                       launcher=lambda: self.launched.append(self.t[0]), clock=lambda: self.t[0],
                       log_path=Path(self.tmpdir.name) / 'w.jsonl', dry_run=dry_run)
        return dog

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def run_ticks(self, dog, n, step=60):
        out = []
        for _ in range(n):
            out.append(dog.tick())
            self.t[0] += step
        return out

    def test_healthy_engine_never_touched(self):
        dog = self.make([True] * 5)
        self.assertEqual(set(self.run_ticks(dog, 5)), {'HEALTHY'})
        self.assertEqual(self.launched, [])

    def test_relaunch_only_after_consecutive_down_then_grace(self):
        dog = self.make([False] * FAILS_BEFORE_LAUNCH + [True] * 10)
        out = self.run_ticks(dog, FAILS_BEFORE_LAUNCH + 2)
        self.assertEqual(out[:FAILS_BEFORE_LAUNCH], ['DOWN_SUSPECTED'] * (FAILS_BEFORE_LAUNCH - 1) + ['RELAUNCHED'])
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(out[FAILS_BEFORE_LAUNCH], 'GRACE')

    def test_transient_blip_does_not_relaunch(self):
        dog = self.make([False, True, False, True, False, True])
        self.run_ticks(dog, 6)
        self.assertEqual(self.launched, [])

    def test_hourly_limit_and_dry_run(self):
        dog = self.make([False] * 100)
        self.run_ticks(dog, 60, step=GRACE_SECONDS)
        self.assertGreater(len(self.launched), MAX_LAUNCHES_PER_HOUR)  # keeps retrying across hours, never faster
        self.assertLessEqual(max(sum(1 for t in self.launched if s <= t < s + 3600) for s in self.launched), MAX_LAUNCHES_PER_HOUR)
        dry = self.make([False] * 10, dry_run=True)
        self.run_ticks(dry, 5)
        self.assertEqual(self.launched, [])


class SingleInstanceTests(unittest.TestCase):
    def test_second_watchdog_cannot_acquire_lock(self):
        from ops.watchdog import single_instance_lock
        first = single_instance_lock()
        if first is None:
            self.skipTest('a watchdog is already running on this machine')
        try:
            self.assertIsNone(single_instance_lock())
        finally:
            first.close()


if __name__ == '__main__':
    unittest.main()
