"""CEO previews for the three Telegram categories, built from GENUINE records only (nothing is sent).

A and B: the most recent real historical signal of each model (frozen-evaluator intents), with the
model's own source re-run on the genuine MT5 snapshot at that moment to obtain its real rationale
and direction; regime from rule R1. Labelled as historical research records, not live detections.
C: briefings generated from the live engine's current closed candles and quotes.
"""
import json
import sys
import time
import urllib.request
from bisect import bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from quant_labs.data import SharedData
from quant_labs.evaluation.v1.engine import POLICY
from quant_live.model_host import execute
from quant_live.runtime import regime_at_entry, session
from quant_live.execution import rounded
from quant_live.store import Store
from quant_live import telegram as tg, research_observations as ro
from market_intel.briefings import compose

TF = {'M1': 60, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}
data = SharedData(ROOT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')
RESULTS = HERE.parent / 'results'
live = Store(ROOT / 'backend/data/quant_live')


def snapshot(manifest, symbol, t):
    frames = {}
    for tf, n in manifest['requirements'].items():
        bars = data.read(symbol, tf)
        frames[tf] = bars[max(0, bisect_right([b['utc'] + TF[tf] for b in bars], t) - n):bisect_right([b['utc'] + TF[tf] for b in bars], t)]
    if 'H1' not in frames:  # regime rule needs closed H1 candles
        h1 = data.read(symbol, 'H1')
        frames['H1_for_regime'] = h1[max(0, bisect_right([b['utc'] + 3600 for b in h1], t) - 30):bisect_right([b['utc'] + 3600 for b in h1], t)]
    q = next(b for b in data.read(symbol, 'M15') if b['utc'] == t)
    meta = {**data.metadata(symbol), 'commission_price': POLICY['commission_price'][symbol], 'tradable_long': True, 'tradable_short': True}
    return {'symbol': symbol, 'frames': frames, 'quote': {'bid': q['open'], 'ask': q['open'] + q['spread'], 'tick_at': t}, 'metadata': meta, 'asof': t}


def historical_signal(lab, key, intents_file):
    m = next(x for x in live.models() if (x['lab'], x['key']) == (lab, key))
    it = json.loads((RESULTS / intents_file).read_text())[-1]
    snap = snapshot(m['manifest'], it['symbol'], it['entry_at'])
    d = execute(m['source'], {k: v for k, v in snap.items()} | {'frames': {k: v for k, v in snap['frames'].items() if k != 'H1_for_regime'}})[0]
    reg = regime_at_entry({'frames': {'H1': snap['frames'].get('H1') or snap['frames']['H1_for_regime']}})
    entry = snap['quote']['ask'] if d['direction'] == 'LONG' else snap['quote']['bid']
    tick, long = snap['metadata']['tick_size'], d['direction'] == 'LONG'
    d = {**d, 'stop_loss': rounded(d['stop_loss'], tick, not long), 'take_profit': rounded(d['take_profit'], tick, not long)}  # as the live gate does
    risk = abs(entry - d['stop_loss'])
    return m, {'signal_id': f'historical_{key}_{it["entry_at"]}', 'lab': lab, 'lab_name': tg.RESEARCHERS[lab] + ' Quant Lab', 'model_key': key,
               'model_name': m['manifest']['name'], 'model_version': m['version'], 'symbol': it['symbol'], 'timeframe': m['manifest']['timeframe'],
               'direction': d['direction'], 'entry_at': it['entry_at'], 'entry': entry, 'stop_loss': d['stop_loss'], 'take_profit': d['take_profit'],
               'planned_rr': abs(d['take_profit'] - entry) / risk, 'risk': risk, 'atr': d['atr'], 'deadline': it['entry_at'] + d['horizon_seconds'],
               'rationale': d['rationale'], 'regime_at_entry': reg, 'session': session(it['entry_at']), 'spread': snap['quote']['ask'] - snap['quote']['bid']}


def main():
    out = ['# Telegram category previews (generated ' + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()) + '; nothing sent)', '']
    _, a = historical_signal('claude', 'index_trend_day', 'index_trend_day_0.2.0_full_intents.json')
    out += ['## A · Qualified experimental signal (new format; HISTORICAL record of an approved strategy, not live)', '', '```', tg.message(a, 'PAPER_CANDIDATE'), '```', '']
    out += ['## B · Research observations (HISTORICAL research records; no live research event exists yet)', '']
    for lab, key, f in (('codex', 'compression_escape', 'compression_escape_0.1.0_full_intents.json'),
                        ('claude', 'hourly_shock_drift', 'hourly_shock_drift_0.1.0_full_intents.json')):
        m, s = historical_signal(lab, key, f)
        out += ['```', ro.message(s, ro.evidence_row(lab, key, m['version']), historical_record=True), '```', '']
    quotes = {k: v['quote'] for k, v in json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/quant-labs/live', timeout=30))['runtime']['latest_inputs'].items()}
    for kind in ('morning', 'new_york'):
        state, text = compose(kind, live, quotes, time.time())
        out += [f'## C · {kind} briefing (LIVE data, generated now; state {state})', '', '```', text, '```', '']
    path = HERE / 'TELEGRAM_CATEGORY_PREVIEWS.md'
    path.write_text('\n'.join(out), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
