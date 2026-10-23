"""Read live closed candles and strategy observations from the existing quant_live store (read-only)."""
import json
import time
from .engine import build, render_telegram, USD_PAIRS
from .rules import TF

COUNTS = {'M15': 400, 'H1': 600, 'H4': 199, 'D1': 199}


def frames(store, symbol, now, counts=COUNTS):
    out = {}
    with store.db() as c:
        for tf, n in counts.items():
            rows = c.execute('SELECT b.body FROM candles b WHERE symbol=? AND tf=? AND utc+?<=? AND NOT EXISTS '
                             '(SELECT 1 FROM candle_revisions r WHERE r.symbol=b.symbol AND r.tf=b.tf AND r.utc=b.utc) ORDER BY utc DESC LIMIT ?',
                             (symbol, tf, TF[tf], now, n)).fetchall()
            out[tf] = [json.loads(r['body']) for r in reversed(rows)]
    return out


def observations(store, symbol, now, hours=24):
    """Confirmed paper signals for the symbol in the last `hours` (live detections only)."""
    out = []
    for s in store.signals(300):
        if s['symbol'] == symbol and s.get('confirmed') and now - s['entry_at'] <= hours * 3600:
            out.append({'summary': f"{s['model_name']} v{s['model_version']} {'BUY' if s['direction'] == 'LONG' else 'SELL'} ({s['state']})",
                        'signal_id': s['signal_id'], 'entry_at': s['entry_at']})
    return out


def intelligence(store, symbol, quote=None, now=None):
    now = time.time() if now is None else now
    context = {'strategy_observations': observations(store, symbol, now)}
    if symbol == 'XAUUSD':
        context['fx_h1'] = {p: frames(store, p, now, {'H1': 30})['H1'] for p in USD_PAIRS}
    if symbol == 'BTCUSD':
        context['nas100_h1'] = frames(store, 'NAS100', now, {'H1': 200})['H1']
    intel = build(symbol, frames(store, symbol, now), quote, now, context)
    intel['telegram_preview'] = render_telegram(intel)
    intel['telegram_status'] = 'INTERNAL_PREVIEW_ONLY (no scheduled or outbound delivery without CEO approval)'
    return intel
