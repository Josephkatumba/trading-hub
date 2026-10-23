"""Generate the strategy sieve table for every live-monitored strategy from the unified leaderboard (read-only)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / 'backend'))
from quant_live.store import Store
from quant_live.leaderboard import leaderboard

FURTHER = {'A': 'Yes: priority forward test', 'B': 'Yes: forward paper evidence only, no tuning',
           'C': 'Only as a structurally different hypothesis', 'D': 'No (preserved, deprioritised)'}


def f(x, d=2):
    return '—' if x is None else f'{x:+.{d}f}'


def main():
    board = leaderboard(Store(ROOT / 'backend/data/quant_live'))
    lines = ['# Strategy sieve (all live-monitored strategies)', '',
             'Historical = frozen shared evaluator after realistic costs (train / validation / test; every split was previously exposed). '
             'Cost sensitivity = test expectancy under stress (doubled spreads and slippage) minus normal. Forward = live paper signals since registration.', '',
             '| Cat | Researcher | Strategy | Mechanism | Instruments | Hist. trades/mo | Train | Validation | Test | Cost sensitivity | Forward (signals/resolved, net R) | Limitations | Further research? |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in board['rows']:
        h = r['historical'] or {}
        t, v, te = h.get('train', {}), h.get('validation', {}), h.get('test', {})
        cell = lambda x: f"{f(x.get('net_expectancy_r'))}R (n={x.get('n', 0)})" + (' ⚠' if x.get('insufficient_sample') else '') if x else '—'
        cost = f(te['stress_expectancy_r'] - te['net_expectancy_r']) if te.get('stress_expectancy_r') is not None and te.get('net_expectancy_r') is not None else '—'
        fw = r['forward']
        mech = (Store(ROOT / 'backend/data/quant_live').model(r['lab'], r['key'], r['version']) or {}).get('manifest', {}).get('hypothesis', '')
        limits = 'correlated family; ' if r['family'] else ''
        limits += 'small samples; ' if any(x.get('insufficient_sample') for x in (t, v, te) if x) else ''
        limits += 'all splits previously exposed'
        freq = r['frequency'].get('historical_trades_per_month')
        lines.append(f"| {r['category']} | {r['researcher']} | {r['strategy']} v{r['version']} | {mech[:110].replace('|', '/')} | {', '.join(r['instruments'])} | "
                     f"{'—' if freq is None else f'{freq:.1f}'} | {cell(t)} | {cell(v)} | {cell(te)} | {cost} | "
                     f"{fw['confirmed']}/{fw['resolved']}, {f(fw['net_paper_r'])} | {limits} | {FURTHER.get(r['category'], 'Not audited')} |")
    lines += ['', '⚠ = fewer than 30 trades. No strategy is validated or in production. Category A is empty.']
    out = HERE.parents[1] / 'STRATEGY_SIEVE_2026-10-23.md'
    out.write_text('\n'.join(lines), encoding='utf-8')
    print(out, len(board['rows']), 'strategies')


if __name__ == '__main__':
    main()
