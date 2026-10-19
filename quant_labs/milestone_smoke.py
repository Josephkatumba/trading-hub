"""Real-data contract check attributed only to Codex; never a strategy evidence claim."""
from datetime import datetime,timezone
import json
from .bootstrap import setup,BASE
from .data import SharedData
from .queue import run_one
from .preview import export

def main():
    c=setup();tokens=json.loads((c.root/'owner/credentials.json').read_text(encoding='utf-8'))
    spec={'id':'evaluation_contract_smoke','version':'1.0.0','name':'Shared evaluator contract check',
          'hypothesis':'Infrastructure fixture only; tests planned 2R/3R/4R/5R/7R/9R accounting, not a trading edge.',
          'entry_conditions':'Fixed historical H1 noon closes after 1 September 2026; alternating direction.',
          'exit_conditions':'First barrier or 15-minute time exit.','stop_loss_method':'Prior 14 observed H1 ranges, minimum .1% of reference price.',
          'take_profit_method':'2R, 3R, 4R, 5R, 7R and 9R fixtures.','risk_model':'One planned risk unit; no overlapping same-symbol positions.',
          'intended_conditions':'Infrastructure verification only','limitations':'Not a strategy; excluded from research leaderboard.',
          'timeframe':'H1','declared_trials':1,'purpose':'INFRASTRUCTURE_TEST'}
    try:c.get_strategy('codex',spec['id'],spec['version'])
    except KeyError:c.register(tokens['lab:codex'],'codex',spec,'# Fixed infrastructure fixture. No signal research or profitability claim.\n')
    data=SharedData(c.root/'shared',c.settings()['dataset']);signals=[]
    for symbol in ['XAUUSD','EURUSD','GBPUSD','GBPJPY','BTCUSD','ETHUSD','NAS100','US500','GER40']:
        h1=data.read(symbol,'H1');m15={b['utc']:b for b in data.read(symbol,'M15')}
        eligible=[i for i,b in enumerate(h1) if b['utc']>=datetime(2026,9,1,tzinfo=timezone.utc).timestamp() and datetime.fromtimestamp(b['utc']+3600,timezone.utc).hour==12 and b['utc']+3600 in m15]
        for k,(i,rr) in enumerate(zip(eligible,[2,3,4,5,7,9])):
            at=h1[i]['utc']+3600;quote=m15[at];long=k%2==0
            entry=quote['open']+(quote['spread'] if long else 0)
            risk=max(entry*.001,sum(b['high']-b['low'] for b in h1[i-13:i+1])/14)
            signals.append({'symbol':symbol,'direction':'LONG' if long else 'SHORT','signal_bar_closed_at':at,'entry_at':at,
                            'stop_loss':entry+(-risk if long else risk),'take_profit':entry+(rr*risk if long else -rr*risk),'horizon_seconds':900})
    job=c.submit(tokens['lab:codex'],'codex',spec['id'],spec['version'],signals,'INFRASTRUCTURE_TEST')
    if job['state']=='QUEUED':answer=run_one(c,tokens['operator:owner'])
    else:answer={'job':job['job'],'status':job['state'],'duplicate_of':job['duplicate_of']}
    evidence={'kind':'INFRASTRUCTURE_TEST','lab':'codex','intent_count':len(signals),'result':answer,
              'claude_research_run':False,'kimi_research_run':False,'profitability_claim':False}
    (BASE/'verification/smoke.json').write_text(json.dumps(evidence,indent=2))
    export(c);print(json.dumps(evidence,indent=2))
if __name__=='__main__':main()
