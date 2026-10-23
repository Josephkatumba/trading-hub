"""Milestone 3.1: are Crypto Trend Breakout 0.3.0 and Codex BTCUSD Trend Reclaim r4 the same evidence?

Uses only completed frozen-evaluator trades. Measures, on BTCUSD:
  * time overlap: share of each strategy's trades open while the other has a same-direction trade open;
  * correlation of weekly net R (weeks where either traded);
  * a combined, non-overlapping view (same-direction concurrent trades counted once).
No parameters are chosen here.
"""
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
db = sqlite3.connect(f"file:{(ROOT / 'quant_labs/state/control.sqlite3').as_posix()}?mode=ro", uri=True)


def trades(job_prefix):
    body = db.execute("SELECT r.body FROM results r WHERE r.job LIKE ?", (job_prefix + '%',)).fetchone()[0]
    out = []
    for t in json.loads(body)['trades']:
        if t['plan']['symbol'] == 'BTCUSD' and t['normal'].get('r') is not None:
            out.append({'start': t['plan']['entry_at'], 'end': t['normal']['exit_at'], 'dir': t['plan']['direction'], 'r': t['normal']['r']})
    return out


def overlap(a, b):
    hits = sum(any(x['dir'] == y['dir'] and x['start'] < y['end'] and y['start'] < x['end'] for y in b) for x in a)
    return hits / len(a) if a else None


def weekly(ts):
    w = defaultdict(float)
    for t in ts:
        w[int(t['start'] // 604800)] += t['r']
    return w


breakout = trades('07673508')   # claude crypto_trend_breakout 0.3.0
reclaim = trades('87839dcb')    # codex trend_reclaim_r4, BTCUSD job
wa, wb = weekly(breakout), weekly(reclaim)
weeks = sorted(set(wa) | set(wb))
xa, xb = [wa.get(w, 0.0) for w in weeks], [wb.get(w, 0.0) for w in weeks]
corr = statistics.correlation(xa, xb) if len(weeks) > 2 else None
both_weeks = sorted(set(wa) & set(wb))
result = {'btc_trades': {'crypto_trend_breakout_0.3.0': len(breakout), 'trend_reclaim_r4': len(reclaim)},
          'share_of_breakout_trades_overlapping_same_direction_reclaim': overlap(breakout, reclaim),
          'share_of_reclaim_trades_overlapping_same_direction_breakout': overlap(reclaim, breakout),
          'weeks_with_trades': len(weeks), 'weeks_both_traded': len(both_weeks), 'weekly_net_r_correlation': corr,
          'breakout_btc_mean_r': statistics.fmean(t['r'] for t in breakout), 'reclaim_btc_mean_r': statistics.fmean(t['r'] for t in reclaim)}
(HERE / 'crypto_momentum.json').write_text(json.dumps(result, indent=1))
print(json.dumps(result, indent=1))
