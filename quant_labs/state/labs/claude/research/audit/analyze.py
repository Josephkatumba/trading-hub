"""Milestone 2 research audit: evidence quality of every evaluated Quant Labs strategy and cell.

Sources (all produced by the frozen shared evaluator v1, never re-tuned here):
  * completed jobs in quant_labs/state/control.sqlite3 (all labs, read-only);
  * exact-request recoveries of OneDrive-lock failures (Claude, Kimi, Codex retry files);
  * a lab-harness replay of Codex compression_escape (never queued by Codex).
Per strategy-version and per instrument cell and period: n, net expectancy (normal/stress),
trade-level bootstrap 95% CI, two-sided sign-flip p, expectancy without the best trade, best
trade share of total R. Holm correction across every cell examined on the test period.
"""
import json
import random
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
PERIODS = ('train', 'validation', 'test')
POLICY = json.loads((ROOT / 'quant_labs/evaluation/v1/policy.json').read_text())
from datetime import datetime
BOUNDS = {'train': (POLICY['train_start'], POLICY['validation_start']), 'validation': (POLICY['validation_start'], POLICY['test_start']),
          'test': (POLICY['test_start'], POLICY['test_end'])}
BOUNDS = {k: (datetime.fromisoformat(a).timestamp(), datetime.fromisoformat(b).timestamp()) for k, (a, b) in BOUNDS.items()}


def load():
    db = sqlite3.connect(f"file:{(ROOT / 'quant_labs/state/control.sqlite3').as_posix()}?mode=ro", uri=True)
    out = []
    for lab, s, v, job, body in db.execute("SELECT j.lab,j.strategy,j.version,j.id,r.body FROM jobs j JOIN results r ON r.job=j.id"):
        if s == 'evaluation_contract_smoke':
            continue
        out.append({'lab': lab, 'strategy': s, 'version': v, 'job': job, 'source': 'queue', 'trades': json.loads(body)['trades']})
    for r in json.loads((HERE.parent / 'queue_runs/recovered_evaluations.json').read_text()):
        out.append({'lab': 'claude', 'strategy': r['strategy'], 'version': r['version'], 'job': r['original_job'], 'source': 'recovered', 'trades': r['result']['trades']})
    for f in (HERE / 'recovered').glob('*.json'):
        r = json.loads(f.read_text())
        out.append({'lab': r['lab'], 'strategy': r['strategy'], 'version': r['version'], 'job': r['original_job'], 'source': 'recovered', 'trades': r['result']['trades']})
    for r in json.loads((ROOT / 'quant_labs/next_phase/retry_evaluations.json').read_text()):
        if r['retry_status'] == 'COMPLETE':
            out.append({'lab': 'codex', 'strategy': r['key'], 'version': '0.1.0', 'job': r['original_job'], 'source': 'codex_retry', 'trades': r['result']['trades']})
    # Codex compression_escape: never queued; replay its unmodified source with the frozen evaluator.
    from quant_labs.data import SharedData
    from quant_labs.evaluation.v1.engine import evaluate
    data = SharedData(ROOT / 'quant_labs/state/shared', 'bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3')
    intents = json.loads((HERE.parent / 'results/compression_escape_0.1.0_full_intents.json').read_text())
    out.append({'lab': 'codex', 'strategy': 'compression_escape', 'version': '0.1.0', 'job': 'harness-replay', 'source': 'claude_harness_replay',
                'trades': evaluate(data, {'signals': intents, 'strategy': {'timeframe': 'M15'}})['trades']})
    return out


