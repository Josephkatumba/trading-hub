"""Compose explainable XAUUSD / BTCUSD intelligence from closed candles (+ optional context).

build() is pure: it receives frames (closed candles only), a quote, the evaluation time and
optional context (USD proxy inputs, NAS100 H1 for BTC, live strategy observations). It never
produces entry, stop or target levels.
"""
from datetime import datetime, timezone
from . import rules as R

SYMBOLS = {'XAUUSD': 'Gold', 'BTCUSD': 'Bitcoin'}
USD_PAIRS = {'EURUSD': -1, 'GBPUSD': -1, 'AUDUSD': -1, 'NZDUSD': -1, 'USDJPY': 1, 'USDCHF': 1, 'USDCAD': 1}
UNAVAILABLE_MACRO = {
    'us_treasury_yields': 'No Treasury yield instrument in the broker feed; no authoritative feed connected.',
    'real_yield_proxy': 'Requires nominal yields and inflation expectations; neither is connected.',
    'economic_calendar': 'No authoritative timestamped calendar (Fed, BLS CPI/NFP) connected; events are not inferred from price.',
    'geopolitical_risk': 'No verified news source connected.',
}
UNAVAILABLE_CRYPTO = {
    'funding_rates': 'No trusted funding-rate source connected.',
    'open_interest': 'No trusted open-interest source connected.',
    'liquidations': 'No liquidation data source connected; not inferred from candle shapes.',
    'spot_perp_divergence': 'Only the broker CFD price is available.',
}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None


def closed(bars, tf, now):
    return [b for b in bars or [] if b['utc'] + R.TF[tf] <= now]


def usd_proxy(fx_h1, now):
    """Equal-weight 24h USD change across available USD pairs (sign-adjusted). A proxy, not the DXY."""
    moves, used = [], []
    for pair, sign in USD_PAIRS.items():
        bars = closed(fx_h1.get(pair), 'H1', now)
        if len(bars) >= 25 and now - (bars[-1]['utc'] + 3600) <= 2 * 3600:
            moves.append(sign * (bars[-1]['close'] / bars[-25]['close'] - 1))
            used.append(pair)
    if len(used) < 4:
        return {'state': 'UNAVAILABLE', 'reason': f'only {len(used)} fresh USD pairs'}
    avg = sum(moves) / len(moves)
    return {'state': 'USD_STRONGER' if avg > 0.002 else 'USD_WEAKER' if avg < -0.002 else 'USD_FLAT', 'change_24h_pct': avg * 100,
            'pairs': used, 'note': 'Equal-weight broker FX proxy, not the DXY; 24 closed H1 candles.'}


def equity_correlation(btc_h1, nas_h1, now, n=120):
    a = {b['utc']: b['close'] for b in closed(btc_h1, 'H1', now)}
    b = {x['utc']: x['close'] for x in closed(nas_h1, 'H1', now)}
    common = sorted(set(a) & set(b))
    pairs = [(a[t2] / a[t1] - 1, b[t2] / b[t1] - 1) for t1, t2 in zip(common, common[1:]) if t2 - t1 == 3600][-n:]
    if len(pairs) < 40:
        return {'state': 'UNAVAILABLE', 'reason': f'{len(pairs)} synchronised hourly returns (< 40)'}
    from statistics import correlation
    rho = correlation([p[0] for p in pairs], [p[1] for p in pairs])
    return {'state': 'POSITIVE' if rho >= 0.3 else 'NEGATIVE' if rho <= -0.3 else 'WEAK', 'correlation': rho, 'hours': len(pairs),
            'note': 'BTCUSD vs NAS100 synchronised H1 returns; correlations are unstable over time.'}


