"""Derived M5 candles from the frozen shared M1 snapshot. Nothing is synthesised.

An M5 candle exists only when all five M1 candles of its bucket exist in the validated
shared M1 series (contiguous minutes, no duplicates). Incomplete buckets are dropped and
remain gaps; prices are never interpolated or carried forward.
"""


def aggregate_m5(m1):
    """Complete M5 candles from validated, time-ordered M1 candles."""
    out = []
    i, n = 0, len(m1)
    while i < n:
        start = int(m1[i]['utc']) - int(m1[i]['utc']) % 300
        j = i
        while j < n and m1[j]['utc'] < start + 300:
            j += 1
        group = m1[i:j]
        if len(group) == 5 and all(group[k]['utc'] == start + 60 * k for k in range(5)):
            out.append({'utc': start, 'time': group[0].get('time', start), 'open': group[0]['open'],
                        'high': max(b['high'] for b in group), 'low': min(b['low'] for b in group),
                        'close': group[-1]['close'], 'spread': max(b['spread'] for b in group),
                        'tick_volume': sum(b.get('tick_volume', 0) for b in group)})
        i = j
    return out


class M5SharedData:
    """Read-only view over a verified SharedData snapshot that adds derived M5 candles."""

    def __init__(self, shared):
        self.shared, self.manifest, self.dataset = shared, shared.manifest, shared.dataset
        self._m5 = {}

    def read(self, symbol, timeframe):
        if timeframe != 'M5':
            return self.shared.read(symbol, timeframe)
        if symbol not in self._m5:
            self._m5[symbol] = aggregate_m5(self.shared.read(symbol, 'M1'))
        return [dict(b) for b in self._m5[symbol]]

    def metadata(self, symbol):
        return self.shared.metadata(symbol)
