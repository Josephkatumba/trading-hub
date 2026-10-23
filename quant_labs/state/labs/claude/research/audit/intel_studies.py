"""Overnight statistical studies (rules fixed before running; descriptive, not strategies).

GOLD (XAUUSD M15, shared snapshot, DST-aware sessions):
  L = London move: close at the New York 09:30 open minus open at London 08:00, in daily ATR (14, broker days).
  N = New York move: close of the candle ending at 16:00 New York minus close at the New York open, in daily ATR.
  G1 sign agreement P(sign N = sign L) and the slope of N on L.
  G2 strong London (|L| >= 0.5): mean N in the direction of L (continuation > 0, reversal < 0).
  G3 London sweep: London traded beyond the Asian (00-06 UTC) high or low and the price at the New York open is
     back inside the Asian range: mean N in the sweep direction (positive = continuation of the sweep, negative = reversal).
BITCOIN (BTCUSD H1):
  B1 volatility clustering: correlation of |r_t| with |r_t-1| and |r_t-24|.
  B2 weekend vs weekday mean H1 range; US cash session (09:30-16:00 NY, weekdays) vs other weekday hours.
  B3 post-shock: after an H1 candle whose range >= 3x the median same-hour range of the prior 20 days, mean return of the
     next 4 H1 candles in the shock direction, in H1 ATR(24) (positive = continuation, negative = reversal).
Each statistic is reported per split (train / validation / test-exposed) with a bootstrap 95% CI.
"""
import json
import random
import statistics
import sys
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from quant_labs.data import SharedData
from market_intel import rules as R