def build(symbol, frames, quote, now, context=None):
    context = context or {}
    m15, h1, h4, d1 = (closed(frames.get(tf), tf, now) for tf in ('M15', 'H1', 'H4', 'D1'))
    last_close_at = max((b['utc'] + R.TF[tf] for tf, bs in (('M15', m15), ('H1', h1)) for b in bs[-1:]), default=None)
    quote_age = now - quote['tick_at'] if quote and quote.get('tick_at') else None
    stale = last_close_at is None or now - last_close_at > 1800 or (quote_age is not None and quote_age > 120)
    price = quote.get('bid') if quote else (m15[-1]['close'] if m15 else None)
    trend = {tf: R.trend(bs) for tf, bs in (('D1', d1), ('H4', h4), ('H1', h1))}
    days, today = R.broker_days(h1, now)
    pd = days[-1] if days else None
    pw = R.previous_week(days)
    sh, sl = R.swings(h4)
    sess = R.sessions(m15, now)
    today_m15 = [b for b in m15 if today and b['utc'] >= today['start']]
    levels = []
    def add(name, value, level_type, rule, after=None, forming=False):
        if value is None:
            return
        side = 'above' if level_type == 'high' else 'below'
        after = max(after or 0, today['start'] if today else 0)
        event = {'event': 'FORMING'} if forming else R.level_event([b for b in today_m15 if b['utc'] >= after], value, side)
        levels.append({'name': name, 'price': value, 'level_type': level_type, 'rule': rule, 'events_from': iso(after), **event})
    if pd:
        add('Previous day high', pd['high'], 'high', 'L1')
        add('Previous day low', pd['low'], 'low', 'L1')
    if pw:
        add('Previous week high', pw['high'], 'high', 'L2')
        add('Previous week low', pw['low'], 'low', 'L2')
    for key, label in (('asia', 'Asian'), ('london', 'London')):
        sr = sess.get(key)
        if sr:
            add(f'{label} high', sr['high'], 'high', 'S1', sr['ends_at'], not sr['complete'])
            add(f'{label} low', sr['low'], 'low', 'S1', sr['ends_at'], not sr['complete'])
    for sw in sh[-3:]:
        add('H4 swing high', sw['price'], 'high', 'L3', sw['at'] + 3 * R.TF['H4'])
    for sw in sl[-3:]:
        add('H4 swing low', sw['price'], 'low', 'L3', sw['at'] + 3 * R.TF['H4'])
    d20 = [d for d in d1 if d['utc'] + 86400 <= now][-20:]
    if len(d20) == 20:
        add('20-day high', max(d['high'] for d in d20), 'high', 'L4')
        add('20-day low', min(d['low'] for d in d20), 'low', 'L4')
    regime = R.regime(h1, days, today)
    above = sorted((l for l in levels if price is not None and l['price'] > price), key=lambda l: l['price'])
    below = sorted((l for l in levels if price is not None and l['price'] < price), key=lambda l: -l['price'])
    resistance, support = (above[0] if above else None), (below[0] if below else None)
    missing = [] + (['stale data'] if stale else [])
    missing += [f'{tf} trend: {t.get("reason")}' for tf, t in trend.items() if t['state'] == 'UNAVAILABLE']
    conflicts = []
    if {trend['D1']['state'], trend['H4']['state']} == {'UP', 'DOWN'}:
        conflicts.append('D1 and H4 trends point in opposite directions')
    # Scenarios (C1-C3): conditions, not trades.
    h1_last = h1[-1]['close'] if h1 else None
    lowest = min(levels, key=lambda l: l['price']) if levels else None
    highest = max(levels, key=lambda l: l['price']) if levels else None
    up_ref = resistance or highest   # with no level above, the highest level is the reference already exceeded
    dn_ref = support or lowest       # with no level below, the lowest level is the reference already broken
    def scenario(rule, ref, above, blocked_trend):
        if not ref or h1_last is None:
            return {'rule': rule, 'requires': 'no reference level identified', 'currently_met': False}
        word, cmp = ('above', h1_last > ref['price']) if above else ('below', h1_last < ref['price'])
        beyond_all = (above and ref is highest and not resistance) or (not above and ref is lowest and not support)
        return {'rule': rule, 'reference': ref['name'], 'reference_price': ref['price'],
                'requires': f"H1 close {word} {ref['name']} {ref['price']:.2f} with H4 trend not {blocked_trend}"
                            + (' (price is already beyond every reference level)' if beyond_all else ''),
                'currently_met': bool(cmp and trend['H4']['state'] != blocked_trend)}
    bull = scenario('C1', up_ref, True, 'DOWN')
    bear = scenario('C2', dn_ref, False, 'UP')
    avoid = []
    if regime['trend']['state'] == 'RANGING' and pd and price is not None and pd['low'] <= price <= pd['high']:
        avoid.append('H1 regime RANGING and price inside the previous-day range')
    if conflicts:
        avoid.extend(conflicts)
    if regime.get('shock', {}).get('state') == 'SHOCK':
        avoid.append('volatility shock in the last closed H1 candle (cause not verified)')
    if stale:
        avoid.append('market data is stale')
    neutral = {'rule': 'C3', 'avoid_directional_trades': bool(avoid), 'reasons': avoid}
    explain = [
        {'conclusion': f"Structure D1 {trend['D1']['state']}, H4 {trend['H4']['state']}, H1 {trend['H1']['state']}", 'rules': ['T1'],
         'observations': {tf: {k: t.get(k) for k in ('close', 'ema20', 'ema50', 'ema50_5_ago')} for tf, t in trend.items()},
         'data_timestamp': iso(last_close_at), 'missing': [m for m in missing if 'trend' in m], 'conflicts': conflicts},
        {'conclusion': f"Regime {regime['trend']['state']} / volatility {regime['volatility']['state']} / range {regime['expansion']['state']}",
         'rules': ['R1', 'R2', 'R3', 'R4'], 'observations': regime, 'data_timestamp': iso(last_close_at),
         'missing': [k for k, v in regime.items() if v.get('state') == 'UNAVAILABLE'], 'conflicts': []},
        {'conclusion': f"Session: {sess['current']}", 'rules': ['S1', 'S2'], 'observations': sess, 'data_timestamp': iso(last_close_at),
         'missing': [k for k in ('asia', 'london', 'new_york') if not sess.get(k)], 'conflicts': []}]
    out = {'symbol': symbol, 'name': SYMBOLS.get(symbol, symbol), 'evaluated_at': iso(now), 'price': price, 'price_source': 'live bid quote' if quote else 'last closed M15 close',
           'data_timestamp': iso(last_close_at), 'quote_age_seconds': quote_age, 'stale': stale,
           'structure': trend, 'levels': levels, 'nearest_resistance': resistance, 'nearest_support': support,
           'sessions': sess, 'regime': regime, 'scenarios': {'bullish': bull, 'bearish': bear, 'neutral': neutral},
           'explanations': explain, 'strategy_observations': context.get('strategy_observations', []),
           'rules': R.RULES, 'not_a_signal': 'Market analysis only. No entry, stop-loss or take-profit is implied.'}
    if symbol == 'XAUUSD':
        out['macro'] = {'usd_proxy': usd_proxy(context.get('fx_h1', {}), now), **{k: {'state': 'UNAVAILABLE', 'reason': v} for k, v in UNAVAILABLE_MACRO.items()}}
    if symbol == 'BTCUSD':
        out['crypto'] = {'weekend': sess['weekend'],
                         'us_cash_session_open': sess['current'] in ('New York', 'London/New York overlap'),
                         'equity_correlation': equity_correlation(h1, context.get('nas100_h1', []), now),
                         **{k: {'state': 'UNAVAILABLE', 'reason': v} for k, v in UNAVAILABLE_CRYPTO.items()}}
    return out


