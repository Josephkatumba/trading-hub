"""Milestone 3.3: Range Sweep Reversion regime diagnostic (no parameter selection).

For each completed frozen-evaluator trade of Codex range_sweep_reversion (EURUSD, BTCUSD,
XAUUSD jobs), measure the regime at entry from closed H1 candles only:
  * trend: H1 efficiency ratio over 24 candles (< 0.25 range-bound, >= 0.25 trending);
  * volatility: ATR(H1, 24) percentile vs the prior 30 days (low < 1/3, high > 2/3).
Then report net R by regime and split. If the test-split gains sit in a regime that also lost in
train/validation, the test result is not a stable conditional edge.
"""
import json
import sqlite3
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
from quant_labs.data import SharedData

POLICY = json.loads((ROOT / 'quant_labs/evaluation/v1/policy.json').read_text())
EDGES = [datetime.fromisoformat(POLICY[k]).timestamp() for k in ('validation_start', 'test_start')]
data = SharedData(ROOT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')
db = sqlite3.connect(f"file:{(ROOT / 'quant_labs/state/control.sqlite3').as_posix()}?mode=ro", uri=True)


def split(t):
    return 'train' if t < EDGES[0] else 'validation' if t < EDGES[1] else 'test'


def regime(h1, closes_at, at):
    j = bisect_left(closes_at, at + 1)  # candles closed at or before entry
    if j < 24 * 31:
        return None
    window = h1[j - 25:j]
    c = [b['close'] for b in window]
    path = sum(abs(c[i] - c[i - 1]) for i in range(1, len(c)))
    er = abs(c[-1] - c[0]) / path if path else 0
    def atr(k):
        seg = h1[k - 24:k]
        return statistics.fmean(max(b['high'] - b['low'], abs(b['high'] - a['close']), abs(b['low'] - a['close'])) for a, b in zip(h1[k - 25:k - 1], seg))
    now = atr(j)
    hist = [atr(k) for k in range(j - 24 * 30, j, 24)]
    pct = sum(h < now for h in hist) / len(hist)
    return ('trending' if er >= 0.25 else 'range-bound') + '/' + ('low-vol' if pct < 1 / 3 else 'high-vol' if pct > 2 / 3 else 'mid-vol')


out = defaultdict(lambda: defaultdict(list))
for (body,) in db.execute("SELECT r.body FROM results r JOIN jobs j ON j.id=r.job WHERE j.lab='codex' AND j.strategy='range_sweep_reversion'"):
    trades = [t for t in json.loads(body)['trades'] if t['normal'].get('r') is not None]
    if not trades:
        continue
    symbol = trades[0]['plan']['symbol']
    h1 = data.read(symbol, 'H1')
    closes_at = [b['utc'] + 3600 for b in h1]
    for t in trades:
        g = regime(h1, closes_at, t['plan']['entry_at'])
        if g:
            out[(symbol, g)][split(t['plan']['entry_at'])].append(t['normal']['r'])
rows = []
for (symbol, g), per in sorted(out.items()):
    row = {'symbol': symbol, 'regime': g}
    for s in ('train', 'validation', 'test'):
        rs = per.get(s, [])
        row[s] = {'n': len(rs), 'exp': statistics.fmean(rs) if rs else None}
    rows.append(row)
    print(f"{symbol} {g:22s} " + ' | '.join(f"{s[:3]} n={row[s]['n']:2d} {('NA' if row[s]['exp'] is None else format(row[s]['exp'], '+.2f'))}" for s in ('train', 'validation', 'test')))
(HERE / 'range_sweep_regimes.json').write_text(json.dumps(rows, indent=1))