POLICY = json.loads((ROOT / 'quant_labs/evaluation/v1/policy.json').read_text())
E = [datetime.fromisoformat(POLICY[k]).timestamp() for k in ('train_start', 'validation_start', 'test_start', 'test_end')]
data = SharedData(ROOT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')


def split(t):
    return None if t < E[0] or t >= E[3] else 'train' if t < E[1] else 'validation' if t < E[2] else 'test (exposed)'


def ci(xs, seed=11):
    if len(xs) < 5:
        return {'n': len(xs), 'mean': statistics.fmean(xs) if xs else None}
    rng = random.Random(seed)
    b = sorted(statistics.fmean(rng.choices(xs, k=len(xs))) for _ in range(2000))
    return {'n': len(xs), 'mean': statistics.fmean(xs), 'ci95': [b[50], b[1949]]}


def by_split(rows):
    out = {}
    for s in ('train', 'validation', 'test (exposed)'):
        out[s] = ci([v for t, v in rows if split(t) == s])
    return out


def gold():
    m15 = data.read('XAUUSD', 'M15')
    h1 = data.read('XAUUSD', 'H1')
    at = {b['utc']: b for b in m15}
    times = [b['utc'] for b in m15]
    agree, slope_pts, g2, g3 = [], [], [], []
    day = int(E[0] // 86400)
    while day * 86400 < E[3]:
        t0 = day * 86400 + 43200
        if R.weekday(t0) in (0, 6):
            day += 1
            continue
        lo_open = day * 86400 + 8 * 3600 - R.offset('UK', t0)
        ny_open = day * 86400 + 9 * 3600 + 1800 - R.offset('US', t0)
        ny_end = day * 86400 + 16 * 3600 - R.offset('US', t0)
        a, b, c = at.get(lo_open), at.get(ny_open - 900), at.get(ny_end - 900)
        if not (a and b and c):
            day += 1
            continue
        days, _ = R.broker_days([x for x in h1 if x['utc'] < lo_open][-24 * 25:], lo_open)
        if len(days) < 15:
            day += 1
            continue
        trs = [max(d['high'] - d['low'], abs(d['high'] - p['close']), abs(d['low'] - p['close'])) for p, d in zip(days[-15:-1], days[-14:])]
        datr = sum(trs) / len(trs)
        L = (b['close'] - a['open']) / datr
        N = (c['close'] - b['close']) / datr
        agree.append((lo_open, 1.0 if L * N > 0 else 0.0))
        slope_pts.append((lo_open, (L, N)))
        if abs(L) >= 0.5:
            g2.append((lo_open, N if L > 0 else -N))
        asia = [x for x in m15[bisect_left(times, day * 86400):bisect_left(times, day * 86400 + 6 * 3600)]]
        london = [x for x in m15[bisect_left(times, lo_open):bisect_left(times, ny_open)]]
        if len(asia) >= 20 and london:
            ah, al = max(x['high'] for x in asia), min(x['low'] for x in asia)
            took_high, took_low = max(x['high'] for x in london) > ah, min(x['low'] for x in london) < al
            inside = al <= b['close'] <= ah
            if inside and took_high != took_low:  # exactly one side swept, price back inside at the NY open
                g3.append((lo_open, N if took_high else -N))
        day += 1
    slopes = {}
    for s in ('train', 'validation', 'test (exposed)'):
        pts = [p for t, p in slope_pts if split(t) == s]
        if len(pts) > 10:
            mx = statistics.fmean(p[0] for p in pts)
            my = statistics.fmean(p[1] for p in pts)
            cov = sum((x - mx) * (y - my) for x, y in pts)
            var = sum((x - mx) ** 2 for x, _ in pts)
            slopes[s] = {'n': len(pts), 'slope_N_on_L': cov / var if var else None,
                         'correlation': statistics.correlation([p[0] for p in pts], [p[1] for p in pts])}
    return {'G1_sign_agreement': by_split(agree), 'G1_regression': slopes,
            'G2_strong_london_followthrough_datr': by_split(g2), 'G3_sweep_direction_followthrough_datr': by_split(g3)}


def bitcoin():
    h1 = data.read('BTCUSD', 'H1')
    rets = [(b['utc'], b['close'] / a['close'] - 1) for a, b in zip(h1, h1[1:]) if b['utc'] - a['utc'] == 3600]
    out = {}
    for s in ('train', 'validation', 'test (exposed)'):
        r = [x for t, x in rets if split(t) == s]
        ab = [abs(x) for x in r]
        out.setdefault('B1_volatility_clustering', {})[s] = {'n': len(ab), 'lag1': statistics.correlation(ab[1:], ab[:-1]),
                                                            'lag24': statistics.correlation(ab[24:], ab[:-24])}
    rng_rows = {'weekend': [], 'weekday_us_cash': [], 'weekday_other': []}
    for b in h1:
        s = split(b['utc'])
        if not s:
            continue
        rngp = (b['high'] - b['low']) / b['close']
        wd = R.weekday(b['utc'])
        ny = b['utc'] - b['utc'] % 86400 + 9 * 3600 + 1800 - R.offset('US', b['utc'])
        key = 'weekend' if wd in (0, 6) else 'weekday_us_cash' if ny <= b['utc'] < ny + 6.5 * 3600 else 'weekday_other'
        rng_rows[key].append((b['utc'], rngp * 100))
    out['B2_mean_h1_range_pct'] = {k: by_split(v) for k, v in rng_rows.items()}
    shock = []
    for i in range(24 * 21, len(h1) - 4):
        b = h1[i]
        same = [x['high'] - x['low'] for x in h1[i - 24 * 20:i] if x['utc'] % 86400 == b['utc'] % 86400]
        if len(same) < 10:
            continue
        base = statistics.median(same)
        rngb = b['high'] - b['low']
        if base <= 0 or rngb < 3 * base or h1[i + 4]['utc'] - b['utc'] != 4 * 3600:
            continue
        atr = R.atr(h1[:i + 1], 24)
        sign = 1 if b['close'] >= b['open'] else -1
        shock.append((b['utc'], sign * (h1[i + 4]['close'] - b['close']) / atr))
    out['B3_post_shock_next4h_in_shock_direction_atr'] = by_split(shock)
    return out


def main():
    res = {'gold': gold(), 'bitcoin': bitcoin(), 'rules': __doc__}
    (HERE / 'intel_studies.json').write_text(json.dumps(res, indent=1, default=str))
    f = lambda d: ' | '.join(f"{k[:5]} n={v['n']} {v['mean']:+.3f}" + (f" [{v['ci95'][0]:+.3f},{v['ci95'][1]:+.3f}]" if 'ci95' in v else '') for k, v in d.items() if v.get('mean') is not None)
    g, b = res['gold'], res['bitcoin']
    print('G1 sign agreement :', f(g['G1_sign_agreement']))
    print('G1 regression     :', {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in g['G1_regression'].items()})
    print('G2 strong London  :', f(g['G2_strong_london_followthrough_datr']))
    print('G3 sweep follow   :', f(g['G3_sweep_direction_followthrough_datr']))
    print('B1 clustering     :', {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in b['B1_volatility_clustering'].items()})
    for k, v in b['B2_mean_h1_range_pct'].items():
        print('B2', k.ljust(16), f(v))
    print('B3 post-shock 4h  :', f(b['B3_post_shock_next4h_in_shock_direction_atr']))


if __name__ == '__main__':
    main()
