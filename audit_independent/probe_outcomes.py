"""Adversarial pure-function probes. No MT5 connection, stores, or notifications."""
import datetime as dt
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import signal_outcomes as so
from strategy_bank import engine, rules

UTC=dt.timezone.utc
base=dt.datetime(2026,10,1,tzinfo=UTC).timestamp()
plan={'direction':'LONG','entry':100,'stop_loss':99,'take_profit':102}
def bar(t,low=99.5,high=100.5,close=100):
    return {'utc':base+t,'open':100,'high':high,'low':low,'close':close,'spread':0}
def resolve(start,m15,m1,end):
    return so.resolve(plan,dt.datetime.fromtimestamp(base+start,UTC),m15,m1,dt.datetime.fromtimestamp(base+end,UTC))
def main():
    cases={}
    # At the exact bar boundary the entry-minute stop is entirely post-entry.
    cases['boundary_entry_minute_stop']=resolve(0,[bar(0,98.5),bar(900,high=103)],[bar(0,98.5),bar(60),bar(900,high=103)],1800)
    # Missing earlier minutes must not establish the later target as first hit.
    cases['sparse_tie_minutes']=resolve(0,[bar(0),bar(900,98,103)],[bar(0),bar(60),bar(1740,high=103)],1800)
    # A minute beyond the observation clock cannot resolve an outcome.
    cases['future_in_confirmation_bar']=resolve(10,[bar(0,high=103)],[bar(0),bar(60,high=103)],30)
    cases['missing_path_before_hit']=resolve(0,[bar(0),bar(86400,high=103)],[],90000)
    cases['truncated_history_at_expiry']=resolve(0,[bar(0),bar(900)],[],8*86400)
    # Bank gate incorrectly accepts future quote ages.
    frames={'H1':[dict(bar(i*3600),open=100,high=101,low=99,close=100) for i in range(250)]}
    ctx=rules.Ctx('EURUSD',frames); i=249; now=ctx.close_utc('H1',i)
    spec={'timeframe':'H1','min_rr':1.5,'key':'probe','name':'probe','status':'RESEARCH'}
    sig,reason=engine.confirm(spec,rules.Decision('LONG',stop_atr=1,target_r=2),ctx,i,{'bid':100,'ask':100.01,'tick_age_seconds':-3600},now)
    cases['future_quote_accepted']={'accepted':sig is not None,'reason':reason}
    sig,reason=engine.confirm(spec,rules.Decision('LONG',stop_atr=1,target_r=2),ctx,i,{'bid':100,'ask':100.01,'tick_age_seconds':0},now-3600)
    cases['future_bar_accepted']={'accepted':sig is not None,'reason':reason}
    p=Path(__file__).with_name('probe_results.json'); p.write_text(json.dumps(cases,indent=2),encoding='utf-8')
    print(json.dumps(cases,indent=2))
if __name__=='__main__':main()
