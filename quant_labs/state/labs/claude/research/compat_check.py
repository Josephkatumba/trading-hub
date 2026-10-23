"""Decision-path compatibility: direct replay vs the live restricted host + live qualify().

For historical snapshots where a model fires, run backend/quant_live/model_host.execute
(immutable data, restricted builtins) and runtime.qualify with now = decision time,
and compare against the harness's direct call and gate emulation.
"""
import json, sys
from bisect import bisect_right
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import harness
from quant_live.model_host import execute
from quant_live.runtime import qualify
from quant_labs.data import SharedData
from quant_labs.evaluation.v1.engine import POLICY

LAB = Path(__file__).resolve().parents[1]
data = SharedData(harness.ROOT / 'quant_labs/state/shared', harness.DATASET)
report = {}
for key in ['index_trend_day', 'crypto_trend_breakout', 'index_turn_of_month']:
    d = LAB / 'strategies' / key
    manifest = json.loads((d / 'manifest.json').read_text())
    source = (d / 'model.py').read_text()
    detect, sha = harness.load_model(d / 'model.py')
    intents = json.loads((LAB / 'research/results' / f"{key}_{manifest['version']}_full_intents.json").read_text())
    checked, agree, admitted, reasons = 0, 0, 0, {}
    for it in intents[::max(1, len(intents) // 12)][:12]:
        sym, t = it['symbol'], it['entry_at']
        meta = dict(data.metadata(sym), commission_price=POLICY['commission_price'][sym], tradable_long=True, tradable_short=True)
        frames = {}
        for tf, n in manifest['requirements'].items():
            bars = data.read(sym, tf)
            j = bisect_right([b['utc'] + harness.TF[tf] for b in bars], t)
            frames[tf] = bars[max(0, j - n):j]
        q = next(b for b in data.read(sym, 'M15') if b['utc'] == t)
        snap = {'symbol': sym, 'broker_symbol': sym, 'source': 'CLAUDE_COMPAT', 'asof': t, 'time_verified': True,
                'quote': {'bid': q['open'], 'ask': q['open'] + q['spread'], 'tick_at': t}, 'metadata': meta,
                'frames': frames, 'data_quality': {}, 'input_sha256': 'compat'}
        direct = detect(snap)
        restricted = execute(source, snap)
        checked += 1
        agree += direct == restricted
        model = {'lab': 'claude', 'key': key, 'version': manifest['version'], 'manifest': manifest, 'sha': sha}
        for dec in restricted:
            sig, why = qualify(snap, model, dec, t)
            admitted += sig is not None
            reasons[why or 'ADMITTED'] = reasons.get(why or 'ADMITTED', 0) + 1
    report[key] = {'version': manifest['version'], 'snapshots': checked, 'direct_equals_restricted': agree, 'live_qualify': reasons}
    print(key, report[key])
(LAB / 'research/results/compat_check.json').write_text(json.dumps(report, indent=1))
