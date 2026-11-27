"""Parameter-neighbourhood robustness diagnostics (train+validation only).

Not used for selection: the registered versions are frozen. Each perturbation is a
disclosed diagnostic trial; results are kept in results/sensitivity_*.json.
"""
import json, re, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import harness

LAB = Path(__file__).resolve().parents[1]
GRID = {
    'index_trend_day': [('DECISION_DELAY', [3600, 5400, 9000, 10800]), ('MOVE_ATR', [0.35, 0.55]),
                        ('EXTREME_FRAC', [0.65, 0.85]), ('STOP_ATR', [0.25, 0.40]), ('TARGET_R', [2.0, 3.0])],
    'crypto_trend_breakout': [('CHANNEL', [60, 180]), ('BASELINE', [200, 400]), ('STOP_ATR', [2.0, 4.0]), ('TARGET_R', [2.0, 4.0])],
}

def variant(key, name, value):
    src_dir = LAB / 'strategies' / key
    d = LAB / 'research' / 'sensitivity' / f'{key}_{name}_{value}'
    d.mkdir(parents=True, exist_ok=True)
    src = (src_dir / 'model.py').read_text()
    src, n = re.subn(rf'^{name} = [^\n#]+', f'{name} = {value}', src, flags=re.M)
    assert n == 1, name
    (d / 'model.py').write_text(src)
    m = json.loads((src_dir / 'manifest.json').read_text())
    m['version'] = m['version'] + f'-diag.{name}.{value}'
    if key == 'crypto_trend_breakout' and name in ('BASELINE', 'CHANNEL'):
        m['requirements'] = {'H4': 480}
    (d / 'manifest.json').write_text(json.dumps(m))
    return d

rows = []
for key, grid in GRID.items():
    base = harness.run(LAB / 'strategies' / key, splits=('train', 'validation'), tag='sens-base')
    rows.append((key, 'BASE', '-', base))
    for name, values in grid:
        for v in values:
            rows.append((key, name, v, harness.run(variant(key, name, v), splits=('train', 'validation'), tag='sens')))
out = []
for key, name, v, r in rows:
    tr, va = r['periods']['train']['normal'], r['periods']['validation']['normal']
    out.append({'model': key, 'param': name, 'value': v, 'train_n': tr['resolved'], 'train_exp': tr['net_expectancy_r'],
                'val_n': va['resolved'], 'val_exp': va['net_expectancy_r']})
    f = lambda x: 'NA' if x is None else f'{x:+.3f}'
    print(f"{key:22s} {name:15s} {str(v):6s} train n={tr['resolved']:4d} {f(tr['net_expectancy_r'])}  val n={va['resolved']:4d} {f(va['net_expectancy_r'])}")
(LAB / 'research' / 'results' / 'sensitivity_summary.json').write_text(json.dumps(out, indent=1))
