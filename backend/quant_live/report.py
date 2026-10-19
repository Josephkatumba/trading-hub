"""Paper-signal performance, with actual executed R explicitly unavailable."""
from collections import defaultdict,Counter
from .store import LAB_NAMES

def metrics(signals,outcomes):
    confirmed=[s for s in signals if s.get('confirmed')]
    resolved=[(s,outcomes[s['signal_id']]) for s in confirmed if outcomes.get(s['signal_id'],{}).get('simulated_net_r') is not None]
    rs=[o['simulated_net_r'] for s,o in sorted(resolved,key=lambda x:x[1].get('exit_at',0))]
    gains=sum(r for r in rs if r>0);loss=-sum(r for r in rs if r<0);eq=peak=dd=0
    for r in rs:eq+=r;peak=max(peak,eq);dd=max(dd,peak-eq)
    return {'detected':len(signals),'confirmed':len(confirmed),'resolved':len(rs),'unresolved':len(confirmed)-len(rs),
            'win_rate':sum(r>0 for r in rs)/len(rs) if rs else None,'net_paper_r':sum(rs) if rs else None,
            'net_expectancy_r':sum(rs)/len(rs) if rs else None,'profit_factor':gains/loss if loss else None,
            'max_realized_paper_drawdown_r':dd if rs else None,'actual_realized_r':None,
            'basis':'simulated net paper outcomes; no broker fills; unknown paths excluded and counted separately'}
def snapshot(store):
    models=store.models();signals=store.signals(1000);outcomes=store.outcomes();groups={}
    for dimension,get in [('lab',lambda s:s['lab']),('strategy',lambda s:s['lab']+':'+s['model_key']),('model_version',lambda s:s['lab']+':'+s['model_key']+'@'+s['model_version']),
                          ('market',lambda s:s['symbol']),('session',lambda s:s.get('session','UNKNOWN')),
                          ('timeframe',lambda s:s['timeframe']),('planned_rr',lambda s:str(round(s.get('planned_rr') or 0,1))),
                          ('realized_paper_r',lambda s:'UNRESOLVED' if outcomes.get(s['signal_id'],{}).get('simulated_net_r') is None else str(round(outcomes[s['signal_id']]['simulated_net_r'],1)))]:
        collection=defaultdict(list)
        for s in signals:collection[get(s)].append(s)
        groups[dimension]={key:metrics(value,outcomes) for key,value in collection.items()}
    return {'mode':'EXPERIMENTAL_PAPER_SIGNALS','telegram_mode':'DRY_RUN','outbound_activation_approved':False,
            'labs':[{'id':lab,'name':name,'status':'READY' if any(m['lab']==lab for m in models) else 'PENDING_ACTUAL_AI_MODEL',
                     'models':[{k:m[k] for k in ('key','version','status','scan_enabled','alert_enabled','sha')}|{'name':m['manifest']['name'],'classification':'EXPERIMENTAL','authorship':m['manifest']['authorship']} for m in models if m['lab']==lab],
                     'performance':groups['lab'].get(lab,metrics([],{}))} for lab,name in LAB_NAMES.items()],
            'signals':[{**s,'outcome':outcomes.get(s['signal_id'])} for s in signals[:100]],'performance':metrics(signals,outcomes),
            'breakdown':groups,'outbox':[{**r,'body':__import__('json').loads(r['body'])} for r in store.outbox()],
            'verified_models':[],'scope':'latest 1000 detected signals; experimental and verified never pooled'}
