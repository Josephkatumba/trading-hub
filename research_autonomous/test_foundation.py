import dataclasses
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from .foundation import Plan,simulate,fresh,confirmation_valid,alert_authorized,validate_bars,RevisionStore,financing
from .hypotheses import Features,SPECS
from .experiment import select_training,exposure_filter,summarize
from .lifecycle import transition_allowed,delivery_allowed
from .forward import detect

def bar(t,low=99.5,high=100.5,op=100,close=100,spread=0):
    return dict(utc=t,open=op,high=high,low=low,close=close,spread=spread)
def plan(**kw):
    values=dict(signal_id='test',symbol='EURUSD',direction='LONG',signal_bar_closed_at=0,entry_at=0,
                entry=100,stop_loss=99,take_profit=102,deadline=1800,risk=1,entry_spread=0)
    return Plan(**(values|kw))

class FoundationTests(unittest.TestCase):
    def sim(self,p,bars,minutes=(),asof=1800,**kw):return simulate(p,bars,list(minutes),asof,meta={'swap_mode':0},**kw)
    def test_boundary_entry_minute_stop(self):
        # Original resolver skipped minute zero and returned later TP.
        self.assertEqual(self.sim(plan(),[bar(0,98),bar(900,high=103)])['status'],'SL')
    def test_sparse_tie_cannot_invent_target(self):
        r=self.sim(plan(),[bar(0),bar(900,98,103)],[bar(1740,high=103)])
        self.assertEqual(r['status'],'AMBIGUOUS')
    def test_gap_before_hit_incomplete(self):
        self.assertEqual(self.sim(plan(deadline=90000),[bar(0),bar(86400,high=103)],asof=90000)['status'],'INCOMPLETE')
    def test_truncated_expiry_incomplete(self):
        self.assertEqual(self.sim(plan(deadline=7*86400),[bar(0),bar(900)],asof=8*86400)['status'],'INCOMPLETE')
    def test_future_minute_ignored(self):
        r=self.sim(plan(entry_at=10),[bar(0,high=103)],[bar(0),bar(60,high=103)],asof=30)
        self.assertEqual(r['status'],'PENDING')
    def test_future_entry_rejected(self):self.assertEqual(self.sim(plan(entry_at=2000),[bar(0)])['status'],'INVALID_PLAN')
    def test_partial_entry_touch_ambiguous(self):
        minutes=[bar(x) for x in range(0,900,60)];minutes[0]=bar(0,98)
        self.assertEqual(self.sim(plan(entry_at=10),[bar(0,98)],minutes)['status'],'AMBIGUOUS')
    def test_full_minutes_stop_before_target(self):
        minutes=[bar(x) for x in range(0,900,60)];minutes[1]=bar(60,98);minutes[2]=bar(120,high=103)
        self.assertEqual(self.sim(plan(),[bar(0,98,103)],minutes)['status'],'SL')
    def test_full_minutes_target_before_stop(self):
        minutes=[bar(x) for x in range(0,900,60)];minutes[1]=bar(60,high=103);minutes[2]=bar(120,98)
        self.assertEqual(self.sim(plan(),[bar(0,98,103)],minutes)['status'],'TP')
    def test_same_minute_both_ambiguous(self):
        minutes=[bar(x) for x in range(0,900,60)];minutes[1]=bar(60,98,103)
        self.assertEqual(self.sim(plan(),[bar(0,98,103)],minutes)['status'],'AMBIGUOUS')
    def test_missing_first_candle(self):self.assertEqual(self.sim(plan(),[bar(900,high=103)])['status'],'INCOMPLETE')
    def test_time_exit_requires_full_path(self):
        self.assertEqual(self.sim(plan(),[bar(0),bar(900)])['status'],'TIME_EXIT')
    def test_time_exit_short_ask(self):
        p=plan(direction='SHORT',stop_loss=101,take_profit=98)
        result=self.sim(p,[bar(0,spread=.1),bar(900,spread=.1)])
        self.assertAlmostEqual(result['r'],-.125)
    def test_short_ask_stop(self):
        p=plan(direction='SHORT',stop_loss=101,take_profit=98)
        self.assertEqual(self.sim(p,[bar(0,high=100.9,spread=.2)])['status'],'SL')
    def test_stop_gap_worse_fill(self):self.assertEqual(self.sim(plan(),[bar(0,98,100,98,99)])['r'],-2)
    def test_commission_reduces_r(self):self.assertAlmostEqual(self.sim(plan(),[bar(0,98)],commission=.1)['r'],-1.1)
    def test_stress_adverse(self):
        p=plan(entry=100.1,risk=1.1,entry_spread=.1)
        normal=self.sim(p,[bar(0,98,spread=.1)],commission=.1)
        stress=self.sim(p,[bar(0,98,spread=.1)],commission=.1,scale=2)
        self.assertLess(stress['r'],normal['r'])
    def test_future_quote_rejected(self):self.assertFalse(fresh(-3600))
    def test_unknown_and_nan_quote_rejected(self):
        for value in (None,float('nan'),float('inf'),'bad'):self.assertFalse(fresh(value))
    def test_future_bar_rejected(self):self.assertFalse(confirmation_valid(3600,0,0))
    def test_true_entry_delay_not_retroactive(self):
        p=plan(signal_bar_closed_at=0,entry_at=900)
        self.assertEqual(self.sim(p,[bar(0,98),bar(900)])['status'],'TIME_EXIT')
    def test_archived_revoked(self):
        self.assertFalse(alert_authorized('ARCHIVED','CEO-1'))
        self.assertFalse(alert_authorized('FORWARD_TESTING','CEO-1'))
        self.assertFalse(alert_authorized('QUALIFIED',None))
        self.assertTrue(alert_authorized('QUALIFIED','CEO-1'))
    def test_invalid_candles_and_duplicates(self):
        valid,rejected=validate_bars([bar(0),bar(0),bar(900,low=101),bar(1800)],900,1800)
        self.assertEqual(len(valid),1);self.assertEqual(sum(rejected.values()),3)
    def test_missing_spread_not_zero(self):
        b=bar(0);b.pop('spread');self.assertFalse(validate_bars([b],900,1800)[0])
    def test_future_candle_rejected(self):
        self.assertFalse(validate_bars([bar(3600)],900,1800)[0])
    def test_revision_append_idempotence(self):
        # Temporary directory explicitly inside isolated research workspace.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path=Path(folder)/'revisions.jsonl';store=RevisionStore(path)
            a=store.append('x',{'status':'SL'},{'version':'1'},prior_id='old')
            self.assertIsNone(store.append('x',{'status':'SL'},{'version':'1'}))
            b=store.append('x',{'status':'AMBIGUOUS'},{'version':'1'})
            self.assertEqual(b['supersedes'],a['revision_id']);self.assertEqual(b['revision'],2)
            self.assertEqual(len(path.read_text().splitlines()),2)
    def test_financing_unknown_currency_fails_closed(self):
        p=plan(entry_at=16*3600,deadline=2*86400)
        self.assertIsNone(financing(p,2*86400,{'swap_mode':3,'swap_long':-1}))
    def test_causal_features_prefix_invariance(self):
        rng=np.random.default_rng(19);closes=100+np.cumsum(rng.normal(0,.1,240))
        bars=[bar(i*3600,c-.2,c+.2,c,c) for i,c in enumerate(closes)]
        full=Features(bars);prefix=Features(bars[:181])
        self.assertAlmostEqual(full.atr[180],prefix.atr[180])
        self.assertAlmostEqual(full.med[180],prefix.med[180])
        for spec in SPECS:self.assertEqual(full.decide(spec.key,180),prefix.decide(spec.key,180))
    def test_portfolio_same_factor_and_unit_cap(self):
        trades=[{'symbol':s,'strategy':'a','plan':{'entry_at':0},'busy_until':900} for s in ['EURUSD','GBPUSD','BTCUSD','XAUUSD','NAS100']]
        chosen,rejected=exposure_filter(trades)
        self.assertEqual(len(chosen),3);self.assertEqual(rejected['portfolio_exposure'],2)
    def test_unknown_not_zero_return(self):
        r=summarize([{'normal':{'status':'INCOMPLETE'},'plan':{'entry_at':0}}],0,86400)
        self.assertIsNone(r['expectancy_r']);self.assertEqual(r['resolved'],0)
    def test_no_evidence_means_abstention(self):self.assertEqual(select_training([],True),({},{}))
    def test_m1_m15_disagreement_ambiguous(self):
        self.assertEqual(self.sim(plan(),[bar(0,98,103)],[bar(x) for x in range(0,900,60)])['status'],'AMBIGUOUS')
    def test_mismatched_risk_rejected(self):self.assertEqual(self.sim(plan(risk=2),[bar(0,98)])['status'],'INVALID_PLAN')
    def test_malformed_timestamp_rejected(self):self.assertFalse(confirmation_valid(None,0,0))
    def test_lifecycle_cannot_skip_forward(self):
        self.assertFalse(transition_allowed('BACKTEST','CEO_APPROVAL',{'ceo_approval':'x'}))
        self.assertFalse(transition_allowed('SHADOW_FORWARD_TEST','QUALIFICATION_REVIEW',{}))
        self.assertTrue(transition_allowed('SHADOW_FORWARD_TEST','QUALIFICATION_REVIEW',{'forward_evidence_id':'f1'}))
    def test_current_registry_demoted_overrides_old_approval(self):
        record={'to':'ARCHIVED','approval':'CEO-1'}
        self.assertFalse(delivery_allowed('s',lambda k:record,0,0,0))
        record['to']='APPROVED_EXPERIMENTAL'
        self.assertTrue(delivery_allowed('s',lambda k:record,0,0,0))
        record['to']='FORWARD_TESTING'
        self.assertFalse(delivery_allowed('s',lambda k:record,0,0,0))
    def test_forward_rejects_future_tick(self):
        bars=[bar(i*3600) for i in range(130)]
        snapshot={'symbol':'EURUSD','asof':130*3600,'quote':{'bid':100,'ask':100.01,'tick_at':131*3600},'frames':{'H1':bars}}
        plans,reason=detect(snapshot,{'tick_size':.00001})
        self.assertFalse(plans);self.assertIn('future',reason)

if __name__=='__main__':unittest.main()
