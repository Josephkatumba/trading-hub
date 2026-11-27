"""Offline quality overlay. Never imported by live workers; no IO or delivery.

Policy thresholds are conservative research hypotheses, not fitted edge estimates.
Input timestamps are UTC bar opens; spreads and prices use instrument price units.
"""
from math import isfinite
from market_intel.engine import build
from market_intel.rules import TF, atr

VERSION = 'intelligence-quality-preview-2'
REQUIRED = {'M15': 60, 'H1': 60, 'H4': 60, 'D1': 60}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def evaluate(symbol, frames, quote, now, *, max_spread_atr=0.10, calendar=None):
    """Return analysis plus explicit blockers, never a qualified signal.

    History after the cutoff is ignored. Malformed/duplicate/unordered observed
    bars block analysis rather than silently repairing uncertain chronology.
    Gaps are unclassified: weekends are not proof of missing broker data.
    """
    if symbol not in ('XAUUSD', 'BTCUSD'):
        raise ValueError('only XAUUSD and BTCUSD are supported')
    if not number(now) or now <= 0:
        raise ValueError('now must be a positive UTC epoch')
    if not number(max_spread_atr) or max_spread_atr <= 0:
        raise ValueError('max_spread_atr must be positive')
    clean, quality, blockers = {}, {}, []
    malformed = False
    for tf, minimum in REQUIRED.items():
        bars, errors, previous = [], [], None
        for row in frames.get(tf, []):
            if not isinstance(row, dict) or not number(row.get('utc')):
                errors.append('invalid timestamp')
                continue
            close_at = calendar.close_at(row['utc'],tf) if calendar else row['utc'] + TF[tf]
            if close_at is None:
                errors.append('ambiguous broker clock boundary')
                continue
            if close_at > now:
                continue
            if calendar and not calendar.aligned(row['utc'],tf):
                errors.append('misaligned broker timeframe')
            if row['utc'] < 0 or (previous is not None and row['utc'] <= previous):
                errors.append('duplicate or unordered timestamp')
            previous = row['utc']
            if not all(number(row.get(k)) and row[k] > 0 for k in ('open', 'high', 'low', 'close')):
                errors.append('invalid OHLC')
                continue
            if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
                errors.append('inconsistent OHLC')
                continue
            bars.append(dict(row))
        recent = bars[-minimum:]
        gaps = sum(b['utc'] - a['utc'] != TF[tf] for a, b in zip(recent, recent[1:]))
        age = now - bars[-1]['utc'] - TF[tf] if bars else None
        quality[tf] = {'closed_bars': len(bars), 'required_bars': minimum,
                       'last_close_age_seconds': age, 'recent_unclassified_gaps': gaps,
                       'errors': sorted(set(errors))}
        coverage = calendar.gaps(symbol, recent, tf, now) if calendar else None
        if coverage:
            quality[tf]['calendar_coverage'] = coverage
        if errors:
            malformed = True
            blockers.append(f'{tf}: invalid observed history')
        if len(bars) < minimum:
            blockers.append(f'{tf}: insufficient history')
        if (coverage['stale'] if coverage else age is None or age > TF[tf]):
            blockers.append(f'{tf}: stale or absent history')
        if coverage and coverage['unexpected_missing']:
            blockers.append(f'{tf}: missing expected broker candles')
        elif gaps and not calendar:
            blockers.append(f'{tf}: recent gaps require session-calendar verification')
        clean[tf] = bars
    valid_quote = isinstance(quote, dict) and all(number(quote.get(k)) for k in ('bid', 'ask', 'tick_at'))
    if valid_quote:
        valid_quote = 0 < quote['bid'] <= quote['ask'] and 0 <= now - quote['tick_at'] <= 120
    if not valid_quote:
        blockers.append('missing, invalid, stale or future quote')
    market_state = calendar.state(symbol, now) if calendar else 'UNKNOWN'
    if calendar and market_state != 'SCHEDULED_OPEN':
        blockers.append('broker market state: '+market_state)
    h1_atr = atr(clean['H1'], 24) if len(clean['H1']) >= 25 else None
    ratio = (quote['ask'] - quote['bid']) / h1_atr if valid_quote and h1_atr and h1_atr > 0 else None
    if ratio is None:
        blockers.append('spread-to-ATR unavailable')
    elif ratio > max_spread_atr:
        blockers.append('spread exceeds research ATR threshold')
    # Optional macro/exchange context is deliberately absent, not synthesized.
    analysis = None if malformed else build(symbol, clean, quote if valid_quote else None, now)
    if analysis:
        blockers.extend(analysis['scenarios']['neutral']['reasons'])
        if analysis['structure']['H4']['state'] == 'UNAVAILABLE':
            blockers.append('H4 context unavailable')
        for direction in ('bullish', 'bearish'):
            analysis['scenarios'][direction]['currently_met'] &= not bool(blockers)
    return {'version': VERSION, 'symbol': symbol, 'evaluated_at': now,
            'market_state': market_state,
            'calendar_authority': calendar.profile['authority'] if calendar else 'UNAVAILABLE',
            'quote_state': ('FRESH' if valid_quote else 'UNAVAILABLE_OR_STALE'),
            'status': 'BLOCKED' if blockers else 'CONTEXT_ONLY',
            'opportunity': 'NO QUALIFIED OPPORTUNITY', 'qualified': False,
            'blockers': sorted(set(blockers)), 'data_quality': quality,
            'execution': {'spread_to_h1_atr': ratio, 'max_spread_atr': max_spread_atr,
                          'cost_model': 'quote spread diagnostic only; commission/slippage/financing not estimated'},
            'provenance': {'price': 'MT5 broker bid/ask', 'volume': 'not used; broker tick activity is not consolidated volume',
                           'order_flow': 'unavailable', 'macro_calendar': 'unavailable'},
            'analysis': analysis, 'production_enabled': False}
