"""Fake-broker tests for the maintenance M1 refresh (no MT5 connection, no real cache writes)."""
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from .m1_history_refresh import refresh, compare_overlap, gaps, presample


def bars(times, price=1.0):
    return [{'utc': t, 'time': t, 'open': price, 'high': price + .1, 'low': price - .1, 'close': price, 'spread': .01, 'tick_volume': 1} for t in times]


class M1RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='tradeden_m1_test_')
        self.old = Path(self.tmp.name) / 'old'
        self.old.mkdir()
        meta = {'broker_symbol': 'USTEC', 'tick_size': .01, 'point': .01}
        (self.old / 'manifest.json').write_text(json.dumps({'basis': 'x', 'start': 's', 'end': 'e', 'symbols': {'NAS100': {'meta': meta}}}))
        for tf in ('M15', 'H1', 'H4', 'D1'):
            with gzip.open(self.old / f'NAS100_{tf}.json.gz', 'wt') as f:
                json.dump(bars([0, 900]), f)
        with gzip.open(self.old / 'NAS100_M1.json.gz', 'wt') as f:
            json.dump(bars([600, 660, 720]), f)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_cache_only_broker_bars_gaps_reported_old_untouched(self):
        calls = []

        def download(mt5, broker, tf, start, end):
            calls.append((broker, tf))
            return bars([0, 60, 120, 600, 660, 720])  # broker gap 180..540 must stay a gap

        before = {p.name: p.read_bytes() for p in self.old.iterdir()}
        out = Path(self.tmp.name) / 'new'
        report = refresh(None, download, ['NAS100'], datetime(2024, 10, 15, tzinfo=timezone.utc), datetime(2026, 10, 20, tzinfo=timezone.utc), out, self.old)
        self.assertEqual(calls, [('USTEC', 'M1')])
        self.assertEqual(report['NAS100']['bars'], 6)
        self.assertEqual(report['NAS100']['gaps_reported_not_filled'], 1)
        self.assertEqual((report['NAS100']['overlap_minutes'], report['NAS100']['differing_minutes']), (3, 0))
        with gzip.open(out / 'NAS100_M1.json.gz', 'rt') as f:
            self.assertEqual([b['utc'] for b in json.load(f)], [0, 60, 120, 600, 660, 720])
        self.assertEqual((out / 'NAS100_H1.json.gz').read_bytes(), before['NAS100_H1.json.gz'])
        self.assertEqual({p.name: p.read_bytes() for p in self.old.iterdir()}, before)
        with self.assertRaises(FileExistsError):  # never overwrites an existing output cache
            refresh(None, download, ['NAS100'], datetime(2024, 10, 15, tzinfo=timezone.utc), datetime(2026, 10, 20, tzinfo=timezone.utc), out, self.old)

    def test_presample_never_overlaps_the_research_window(self):
        end = datetime(2024, 8, 14, tzinfo=timezone.utc)
        inside, after = end.timestamp() - 3600, end.timestamp() + 900
        report = presample(None, lambda m, b, tf, s0, e0: bars([inside, after]), ['NAS100'], datetime(2022, 1, 1, tzinfo=timezone.utc), end,
                           Path(self.tmp.name) / 'pre', self.old, timeframes=('M15', 'H1'))
        with gzip.open(Path(self.tmp.name) / 'pre' / 'NAS100_M15.json.gz', 'rt') as f:
            self.assertEqual([b['utc'] for b in json.load(f)], [inside])
        self.assertEqual(report['NAS100']['M15']['bars'], 1)

    def test_overlap_revision_detected(self):
        self.assertEqual(compare_overlap(bars([60]), bars([60], price=2.0))['differing_minutes'], 1)
        self.assertEqual(gaps(bars([0, 60, 180])), 1)


if __name__ == '__main__':
    unittest.main()
