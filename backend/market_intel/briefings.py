"""Category C: scheduled Gold & Bitcoin intelligence briefings (08:00 EAT morning, 15:00 EAT New York).

Preview mode by default: a briefing is generated and stored as PREVIEW. It is sent only with BOTH a
recorded CEO approval for the 'intel_briefings' category and TRADEDEN_INTEL_BRIEFINGS_TELEGRAM_ENABLED=1.
Quality rules: one record per slot per EAT day (no duplicates across restarts); a slot more than one hour
late (engine was off) is logged SKIPPED_LATE and never sent late; stale or closed markets are withheld,
never described; if nothing current remains the briefing is SKIPPED, not sent. EAT is UTC+3 all year;
session times inside the briefing are DST-aware.
"""
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from html import escape
from . import rules as R
from .live import intelligence, frames

EAT = timezone(timedelta(hours=3))
SLOTS = {'morning': (8, 0), 'new_york': (15, 0)}
FLAG = 'TRADEDEN_INTEL_BRIEFINGS_TELEGRAM_ENABLED'
ENABLED = 'TRADEDEN_INTEL_BRIEFINGS_ENABLED'
CATEGORY = 'intel_briefings'
LATE_SECONDS = 3600
SEND_MAX_AGE = 1800
CRYPTO = {'BTCUSD', 'ETHUSD'}


