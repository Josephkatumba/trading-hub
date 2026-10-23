"""Unified Quant Labs leaderboard: historical (train / validation / test) and forward paper results.

Historical figures come from the Milestone 2 audit of frozen shared-evaluator results
(quant_labs/state/labs/claude/research/audit/evidence.json); forward figures come from this live
store's own paper outcomes. They are never pooled. Correlated variants are flagged as one family,
and small samples are flagged prominently.
"""
import json
from .store import PROJECT
from .report import metrics
from .diagnostics import diagnostics

AUDIT = PROJECT / 'quant_labs/state/labs/claude/research/audit'
RESEARCHERS = {'claude': 'Claude', 'codex': 'Codex', 'kimi': 'Kimi'}
MIN_SAMPLE = 30


def _load(name):
    try:
        return json.loads((AUDIT / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def historical(evidence, lab, key, version):
    """n-weighted combination of a strategy-version's per-job 'ALL' rows, per split."""
    rows = [r for r in (evidence or {}).get('cells', []) if r['cell'] == 'ALL' and (r['lab'], r['strategy'], r['version']) == (lab, key, version)]
    if not rows:
        return None
    out = {}
    for split in ('train', 'validation', 'test'):
        n = sum(r[split].get('n', 0) for r in rows)
        exp = sum(r[split]['exp'] * r[split]['n'] for r in rows if r[split].get('n')) / n if n else None
        sn = [(r[split]['stress_exp'], r[split]['n']) for r in rows if r[split].get('n') and r[split].get('stress_exp') is not None]
        out[split] = {'n': n, 'net_expectancy_r': exp,
                      'stress_expectancy_r': sum(e * k for e, k in sn) / sum(k for _, k in sn) if sn else None,
                      'insufficient_sample': n < MIN_SAMPLE}
    return out


def by_instrument(evidence, lab, key, version):
    """Test-split result per instrument cell, so a model's promising and rejected markets are visible separately."""
    out = {}
    for r in (evidence or {}).get('cells', []):
        if r['cell'] != 'ALL' and (r['lab'], r['strategy'], r['version']) == (lab, key, version) and r['test'].get('n'):
            prev = out.get(r['cell'])
            n = r['test']['n'] + (prev['n'] if prev else 0)
            exp = (r['test']['exp'] * r['test']['n'] + (prev['net_expectancy_r'] * prev['n'] if prev else 0)) / n
            out[r['cell']] = {'n': n, 'net_expectancy_r': exp, 'insufficient_sample': n < MIN_SAMPLE}
    return out or None


def leaderboard(store, signals=None, outcomes=None):
    evidence, cats = _load('evidence.json'), _load('leaderboard_categories.json') or {}
    signals = store.signals(1000) if signals is None else signals
    outcomes = store.outcomes() if outcomes is None else outcomes
    diag = diagnostics(store)['models']
    rows = []
    for m in store.models():
        lab, key, version = m['lab'], m['key'], m['version']
        ident = f'{lab}:{key}@{version}'
        source = cats.get('evidence_aliases', {}).get(ident, ident)
        s_lab, rest = source.split(':', 1)
        s_key, s_version = rest.split('@')
        forward = metrics([s for s in signals if (s['lab'], s['model_key'], s['model_version']) == (lab, key, version)], outcomes)
        category = cats.get('models', {}).get(f'{lab}:{key}', {'category': 'UNCLASSIFIED', 'label': 'Not yet audited'})
        family = next((note for prefix, note in cats.get('families', {}).items() if f'{lab}:{key}'.startswith(prefix)), None)
        rows.append({
            'researcher': RESEARCHERS.get(lab, lab), 'lab': lab, 'strategy': m['manifest']['name'], 'key': key, 'version': version,
            'instruments': m['manifest']['instruments'], 'timeframe': m['manifest']['timeframe'],
            'status': m['status'], 'category': category['category'], 'category_label': category['label'],
            'evidence_tier': store.tier(lab, key, version), 'telegram_enabled': bool(m['alert_enabled']),
            'family': family, 'historical': historical(evidence, s_lab, s_key, s_version),
            'test_by_instrument': by_instrument(evidence, s_lab, s_key, s_version),
            'historical_source': None if source == ident else f'evidence of {source} (identical intents)',
            'forward': {**{k: forward[k] for k in ('confirmed', 'resolved', 'win_rate', 'average_r', 'net_paper_r', 'max_realized_paper_drawdown_r',
                                                    'estimated_costs_r', 'tp_hits', 'sl_hits', 'expired_time_exits', 'overlapping_excluded')},
                        'insufficient_sample': forward['resolved'] < MIN_SAMPLE},
            'last_successful_evaluation': diag.get(ident, {}).get('last_successful_evaluation')})
    order = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
    rows.sort(key=lambda r: (order.get(r['category'], 4), r['researcher'], r['strategy']))
    return {'rows': rows, 'min_sample': MIN_SAMPLE, 'historical_note': (
        'Historical = frozen shared evaluator after realistic costs; all splits were previously exposed to research, none is an untouched holdout. '
        'Forward = live paper signals since registration. The two are never pooled. No strategy is validated or in production.'),
            'audit_available': evidence is not None}
