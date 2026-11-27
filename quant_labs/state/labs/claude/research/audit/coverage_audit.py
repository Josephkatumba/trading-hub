"""Signal coverage audit of the 16 live-monitored strategies (frozen-evaluator historical records).

Per strategy: trades/month; per instrument x UTC session: which strategies produce signals (coverage
gaps); pairwise overlap: share of a strategy's signals that coincide with another strategy's signal on the
same instrument and direction within 60 minutes (do several strategies detect the same opportunities?).
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze

LIVE = {('claude', 'index_trend_day', '0.1.0'), ('claude', 'crypto_trend_breakout', '0.3.0'), ('claude', 'hourly_shock_drift', '0.1.0'),
        ('claude', 'index_gap_fade', '0.1.0'), ('claude', 'index_turn_of_month', '0.1.0'), ('codex', 'compression_escape', '0.1.0'),
        ('codex', 'range_sweep_reversion', '0.1.0'), ('kimi', 'london_sweep_reversal', '0.2.0'), ('kimi', 'vol_exhaustion_fade', '0.2.0'),
        ('kimi', 'opening_range_drive', '0.2.0')} | {('codex', f'trend_reclaim_r{r}', '0.1.0') for r in (2, 3, 4, 5, 7, 9)}
MONTHS = 23.5
SESSIONS = ('Asia 00-07', 'London 07-12', 'Overlap 12-16', 'NY 16-24')


def session(t):
    h = datetime.fromtimestamp(t, timezone.utc).hour
    return SESSIONS[0] if h < 7 else SESSIONS[1] if h < 12 else SESSIONS[2] if h < 16 else SESSIONS[3]


def main():
    signals = defaultdict(list)
    for job in analyze.load():
        ident = (job['lab'], job['strategy'], job['version'])
        if ident in LIVE:
            for t in job['trades']:
                signals[ident[1]].append((t['plan']['symbol'], t['plan']['direction'], t['plan']['entry_at']))
    freq = {k: round(len(v) / MONTHS, 2) for k, v in sorted(signals.items(), key=lambda x: -len(x[1]))}
    grid = defaultdict(lambda: defaultdict(int))
    for k, v in signals.items():
        for sym, _, at in v:
            grid[(sym, session(at))][k] += 1
    instruments = sorted({sym for v in signals.values() for sym, _, _ in v} | {'XAUUSD', 'BTCUSD'})
    gaps = [f'{sym} {ses}' for sym in instruments for ses in SESSIONS if not grid.get((sym, ses))]
    gold_btc = {f'{sym} {ses}': dict(grid.get((sym, ses), {})) for sym in ('XAUUSD', 'BTCUSD') for ses in SESSIONS}
    overlap = {}
    keys = sorted(signals)
    for a in keys:
        for b in keys:
            if a >= b:
                continue
            sb = defaultdict(list)
            for sym, d, at in signals[b]:
                sb[(sym, d)].append(at)
            hits = sum(1 for sym, d, at in signals[a] if any(abs(at - x) <= 3600 for x in sb[(sym, d)]))
            share = hits / len(signals[a]) if signals[a] else 0
            if share >= 0.2:
                overlap[f'{a} ~ {b}'] = round(share, 2)
    out = {'trades_per_month': freq, 'total_trades_per_month_all_16': round(sum(freq.values()), 1),
           'approved_two_per_month': round(freq.get('index_trend_day', 0) + freq.get('crypto_trend_breakout', 0), 1),
           'coverage_gaps_instrument_session': gaps, 'gold_bitcoin_session_coverage': gold_btc,
           'pairs_with_20pct_plus_same_opportunity': dict(sorted(overlap.items(), key=lambda x: -x[1]))}
    (HERE / 'coverage_audit.json').write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ('trades_per_month', 'total_trades_per_month_all_16', 'approved_two_per_month')}, indent=1))
    print('gold/btc coverage:', {k: sum(v.values()) for k, v in gold_btc.items()})
    print('gaps:', len(gaps), gaps[:20])
    print('overlap pairs (>=20% same opportunity):', list(out['pairs_with_20pct_plus_same_opportunity'].items())[:20])


if __name__ == '__main__':
    main()
