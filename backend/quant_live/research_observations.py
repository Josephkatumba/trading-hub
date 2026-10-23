"""Category B: Quant Labs research observations (never qualified trading signals).

For live, real-time setups from models OUTSIDE the experimental signal approval, builds a message
labelled 'RESEARCH OBSERVATION: NOT A QUALIFIED TRADING SIGNAL' with the detected condition,
directional hypothesis, historical evidence and its limitations, regime and timestamp. It never
includes entry, stop-loss or take-profit, even though the model computed them internally.

Delivery requires BOTH a recorded CEO approval for the 'research_observations' category and
TRADEDEN_RESEARCH_OBSERVATIONS_TELEGRAM_ENABLED=1; otherwise observations are stored as PREVIEW.
"""
import os
import time
from datetime import datetime, timezone, timedelta
from html import escape
from .telegram import RESEARCHERS, REGIMES, throttle, transport_from_env

CATEGORY = 'research_observations'
FLAG = 'TRADEDEN_RESEARCH_OBSERVATIONS_TELEGRAM_ENABLED'
MAX_RECORD_AGE = 900      # only observations detected in the last 15 minutes are recorded (no replay after downtime)
MAX_SEND_AGE = 600
EAT = timezone(timedelta(hours=3))


def flag_on():
    return os.getenv(FLAG, '').strip() == '1'


def evidence_row(lab, key, version):
    """Category and historical evidence for one model (light: no diagnostics scan)."""
    from .leaderboard import _load, historical
    cats, evidence = _load('leaderboard_categories.json') or {}, _load('evidence.json')
    ident = f'{lab}:{key}@{version}'
    source = cats.get('evidence_aliases', {}).get(ident, ident)
    s_lab, rest = source.split(':', 1)
    s_key, s_version = rest.split('@')
    cat = cats.get('models', {}).get(f'{lab}:{key}', {'category': 'UNCLASSIFIED', 'label': 'Not yet audited'})
    return {'category': cat['category'], 'category_label': cat['label'], 'historical': historical(evidence, s_lab, s_key, s_version)}


def evidence_line(row):
    if not row:
        return 'Historical evidence: not audited.'
    h = (row.get('historical') or {}).get('test') or {}
    exp = 'n/a' if h.get('net_expectancy_r') is None else f"{h['net_expectancy_r']:+.2f}R per trade over {h.get('n', 0)} trades"
    return (f"Historical evidence: Category {row['category']}: {row['category_label']}. Test split {exp}"
            + (' (small sample)' if h.get('insufficient_sample') else '') + '. Previously exposed data; not a validated edge.')


def message(s, row, historical_record=None):
    at = datetime.fromtimestamp(s['entry_at'], timezone.utc)
    head = '🔎 <b>RESEARCH OBSERVATION: NOT A QUALIFIED TRADING SIGNAL</b>'
    if historical_record:
        head += '\n📼 <b>HISTORICAL RESEARCH RECORD (preview example), not a live detection</b>'
    lines = [head,
             '📊 Instrument: ' + escape(s['symbol']),
             '🧠 Strategy: ' + escape(s['model_name']) + ' v' + escape(s['model_version']),
             '🤖 Researcher: ' + RESEARCHERS.get(s['lab'], escape(s['lab'])),
             '🧭 Detected condition: ' + escape(str(s.get('rationale') or 'The model supplied no description.')),
             '↕️ Directional hypothesis: ' + ('price higher' if s['direction'] == 'LONG' else 'price lower') + ' (hypothesis under research, not a recommendation)',
             '📚 ' + escape(evidence_line(row)),
             '🌡️ Market regime: ' + escape(REGIMES.get(s.get('regime_at_entry'), 'not recorded')),
             '🕒 ' + at.strftime('%Y-%m-%d %H:%M UTC') + ' / ' + at.astimezone(EAT).strftime('%H:%M EAT'),
             '⚠️ No entry, stop-loss or take-profit is provided. Research only; do not trade on this.']
    return '\n'.join(lines)


def collect(store, now=None, rows_by_key=None):
    """Record observations for fresh, real-time setups from non-approved models. Returns new ids."""
    now = time.time() if now is None else now
    approval = store.delivery_approval() or {}
    approved = {(i['lab'], i['key'], i['version']) for i in approval.get('scope', [])}
    obs_approval = store.category_approval(CATEGORY) or {}
    live = bool(obs_approval and flag_on())
    # Optional per-model scope in the category approval: only listed models are queued; others stay PREVIEW.
    allowed = {(i['lab'], i['key']) for i in obs_approval.get('scope', [])} if obs_approval.get('scope') else None
    if rows_by_key is None:
        rows_by_key = {}
    new = []
    for s in store.signals(200):
        ident = (s['lab'], s['model_key'], s['model_version'])
        if ident in approved or s.get('detection') != 'REAL_TIME' or not s.get('direction'):
            continue
        nid = 'obs:' + s['signal_id']
        fresh = now - s['entry_at'] <= MAX_RECORD_AGE
        in_scope = allowed is None or (s['lab'], s['model_key']) in allowed
        state = ('QUEUED' if live and in_scope else 'PREVIEW') if fresh else 'SKIPPED_STALE'
        if ident not in rows_by_key:
            rows_by_key[ident] = evidence_row(*ident)
        if store.notify_record(nid, CATEGORY, s['signal_id'], state, message(s, rows_by_key.get(ident)),
                               {'symbol': s['symbol'], 'model': s['model_key'], 'live_at_record': live}, now):
            new.append(nid)
    return new


def deliver(store, transport=None, chat=None, now=None, sleep=time.sleep):
    """Send QUEUED notifications of this category once (QUEUED -> IN_FLIGHT -> SENT/FAILED/DELIVERY_UNKNOWN)."""
    return deliver_category(store, CATEGORY, bool(store.category_approval(CATEGORY) and flag_on()), MAX_SEND_AGE, transport, chat, now, sleep)


def deliver_category(store, category, live, max_age, transport=None, chat=None, now=None, sleep=time.sleep):
    now = time.time() if now is None else now
    sent = 0
    for row in reversed(store.notifications(category)):
        if row['state'] != 'QUEUED':
            continue
        if not live:
            store.notify_transition(row['id'], 'QUEUED', 'PREVIEW', {'reason': 'approval or flag withdrawn before delivery'}, now)
            continue
        if now - row['created'] > max_age:
            store.notify_transition(row['id'], 'QUEUED', 'EXPIRED', {'reason': 'too old to send'}, now)
            continue
        if transport is None:
            transport, chat = transport_from_env()
            if transport is None:
                store.notify_transition(row['id'], 'QUEUED', 'PREVIEW', {'reason': 'TELEGRAM_NOT_CONFIGURED'}, now)
                continue
        if not store.notify_transition(row['id'], 'QUEUED', 'IN_FLIGHT', {}, now):
            continue
        throttle(sleep)
        try:
            result = None
            for chunk in chunks(row['message']):
                result = transport.send_message(chat, chunk, parse_mode='HTML')
        except Exception as exc:
            status = getattr(exc, 'status', None)
            store.notify_transition(row['id'], 'IN_FLIGHT', 'DELIVERY_UNKNOWN' if status is None else 'FAILED', {'error': str(exc)[:300], 'status': status}, time.time())
            continue
        store.notify_transition(row['id'], 'IN_FLIGHT', 'SENT', {'message_id': (result or {}).get('message_id'), 'sent_at': time.time()}, time.time())
        sent += 1
    return sent


def chunks(text, size=3900):
    out, cur = [], ''
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > size:
            out.append(cur)
            cur = ''
        cur += line
    return out + ([cur] if cur else [])