def hm(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime('%H:%M UTC')


def closed(symbol, now):
    from quant_live.health import market_closed
    return market_closed(symbol, now)


def session_times(now):
    day0 = now - now % 86400
    return {'london_open': day0 + 8 * 3600 - R.offset('UK', now), 'ny_open': day0 + 9 * 3600 + 1800 - R.offset('US', now),
            'london_close': day0 + 16 * 3600 + 1800 - R.offset('UK', now)}


def strategy_watch(store, now):
    """What the two approved signal strategies are waiting for, from live closed candles."""
    lines = []
    day0 = now - now % 86400
    us = day0 + 9 * 3600 + 1800 - R.offset('US', now) + 7200
    eu = day0 + 9 * 3600 - (R.offset('UK', now) + 3600) + 7200
    if R.weekday(now) not in (0, 6):
        lines.append(f"Index Trend-Day: decisions at {hm(eu)} (GER40) and {hm(us)} (NAS100, US500); needs a move of at least 0.45 daily ATR "
                     'from the cash open, closing in the outer quarter of the session range.')
    for sym in ('BTCUSD', 'ETHUSD'):
        f = frames(store, sym, now, {'H4': 160, 'D1': 60})
        h4, d1 = f['H4'], f['D1']
        if len(h4) < 121 or len(d1) < 55:
            lines.append(f'Crypto Trend Breakout {sym}: insufficient closed history in the live cache.')
            continue
        hi, lo = max(b['high'] for b in h4[-120:]), min(b['low'] for b in h4[-120:])
        c = [d['close'] for d in d1]
        base, base5 = sum(c[-50:]) / 50, sum(c[-55:-5]) / 50
        slope = 'rising' if base > base5 else 'falling'
        lines.append(f"Crypto Trend Breakout {sym}: BUY needs an H4 close above {hi:,.2f} with the 50-day baseline rising; "
                     f"SELL needs an H4 close below {lo:,.2f} with it falling (baseline currently {slope}).")
    return lines


def _section(intel, focus_gold=False):
    st, rg, sc, se = intel['structure'], intel['regime'], intel['scenarios'], intel['sessions']
    lv = lambda l: f"{l['name']} {l['price']:,.2f} ({l['event']})" if l else 'none'
    lines = [f"<b>{intel['symbol']}</b> {intel['price']:,.2f} · data to {intel['data_timestamp'][11:16]} UTC",
             f"Direction: D1 {st['D1']['state']} · H4 {st['H4']['state']} · H1 {st['H1']['state']} · M15 {st['M15']['state']}",
             f"Regime: {rg['trend']['state']} · volatility {rg['volatility']['state']} · range {rg['expansion']['state']}"
             + (' · volatility shock (cause unverified)' if rg.get('shock', {}).get('state') == 'SHOCK' else ''),
             f"Levels: above {lv(intel['nearest_resistance'])}; below {lv(intel['nearest_support'])}"]
    pd = [l for l in intel['levels'] if l['rule'] in ('L1', 'L4')]
    if pd:
        lines.append('Reference: ' + '; '.join(f"{l['name']} {l['price']:,.2f}" for l in pd))
    if se.get('asia'):
        lines.append(f"Asian range {se['asia']['low']:,.2f}-{se['asia']['high']:,.2f}" + ('' if se['asia']['complete'] else ' (forming)'))
    if focus_gold and se.get('london'):
        lines.append(f"London range before New York: {se['london']['low']:,.2f}-{se['london']['high']:,.2f}" + ('' if se['london']['complete'] else ' (forming)'))
        events = [l for l in intel['levels'] if l['event'] in ('SWEEP', 'FAILED', 'ACCEPTED')]
        lines.append('Liquidity events today: ' + ('; '.join(f"{l['name']} {l['event'].lower()}" for l in events) if events else 'none'))
    if 'macro' in intel:
        u = intel['macro']['usd_proxy']
        lines.append('USD proxy (broker FX basket, not DXY): ' + (f"{u['state']} {u['change_24h_pct']:+.2f}% 24h" if u['state'] != 'UNAVAILABLE' else 'unavailable'))
    if 'crypto' in intel:
        cr = intel['crypto']
        corr = cr['equity_correlation']
        lines.append(f"{'Weekend' if cr['weekend'] else 'Weekday'} · BTC-NAS100 hourly correlation: "
                     + (f"{corr['correlation']:+.2f}" if corr['state'] != 'UNAVAILABLE' else 'unavailable') + ' · funding/open interest: unavailable')
    lines += [f"Bullish if: {sc['bullish']['requires']}" + (' (met)' if sc['bullish']['currently_met'] else ''),
              f"Bearish if: {sc['bearish']['requires']}" + (' (met)' if sc['bearish']['currently_met'] else ''),
              'Caution: ' + ('; '.join(sc['neutral']['reasons']) or 'none')]
    return [escape(x).replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>') for x in lines]


def compose(kind, store, quotes, now):
    """Returns (state, text). state is READY or a SKIPPED_* reason; text is the briefing or the reason."""
    when = datetime.fromtimestamp(now, EAT).strftime('%a %d %b %H:%M EAT')
    st = session_times(now)
    symbols = ['XAUUSD', 'BTCUSD'] if kind == 'morning' else ['XAUUSD']
    if kind == 'new_york' and closed('XAUUSD', now):
        return 'SKIPPED_MARKET_CLOSED', 'Gold market closed (weekend): New York briefing not generated.'
    title = '🌅 <b>TRADEDEN MORNING BRIEFING</b>' if kind == 'morning' else '🗽 <b>TRADEDEN NEW YORK SESSION BRIEFING</b>'
    lines = [title + ' · Gold & Bitcoin intelligence', when + ' · market analysis only, not trade signals', '']
    current = 0
    for sym in symbols:
        if closed(sym, now):
            lines += [f'<b>{sym}</b>: market closed (weekend), no analysis presented.', '']
            continue
        intel = intelligence(store, sym, (quotes or {}).get(sym), now)
        if intel['stale'] or intel['price'] is None:
            lines += [f"<b>{sym}</b>: data stale or unavailable (last data {intel['data_timestamp']}); analysis withheld.", '']
            continue
        current += 1
        lines += _section(intel, focus_gold=(sym == 'XAUUSD' and kind == 'new_york')) + ['']
    if current == 0:
        return 'SKIPPED_STALE_DATA', 'No current market data for the briefing; nothing sent.'
    lines.append(f"Sessions today: London opens {hm(st['london_open'])} · New York {hm(st['ny_open'])} · London close {hm(st['london_close'])}")
    if kind == 'new_york':
        lines.append('Upcoming economic releases: unavailable (no authoritative calendar connected; none inferred).')
    lines += ['', '<b>What our approved strategies are waiting for</b>'] + [escape(x) for x in strategy_watch(store, now)]
    lines.append('Gold: no approved signal strategy; research models are monitored internally (observations in preview).' if kind == 'new_york' else '')
    lines += ['', 'ℹ️ Intelligence only. No entry, stop-loss or take-profit is implied. Experimental research platform.']
    return 'READY', '\n'.join(l for l in lines if l is not None)


def slot_time(name, now):
    eat = datetime.fromtimestamp(now, EAT)
    h, m = SLOTS[name]
    return eat.replace(hour=h, minute=m, second=0, microsecond=0).timestamp(), eat.date().isoformat()


def flag_on():
    return os.getenv(FLAG, '').strip() == '1'


def run_due(store, quotes=None, now=None):
    """Record (and, if approved, queue) every due slot of today's EAT date. Returns recorded ids."""
    now = time.time() if now is None else now
    live = bool(store.category_approval(CATEGORY) and flag_on())
    recorded = []
    for name in SLOTS:
        at, day = slot_time(name, now)
        if now < at:
            continue
        nid = f'brief:{name}:{day}'
        if any(r['id'] == nid for r in store.notifications(CATEGORY, 20)):
            continue
        if now - at > LATE_SECONDS:
            state, text = 'SKIPPED_LATE', f'Engine was not running at {datetime.fromtimestamp(at, EAT):%H:%M} EAT; briefing not sent late.'
        else:
            state, text = compose(name, store, quotes, now)
            if state == 'READY':
                state = 'QUEUED' if live else 'PREVIEW'
        if store.notify_record(nid, CATEGORY, f'{name}:{day}', state, text, {'slot': name, 'slot_at': at, 'live_at_record': live}, now):
            recorded.append(nid)
    from quant_live.research_observations import deliver_category
    deliver_category(store, CATEGORY, live, SEND_MAX_AGE, now=now)
    return recorded


def next_slots(now=None):
    now = time.time() if now is None else now
    out = []
    for name in SLOTS:
        at, _ = slot_time(name, now)
        out.append({'briefing': name, 'at': (at if at > now else at + 86400)})
    return sorted(out, key=lambda x: x['at'])


def run_loop(stop, poll=30):
    """Engine thread (enabled by TRADEDEN_INTEL_BRIEFINGS_ENABLED=1)."""
    from quant_live import service
    while not stop.is_set():
        try:
            quotes = {s: (i or {}).get('quote') for s, i in (service.status().get('latest_inputs') or {}).items()}
            run_due(service.store(), quotes)
        except Exception:
            import logging
            logging.getLogger('trading_hub.intel_briefings').exception('Briefing cycle failed')
        stop.wait(poll)


def start(stop):
    if os.getenv(ENABLED, '').strip() != '1':
        return None
    t = threading.Thread(target=run_loop, args=(stop,), name='tradeden-intel-briefings', daemon=True)
    t.start()
    return t
