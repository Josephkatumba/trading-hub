"""Pooled and per-split metrics for every registered Claude version (frozen evaluator)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import harness
from quant_labs.data import SharedData
from quant_labs.evaluation.v1.engine import evaluate, POLICY
from quant_labs.evaluation.v1.metrics import summarize

LAB = Path(__file__).resolve().parents[1]
R = LAB / 'research/results'
data = SharedData(harness.ROOT / 'quant_labs/state/shared', harness.DATASET)
MODELS = [('index_trend_day', '0.2.0', 'M15'), ('crypto_trend_breakout', '0.3.0', 'H4'), ('crypto_trend_breakout', '0.2.0', 'H4'),
          ('crypto_trend_breakout', '0.1.0', 'H4'), ('index_trend_day', '0.1.0', 'M15'), ('hourly_shock_drift', '0.1.0', 'H1'),
          ('index_turn_of_month', '0.1.0', 'M15'), ('index_gap_fade', '0.1.0', 'M15')]
E = harness.datetime_epoch
splits = {'train': (POLICY['train_start'], POLICY['validation_start']), 'validation': (POLICY['validation_start'], POLICY['test_start']),
          'test': (POLICY['test_start'], POLICY['test_end']), 'all': (POLICY['train_start'], POLICY['test_end'])}
keep = ['attempted', 'resolved', 'unknown', 'win_rate', 'net_expectancy_r', 'total_r', 'profit_factor', 'max_realized_drawdown_r',
        'longest_losing_streak', 'planned_rr_mean', 'realized_win_loss_ratio', 'opportunities_per_month', 'weekly_bootstrap_expectancy_ci95', 'weekly_sign_flip_p']
out = {}
for key, ver, tf in MODELS:
    intents = json.loads((R / f'{key}_{ver}_full_intents.json').read_text())
    res = evaluate(data, {'signals': intents, 'strategy': {'timeframe': tf}})
    rec = {}
    for name, (lo, hi) in splits.items():
        lo, hi = E(lo), E(hi)
        sel = [t for t in res['trades'] if lo <= t['plan']['entry_at'] and t['plan']['deadline'] < hi]
        rec[name] = {sc: {k: summarize(sel, lo, hi, sc)[k] for k in keep} for sc in ('normal', 'stress')}
        if name == 'all':
            for d in ('LONG', 'SHORT'):
                sd = [t for t in sel if t['plan']['direction'] == d]
                s = summarize(sd, lo, hi, 'normal')
                rec['all_' + d.lower()] = {'n': s['resolved'], 'exp': s['net_expectancy_r'], 'win': s['win_rate']}
    out[f'{key}@{ver}'] = rec
    a = rec['all']['normal']
    print(f"{key}@{ver}: n={a['resolved']} win={a['win_rate']:.3f} exp={a['net_expectancy_r']:+.3f} stress={rec['all']['stress']['net_expectancy_r']:+.3f} "
          f"PF={a['profit_factor']:.2f} DD={a['max_realized_drawdown_r']:.1f} streak={a['longest_losing_streak']} realizedW/L={a['realized_win_loss_ratio']:.2f} "
          f"per_month={a['opportunities_per_month']:.1f} CI95={[round(x,3) for x in a['weekly_bootstrap_expectancy_ci95']]} p={a['weekly_sign_flip_p']:.3f} "
          f"long={rec['all_long']} short={rec['all_short']}")
(R / 'summary_all_versions.json').write_text(json.dumps(out, indent=1))
