"""Frozen research accounting; unknowns never become zero-return wins or losses."""
from collections import Counter,defaultdict
import math
import random
import statistics

def summarize(trades,start,end,scenario='normal'):
    known=sorted((t for t in trades if t[scenario].get('r') is not None),key=lambda t:t[scenario]['exit_at'])
    rs=[t[scenario]['r'] for t in known];gains=sum(r for r in rs if r>0);losses=-sum(r for r in rs if r<0)
    equity=peak=dd=streak=longest=0
    for r in rs:
        equity+=r;peak=max(peak,equity);dd=max(dd,peak-equity)
        streak=streak+1 if r<0 else 0;longest=max(longest,streak)
    win=[r for r in rs if r>0];lose=[-r for r in rs if r<0]
    planned=[abs(t['plan']['take_profit']-t['plan']['entry'])/t['plan']['risk'] for t in trades if t.get('plan')]
    bands=Counter('7+' if r>=7-1e-8 else '5–7' if r>=5-1e-8 else '4–5' if r>=4-1e-8 else '3–4' if r>=3-1e-8 else '2–3' if r>=2-1e-8 else '<2' for r in planned)
    blocks=defaultdict(list)
    for t in known:blocks[int(t['plan']['entry_at']//604800)].append(t[scenario]['r'])
    interval=None;p=1.0
    if len(blocks)>=2:
        rng=random.Random(36182);groups=list(blocks.values());means=[]
        for _ in range(1200):
            selected=[rng.choice(groups) for _ in groups];values=[x for group in selected for x in group]
            means.append(sum(values)/len(values))
        means.sort();interval=[means[30],means[1169]]
        sums=[sum(g) for g in groups];observed=sum(sums)
        greater=sum(sum(s*(1 if rng.random()>.5 else -1) for s in sums)>=observed for _ in range(1999))
        p=(greater+1)/2000
    return {'attempted':len(trades),'resolved':len(rs),'unknown':len(trades)-len(rs),'statuses':dict(Counter(t[scenario]['status'] for t in trades)),
            'win_rate':len(win)/len(rs) if rs else None,'net_expectancy_r':sum(rs)/len(rs) if rs else None,
            'total_r':sum(rs) if rs else None,'profit_factor':gains/losses if losses else None,
            'max_realized_drawdown_r':dd if rs else None,'longest_losing_streak':longest if rs else None,
            'planned_rr_mean':statistics.mean(planned) if planned else None,'planned_rr_bands':dict(bands),
            'realized_win_loss_ratio':statistics.mean(win)/statistics.mean(lose) if win and lose else None,
            'opportunities_per_month':len(trades)/max((end-start)/86400/30.4375,1),
            'data_complete_fraction':len(rs)/len(trades) if trades else None,
            'weekly_bootstrap_expectancy_ci95':interval,'weekly_sign_flip_p':p,
            'independent_entry_weeks':len(blocks),'floating_and_unknown_risk_included_in_drawdown':False}
