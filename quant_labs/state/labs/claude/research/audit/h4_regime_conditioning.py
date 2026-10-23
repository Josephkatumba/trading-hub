"""Pre-registered H4 (commit 862075e): does an H1 TRENDING regime at entry (rule R1) raise expectancy
of the momentum candidates? Existing frozen-evaluator trades only; regime from candles closed before entry."""
import json
import sqlite3
import statistics
import sys
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
from quant_labs.data import SharedData

POLICY = json.loads((ROOT / 'quant_labs/evaluation/v1/policy.json').read_text())
EDGES = [datetime.fromisoformat(POLICY[k]).timestamp() for k in ('validation_start', 'test_start')]
JOBS = {'crypto_trend_breakout 0.3.0': '07673508', 'trend_reclaim_r4 (BTCUSD job)': '87839dcb', 'index_trend_day 0.1.0/0.2.0': 'e350c08d'}
data = SharedData(ROOT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')
db = sqlite3.connect(f"file:{(ROOT / 'quant_labs/state/control.sqlite3').as_posix()}?mode=ro", uri=True)
h1_cache = {}


def r1(symbol, at):
    if symbol not in h1_cache:
        bars = data.read(symbol, 'H1')
        h1_cache[symbol] = (bars, [b['utc'] + 3600 for b in bars])
    bars, closes = h1_cache[symbol]
    j = bisect_right(closes, at)  # candles closed at or before entry
    if j < 25:
        return None
    c = [b['close'] for b in bars[j - 25:j]]
    path = sum(abs(c[i] - c[i - 1]) for i in range(1, 25))
    return 'TRENDING' if path and abs(c[-1] - c[0]) / path >= 0.35 else 'OTHER'


def split(t):
    return 'train' if t < EDGES[0] else 'validation' if t < EDGES[1] else 'test (exposed)'


out = {}
for name, job in JOBS.items():
    trades = json.loads(db.execute('SELECT body FROM results WHERE job LIKE ?', (job + '%',)).fetchone()[0])['trades']
    cells = {}
    for t in trades:
        if t['normal'].get('r') is None:
            continue
        g = r1(t['plan']['symbol'], t['plan']['entry_at'])
        if g:
            cells.setdefault((split(t['plan']['entry_at']), g), []).append(t['normal']['r'])
    rows = {f'{s} | {g}': {'n': len(v), 'exp': statistics.fmean(v)} for (s, g), v in sorted(cells.items())}
    verdict = []
    for s in ('train', 'validation'):
        a, b = cells.get((s, 'TRENDING'), []), cells.get((s, 'OTHER'), [])
        ok = len(a) >= 15 and len(b) >= 15 and statistics.fmean(a) > statistics.fmean(b)
        verdict.append(ok)
    out[name] = {'cells': rows, 'prediction_holds_train_and_validation': all(verdict),
                 'adopt_filter': all(verdict)}
    print(name, '-> prediction holds in train & validation (>=15 each):', all(verdict))
    for k, v in rows.items():
        print(f'   {k:28s} n={v["n"]:3d} exp={v["exp"]:+.3f}R')
(HERE / 'h4_regime_conditioning.json').write_text(json.dumps(out, indent=1))