def stats(rs, seed):
    if not rs:
        return {'n': 0}
    rng = random.Random(seed)
    boots = sorted(statistics.fmean(rng.choices(rs, k=len(rs))) for _ in range(2000))
    obs = sum(rs)
    flips = sum(abs(sum(r * (1 if rng.random() < .5 else -1) for r in rs)) >= abs(obs) for _ in range(2000))
    best = max(rs)
    gains = sum(r for r in rs if r > 0)
    return {'n': len(rs), 'exp': statistics.fmean(rs), 'ci95': [boots[50], boots[1949]], 'p_two_sided': (flips + 1) / 2001,
            'exp_without_best': statistics.fmean(sorted(rs)[:-1]) if len(rs) > 1 else None,
            'best_trade_share_of_gains': best / gains if gains > 0 else None, 'win_rate': sum(r > 0 for r in rs) / len(rs)}


def cells(job):
    by = defaultdict(lambda: defaultdict(lambda: {'normal': [], 'stress': []}))
    for t in job['trades']:
        at, deadline = t['plan']['entry_at'], t['plan']['deadline']
        period = next((p for p, (a, b) in BOUNDS.items() if a <= at and deadline < b), None)
        if period is None:
            continue
        for sc in ('normal', 'stress'):
            if t[sc].get('r') is not None:
                for cell in (t['plan']['symbol'], 'ALL'):
                    by[cell][period][sc].append(t[sc]['r'])
    return by


def main():
    jobs = load()
    rows = []
    for j in jobs:
        for cell, periods in cells(j).items():
            rec = {'lab': j['lab'], 'strategy': j['strategy'], 'version': j['version'], 'cell': cell, 'job': j['job'][:8], 'source': j['source']}
            for p in PERIODS:
                d = periods.get(p, {'normal': [], 'stress': []})
                rec[p] = stats(d['normal'], hash((j['job'], cell, p)) % 10**6)
                rec[p]['stress_exp'] = statistics.fmean(d['stress']) if d['stress'] else None
            rows.append(rec)
    # Holm across every test-period cell examined (instrument-level cells only; ALL rows summarise them).
    tested = sorted((r for r in rows if r['test'].get('n', 0) >= 1 and r['cell'] != 'ALL'), key=lambda r: r['test']['p_two_sided'])
    m, running = len(tested), 0
    for i, r in enumerate(tested):
        running = max(running, min(1, (m - i) * r['test']['p_two_sided']))
        r['test']['holm_p'] = running
    # Trend Reclaim variant overlap on BTCUSD: same entries, different targets?
    entries = {}
    for j in jobs:
        if j['strategy'].startswith('trend_reclaim'):
            btc = {t['plan']['entry_at'] for t in j['trades'] if t['plan']['symbol'] == 'BTCUSD'}
            if btc:
                entries[j['strategy']] = btc
    names = sorted(entries)
    overlap = {f'{a}~{b}': len(entries[a] & entries[b]) / len(entries[a] | entries[b]) for i, a in enumerate(names) for b in names[i + 1:]}
    (HERE / 'evidence.json').write_text(json.dumps({'cells': rows, 'trend_reclaim_btc_entry_jaccard': overlap, 'holm_family_size': m}, indent=1), encoding='utf-8')
    f = lambda x: 'NA' if x is None else f'{x:+.3f}'
    print(f'Holm family (instrument cells with test trades): {m}')
    for r in sorted(rows, key=lambda r: (r['lab'], r['strategy'], r['version'], r['cell'])):
        t = r['test']
        line = ' | '.join(f"{p[:3]} {r[p].get('n', 0):3d} {f(r[p].get('exp'))}" for p in PERIODS)
        extra = ''
        if t.get('n'):
            extra = f" | test CI[{t['ci95'][0]:+.2f},{t['ci95'][1]:+.2f}] p={t['p_two_sided']:.3f} holm={t.get('holm_p', float('nan')):.2f} -best {f(t['exp_without_best'])} stress {f(t['stress_exp'])}"
        print(f"{r['lab']:6s} {r['strategy'][:24]:24s} {r['version']:5s} {r['cell']:7s} {line}{extra}")
    print('Trend Reclaim BTCUSD entry overlap (Jaccard):', {k: round(v, 2) for k, v in overlap.items()})


if __name__ == '__main__':
    main()