def render_telegram(intel):
    """Internal preview text (not scheduled, not sent)."""
    f = lambda v: '—' if v is None else f'{v:,.2f}'
    st, rg, sc = intel['structure'], intel['regime'], intel['scenarios']
    lines = [f"🧭 <b>{intel['symbol']} MARKET INTELLIGENCE</b> · internal preview",
             f"Price {f(intel['price'])} ({intel['price_source']}) · data to {intel['data_timestamp']}" + (' · ⚠️ STALE' if intel['stale'] else ''),
             f"Structure: D1 {st['D1']['state']} · H4 {st['H4']['state']} · H1 {st['H1']['state']}",
             f"Regime: {rg['trend']['state']} · volatility {rg['volatility']['state']} · range {rg['expansion']['state']}"
             + (' · ⚠️ volatility shock (cause unverified)' if rg.get('shock', {}).get('state') == 'SHOCK' else ''),
             f"Session: {intel['sessions']['current']}"]
    nvl = intel['sessions'].get('ny_vs_london')
    if nvl:
        lines.append(f"New York vs London: took high {'yes' if nvl['took_london_high'] else 'no'}, took low {'yes' if nvl['took_london_low'] else 'no'}, last close {nvl['last_close_vs_london']} the London range")
    r, s = intel['nearest_resistance'], intel['nearest_support']
    lines.append(f"Nearest level above (resistance): {r['name']} {f(r['price'])} ({r['event']})" if r else 'Nearest level above: none (price above all reference levels)')
    lines.append(f"Nearest level below (support): {s['name']} {f(s['price'])} ({s['event']})" if s else 'Nearest level below: none (price below all reference levels)')
    if 'macro' in intel:
        u = intel['macro']['usd_proxy']
        lines.append('USD proxy (broker FX basket, not DXY): ' + (f"{u['state']} {u['change_24h_pct']:+.2f}% 24h" if u['state'] != 'UNAVAILABLE' else 'unavailable'))
        lines.append('Yields, real yields, economic calendar, geopolitics: unavailable (no authoritative feed connected)')
    if 'crypto' in intel:
        c = intel['crypto']['equity_correlation']
        lines.append(f"Weekend: {'yes' if intel['crypto']['weekend'] else 'no'} · US cash session: {'open' if intel['crypto']['us_cash_session_open'] else 'closed'}")
        lines.append('BTC vs NAS100 (H1): ' + (f"{c['state']} r={c['correlation']:+.2f} over {c['hours']}h" if c['state'] != 'UNAVAILABLE' else 'unavailable'))
        lines.append('Funding, open interest, liquidations: unavailable (no trusted source connected)')
    lines += ['', '<b>Scenarios (conditions, not trades)</b>',
              f"🟢 Bullish if: {sc['bullish']['requires']}" + (' · MET' if sc['bullish']['currently_met'] else ''),
              f"🔴 Bearish if: {sc['bearish']['requires']}" + (' · MET' if sc['bearish']['currently_met'] else ''),
              '⚪ Caution: ' + ('; '.join(sc['neutral']['reasons']) if sc['neutral']['reasons'] else 'no avoid-conditions active')]
    obs = intel.get('strategy_observations') or []
    lines.append('Active qualifying strategy setups: ' + (', '.join(o['summary'] for o in obs) if obs else 'none'))
    lines.append('ℹ️ Analysis only; no entry, stop-loss or take-profit implied.')
    return '\n'.join(lines)
