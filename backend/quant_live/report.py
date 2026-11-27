"""Paper-signal performance, with actual executed R explicitly unavailable."""
from collections import defaultdict,Counter
from .store import LAB_NAMES

def independent(confirmed,outcomes):
    """Drop signals opened while the same model already had an open signal on the same instrument."""
    kept,overlap,busy=[],[],{}
    for s in sorted(confirmed,key=lambda x:x['entry_at']):
        k=(s['lab'],s['model_key'],s['model_version'],s['symbol'])
        if s['entry_at']<busy.get(k,0):overlap.append(s);continue
        o=outcomes.get(s['signal_id'],{});kept.append(s)
        busy[k]=o.get('exit_at') if o.get('status') in ('TP','SL','TIME_EXIT') and o.get('exit_at') else s.get('deadline',s['entry_at'])
    return kept,overlap

def cost_r(s,o):
    """Estimated explicit costs in R: commission, financing and spread-based slippage (spread crossing is in the bid/ask fills)."""
    if not s.get('risk'):return None
    slip=abs((o.get('entry_price') or s['entry'])-s['entry'])+(0.5 if o.get('status')=='SL' else 0.25)*(s.get('spread') or 0)
    return (slip+(o.get('commission_price') or 0)+max(o.get('financing_price') or 0,0))/s['risk']

def metrics(signals,outcomes):
    confirmed_all=[s for s in signals if s.get('confirmed')]
    confirmed,overlapping=independent(confirmed_all,outcomes)
    latest={s['signal_id']:outcomes.get(s['signal_id'],{}) for s in confirmed}
    statuses=Counter(o.get('status','PENDING') for o in latest.values())
    resolved=[(s,latest[s['signal_id']]) for s in confirmed if latest[s['signal_id']].get('simulated_net_r') is not None]
    rs=[o['simulated_net_r'] for s,o in sorted(resolved,key=lambda x:x[1].get('exit_at',0))]
    gains=sum(r for r in rs if r>0);loss=-sum(r for r in rs if r<0);eq=peak=dd=0
    for r in rs:eq+=r;peak=max(peak,eq);dd=max(dd,peak-eq)
    costs=[c for c in (cost_r(s,o) for s,o in resolved) if c is not None]
    return {'detected':len(signals),'confirmed':len(confirmed_all),'overlapping_excluded':len(overlapping),
            'estimated_costs_r':sum(costs) if costs else None,'average_cost_r':sum(costs)/len(costs) if costs else None,
            'triggered_entries':len(confirmed_all),'entry_basis':'market paper quote at confirmation (no pending orders)',
            'tp_hits':statuses.get('TP',0),'sl_hits':statuses.get('SL',0),'expired_time_exits':statuses.get('TIME_EXIT',0),
            'open':statuses.get('PENDING',0),'unknown_outcome':sum(v for k,v in statuses.items() if k not in ('TP','SL','TIME_EXIT','PENDING')),
            'quality_rejected':len(signals)-len(confirmed_all),
            'resolved':len(rs),'unresolved':len(confirmed)-len(rs),'counted_independent':len(confirmed),
            'win_rate':sum(r>0 for r in rs)/len(rs) if rs else None,'net_paper_r':sum(rs) if rs else None,
            'average_r':sum(rs)/len(rs) if rs else None,'net_expectancy_r':sum(rs)/len(rs) if rs else None,
            'profit_factor':gains/loss if loss else None,
            'max_realized_paper_drawdown_r':dd if rs else None,'actual_realized_r':None,
            'basis':'simulated paper outcomes net of estimated costs (commission, spread-based slippage, financing modes 1/5); no broker fills; unknown paths excluded and counted separately'}
def snapshot(store):
    models=store.models();signals=store.signals(1000);outcomes=store.outcomes();groups={}
    for dimension,get in [('lab',lambda s:s['lab']),('strategy',lambda s:s['lab']+':'+s['model_key']),('model_version',lambda s:s['lab']+':'+s['model_key']+'@'+s['model_version']),
                          ('market',lambda s:s['symbol']),('session',lambda s:s.get('session','UNKNOWN')),
                          ('timeframe',lambda s:s['timeframe']),('planned_rr',lambda s:str(round(s.get('planned_rr') or 0,1))),
                          ('realized_paper_r',lambda s:'UNRESOLVED' if outcomes.get(s['signal_id'],{}).get('simulated_net_r') is None else str(round(outcomes[s['signal_id']]['simulated_net_r'],1)))]:
        collection=defaultdict(list)
        for s in signals:collection[get(s)].append(s)
        groups[dimension]={key:metrics(value,outcomes) for key,value in collection.items()}
    approval=store.delivery_approval()
    from .telegram import delivery_enabled
    tiers=collections_tier(signals,store)
    groups['evidence_tier']={key:metrics(value,outcomes) for key,value in tiers.items()}
    return {'mode':'EXPERIMENTAL_PAPER_SIGNALS','telegram_mode':'EXPERIMENTAL_APPROVED' if approval and delivery_enabled() else 'DRY_RUN',
            'outbound_activation_approved':bool(approval),'delivery_approval':approval,'production_models':[],
            'diagnostics':__import__('quant_live.diagnostics',fromlist=['diagnostics']).diagnostics(store),
            'leaderboard':__import__('quant_live.leaderboard',fromlist=['leaderboard']).leaderboard(store,signals,outcomes),
            'labs':[{'id':lab,'name':name,'status':'READY' if any(m['lab']==lab for m in models) else 'PENDING_ACTUAL_AI_MODEL',
                     'models':[{k:m[k] for k in ('key','version','status','scan_enabled','alert_enabled','sha')}|{'name':m['manifest']['name'],'classification':'EXPERIMENTAL','evidence_tier':store.tier(m['lab'],m['key'],m['version']),'timeframe':m['manifest']['timeframe'],'instruments':m['manifest']['instruments'],'authorship':m['manifest']['authorship'],'performance':groups['model_version'].get(m['lab']+':'+m['key']+'@'+m['version'],metrics([],{}))} for m in models if m['lab']==lab],
                     'performance':groups['lab'].get(lab,metrics([],{}))} for lab,name in LAB_NAMES.items()],
            'signals':[{**s,'outcome':outcomes.get(s['signal_id'])} for s in signals[:100]],'performance':metrics(signals,outcomes),
            'breakdown':groups,'outbox':[{**r,'body':__import__('json').loads(r['body'])} for r in store.outbox()],
            'verified_models':[],'scope':'latest 1000 detected signals; experimental and verified never pooled'}

def collections_tier(signals,store):
    """Research-only and paper-candidate cohorts are reported separately, never pooled."""
    scope={(i['lab'],i['key'],i['version']):i['tier'] for i in (store.delivery_approval() or {}).get('scope',[])}
    out=defaultdict(list)
    for s in signals:out[scope.get((s['lab'],s['model_key'],s['model_version']),'UNAPPROVED_DRY_RUN')].append(s)
    return out
