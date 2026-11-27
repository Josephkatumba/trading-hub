"""Telegram Intelligence Center: one read-only view of all three notification categories.

A: qualified experimental signals (existing approval), B: research observations, C: Gold/BTC
intelligence briefings. Each has independent approval, flag and delivery state. Approvals are
recorded only through the owner CLI; this view never changes anything.
"""
import os
import time
from .telegram import delivery_enabled

STORE_ARG = '--store data/quant_live'
CONTROLS = {
    'qualified_signals': {'approve': f'python -m quant_live {STORE_ARG} approve-delivery --approval <approval.json>',
                          'revoke': f'python -m quant_live {STORE_ARG} revoke-delivery --reason "<why>"',
                          'flag': 'TRADEDEN_QUANT_LIVE_TELEGRAM_ENABLED=1 in backend/.env (engine restart)'},
    'research_observations': {'approve': f'python -m quant_live {STORE_ARG} approve-category --category research_observations --approval <approval.json>',
                              'revoke': f'python -m quant_live {STORE_ARG} revoke-category --category research_observations --reason "<why>"',
                              'flag': 'TRADEDEN_RESEARCH_OBSERVATIONS_TELEGRAM_ENABLED=1 in backend/.env (engine restart)'},
    'intel_briefings': {'approve': f'python -m quant_live {STORE_ARG} approve-category --category intel_briefings --approval <approval.json>',
                        'revoke': f'python -m quant_live {STORE_ARG} revoke-category --category intel_briefings --reason "<why>"',
                        'flag': 'TRADEDEN_INTEL_BRIEFINGS_TELEGRAM_ENABLED=1 in backend/.env (engine restart); preview generation: TRADEDEN_INTEL_BRIEFINGS_ENABLED=1'},
}


def center(store, runtime, now=None, intel_fn=None):
    now = time.time() if now is None else now
    from .research_observations import flag_on as obs_flag
    from market_intel.briefings import flag_on as brief_flag, next_slots, ENABLED as BRIEF_ENABLED
    from .health import health
    approval = store.delivery_approval() or {}
    scope = {(i['lab'], i['key'], i['version']) for i in approval.get('scope', [])}
    outbox = store.outbox()
    sent_signals = [r for r in outbox if r['state'] == 'SENT']
    notes = store.notifications(None, 500)
    by_cat = lambda c: [n for n in notes if n['category'] == c]
    failures = lambda rows: sum(1 for r in rows if r['state'] in ('FAILED', 'DELIVERY_UNKNOWN') and now - r['updated'] <= 86400)
    last = lambda rows: max((r['updated'] for r in rows if r['state'] == 'SENT'), default=None)
    models = [m for m in store.models() if m['status'] == 'EXPERIMENTAL' and m['scan_enabled']]
    obs_approved, brief_approved = store.category_approval('research_observations'), store.category_approval('intel_briefings')
    cats = {
        'qualified_signals': {'label': 'A · Qualified experimental signals', 'approved': bool(approval), 'approved_by': approval.get('approved_by'),
                              'flag': delivery_enabled(), 'mode': 'LIVE' if approval and delivery_enabled() else 'DRY_RUN',
                              'strategies': [f"{m['manifest']['name']} v{m['version']}" for m in models if (m['lab'], m['key'], m['version']) in scope],
                              'last_sent': last(outbox), 'sent_total': len(sent_signals), 'failures_24h': failures(outbox), 'controls': CONTROLS['qualified_signals']},
        'research_observations': {'label': 'B · Research observations (not trading signals)', 'approved': bool(obs_approved), 'flag': obs_flag(),
                                  'mode': 'LIVE' if obs_approved and obs_flag() else 'PREVIEW',
                                  'strategies': [f"{m['manifest']['name']} v{m['version']} ({m['lab']})" for m in models if (m['lab'], m['key'], m['version']) not in scope],
                                  'previews': sum(1 for n in by_cat('research_observations') if n['state'] == 'PREVIEW'),
                                  'latest': (by_cat('research_observations') or [None])[0], 'last_sent': last(by_cat('research_observations')),
                                  'failures_24h': failures(by_cat('research_observations')), 'controls': CONTROLS['research_observations']},
        'intel_briefings': {'label': 'C · Gold & Bitcoin intelligence briefings', 'approved': bool(brief_approved), 'flag': brief_flag(),
                            'mode': 'LIVE' if brief_approved and brief_flag() else 'PREVIEW',
                            'preview_generation': os.getenv(BRIEF_ENABLED, '').strip() == '1',
                            'schedule': '08:00 EAT morning (Gold & Bitcoin) · 15:00 EAT New York (Gold focus)', 'next': next_slots(now),
                            'latest': (by_cat('intel_briefings') or [None])[0], 'last_sent': last(by_cat('intel_briefings')),
                            'skipped_7d': [{'id': n['id'], 'state': n['state'], 'reason': n['message'][:160]} for n in by_cat('intel_briefings')
                                           if n['state'].startswith('SKIPPED') and now - n['created'] <= 7 * 86400],
                            'failures_24h': failures(by_cat('intel_briefings')), 'controls': CONTROLS['intel_briefings']},
    }
    intel = {}
    for sym in ('XAUUSD', 'BTCUSD'):
        try:
            i = (intel_fn or _intel)(store, sym, (runtime.get('latest_inputs', {}).get(sym) or {}).get('quote'), now)
            intel[sym] = {'data_timestamp': i['data_timestamp'], 'stale': i['stale'], 'price': i['price'],
                          'structure': {k: v['state'] for k, v in i['structure'].items()}, 'regime': i['regime']['trend']['state'],
                          'volatility': i['regime']['volatility']['state']}
        except Exception as exc:
            intel[sym] = {'status': 'UNAVAILABLE', 'reason': type(exc).__name__}
    inputs = runtime.get('latest_inputs') or {}
    return {'categories': cats, 'intelligence': intel, 'health': health(store, runtime, now),
            'last_market_data_update': max((v['asof'] for v in inputs.values() if v.get('asof')), default=None),
            'latest_successful_delivery': max([t for t in (cats['qualified_signals']['last_sent'], cats['research_observations']['last_sent'],
                                                           cats['intel_briefings']['last_sent']) if t] or [None]),
            'broker_execution': 'DISABLED', 'note': 'Read-only view. Approvals are recorded through the owner CLI; this page cannot change delivery.'}


def _intel(store, sym, quote, now):
    from market_intel.live import intelligence
    return intelligence(store, sym, quote, now)
