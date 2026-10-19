"""Actual executable model, collector boundary, durable lifecycle and dry-run transport."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quant_live import service
from quant_live.adapter import from_collector,immutable
from quant_live.fixtures import ASOF,snapshot,raw_fixture,normalizer,future_bar
from quant_live.execution import Plan,simulate
from quant_live.model_host import execute,validate_source
from quant_live.runtime import Runtime,register_codex,qualify,bounded_model
from quant_live.store import Store
from quant_live.telegram import ExperimentalNotifier,ApprovedTelegramAdapter
from quant_live.report import snapshot as report

class QuantLiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);register_codex(self.store)
        self.model=self.store.models()[0];self.data=snapshot()
        self.decision=execute(self.model['source'],self.data)[0]
    def signal(self):
        s,reason=qualify(self.data,self.model,self.decision,ASOF);self.assertIsNone(reason);return s
    def runner(self,*args):return {'status':'COMPLETE','decisions':[self.decision]}
    def test_actual_codex_bounded_worker(self):
        result=Runtime(self.store).process(self.data,ASOF)
        self.assertEqual(result['status'],'COMPLETE');self.assertEqual(len(result['signals']),1,result)
        limits=result['runs'][0]['resources'];self.assertTrue(limits['enforced']);self.assertEqual(limits['memory_limit_mb'],192)
        self.assertEqual(limits['cpu_cap_percent'],15);self.assertEqual(limits['max_processes'],1)
        self.assertEqual(self.store.outbox()[0]['state'],'DRY_RUN');self.assertEqual(result['outbound_calls'],0)
    def test_read_only_and_no_io(self):
        with self.assertRaises(TypeError):immutable(self.data)['quote']['ask']=1
        for source in ['import MetaTrader5\ndef detect(s):return []','import os\ndef detect(s):return []','def detect(s):return open("secret")','def detect(s):return s.__class__']:
            with self.assertRaises(ValueError):validate_source(source)
        with self.assertRaises(TypeError):execute('def detect(s):\n s["quote"]["ask"]=1\n return []',self.data)
    def test_parent_timeout_bounds_infinite_model(self):
        source='def detect(s):\n while True: pass'
        m={**self.model,'source':source,'sha':hashlib.sha256(source.encode()).hexdigest()}
        started=time.monotonic();r=bounded_model(self.store,m,self.data)
        self.assertNotEqual(r['status'],'COMPLETE');self.assertLess(time.monotonic()-started,8)
    def test_collector_spread_and_time_fail_closed(self):
        frames,q,meta=raw_fixture();del frames['M15'][0]['spread_points']
        bad=from_collector('EURUSD','EURUSD',frames,q,meta,'UTC',normalizer)
        self.assertEqual(bad['frames']['M15'],[])
        bad=from_collector('EURUSD','EURUSD',*raw_fixture(),'UNKNOWN',normalizer)
        self.assertFalse(bad['time_verified'])
    def test_future_forming_nan_and_unsorted_rejected(self):
        frames,q,meta=raw_fixture();frames['M15'].append({**frames['M15'][-1],'time':ASOF})
        good=from_collector('EURUSD','EURUSD',frames,q,meta,'UTC',normalizer)
        self.assertEqual(len(good['frames']['M15']),300)
        frames['M15'][0]['high']=float('nan')
        bad=from_collector('EURUSD','EURUSD',frames,q,meta,'UTC',normalizer)
        self.assertEqual(bad['frames']['M15'],[])
    def test_quality_gates(self):
        variants=[('time_verified',False,'UNVERIFIED_TIME'),('asof',ASOF-61,'STALE_SNAPSHOT')]
        for field,value,reason in variants:
            d=copy.deepcopy(self.data);d[field]=value;self.assertEqual(qualify(d,self.model,self.decision,ASOF)[1],reason)
        for field,value,reason in [('tick_at',ASOF-31,'STALE_OR_FUTURE_QUOTE'),('bid',-1,'INVALID_QUOTE')]:
            d=copy.deepcopy(self.data);d['quote'][field]=value;self.assertEqual(qualify(d,self.model,self.decision,ASOF)[1],reason)
        for field,value,reason in [('tradable_long',False,'INSTRUMENT_NOT_TRADABLE'),('commission_price',None,'COSTS_UNVERIFIED'),('tick_size',0,'TICK_SIZE_UNAVAILABLE')]:
            d=copy.deepcopy(self.data);d['metadata'][field]=value;self.assertEqual(qualify(d,self.model,self.decision,ASOF)[1],reason)
        for changes in [{'stop_loss':102},{'take_profit':99},{'atr':float('nan')},{'take_profit':100.5}]:
            self.assertIsNotNone(qualify(self.data,self.model,{**self.decision,**changes},ASOF)[1])
        d=copy.deepcopy(self.data);d['frames']['H1']=[]
        self.assertEqual(qualify(d,self.model,self.decision,ASOF)[1],'STALE_OR_MISSING_MODEL_CONTEXT')
    def test_existing_scanner_handoff_reuses_collected_frames(self):
        import test_market_data as existing
        from types import SimpleNamespace
        class Broker(existing.FakeBroker):
            def symbol_info(self,name):return SimpleNamespace(last=0,point=.01,trade_tick_size=.01,trade_mode=4)
        broker=Broker({'EURUSD':'EURUSD'})
        with mock.patch.object(existing.main.quant_live_service,'enabled',return_value=True),mock.patch.object(existing.main.quant_live_service,'requirements',return_value={}),mock.patch.object(existing.main.quant_live_service,'offer') as offered:
            markets,_=existing.run_scan(broker,watchlist=['EURUSD'])
        self.assertEqual(len(markets),1);offered.assert_called_once()
        args=offered.call_args.args;self.assertEqual(args[:2],('EURUSD','EURUSD'))
        self.assertIn('spread_points',args[2]['M15'][0]);self.assertTrue(args[4]['tradable_long'])
        self.assertEqual(sum(tf==15 for _,tf,_ in broker.requests),1)
        self.assertEqual(sum(tf==60 for _,tf,_ in broker.requests),1)
    def test_shared_consumer_thread_actual_model_and_single_start(self):
        import threading
        from collections import OrderedDict
        stop=threading.Event();at=time.time();frames,quote,meta=raw_fixture(at)
        with mock.patch.dict(os.environ,{'TRADEDEN_QUANT_LIVE_ENABLED':'1'}),mock.patch.object(service,'store',return_value=self.store),mock.patch.object(service,'_thread',None),mock.patch.object(service,'_runtime',None),mock.patch.object(service,'_pending',OrderedDict()),mock.patch.object(service,'_last',{'running':False,'overwritten_snapshots':0}):
            worker=service.start(stop)
            try:
                self.assertIs(service.start(stop),worker)
                service.offer('EURUSD','EURUSD.TEST',frames,quote,meta,'UTC',normalizer)
                until=time.monotonic()+7
                while time.monotonic()<until:
                    previews=self.store.outbox()
                    if previews and previews[0]['state']=='DRY_RUN':break
                    time.sleep(.05)
                self.assertEqual(len(self.store.signals()),1,service.status())
                self.assertEqual(self.store.outbox()[0]['state'],'DRY_RUN')
                self.assertFalse(service.status()['outbound_activation_approved'])
                observed=service.status()['latest_inputs']['EURUSD']
                self.assertEqual(observed['source'],'MT5_SHARED_COLLECTOR')
                self.assertLessEqual(observed['frames']['M15']['last_close_at'],observed['asof'])
                self.assertTrue(observed['last_model_runs'][0]['resources']['enforced'])
            finally:stop.set();worker.join(7)
            self.assertFalse(worker.is_alive())
    def test_duplicates_restart_and_providers_pending(self):
        first=Runtime(self.store,self.runner).process(self.data,ASOF);self.assertEqual(len(first['signals']),1)
        reopened=Store(self.tmp.name);reopened.recover();second=Runtime(reopened,self.runner).process(self.data,ASOF)
        self.assertEqual(second['signals'],[]);self.assertEqual(len(reopened.outbox()),1)
        labs=report(reopened)['labs'];self.assertEqual([l['status'] for l in labs],['READY','PENDING_ACTUAL_AI_MODEL','PENDING_ACTUAL_AI_MODEL'])
        self.assertEqual(report(reopened)['verified_models'],[])
    def test_immutable_identity_and_no_self_verification(self):
        with self.assertRaises(ValueError):self.store.register(self.model['manifest'],self.model['source']+'\n# changed',self.model['manifest']['authorship'])
        with self.assertRaises(ValueError):self.store.set_status('codex',self.model['key'],self.model['version'],'VERIFIED')
    def test_durable_lease_and_crash_recovery(self):
        self.assertTrue(self.store.lease('one',time.time(),30));self.assertFalse(self.store.lease('two',time.time(),30))
        self.store.claim('crashed',ASOF);self.assertFalse(self.store.recover());self.store.release('one');self.assertTrue(self.store.recover())
        with self.store.db() as c:self.assertEqual(c.execute('SELECT state FROM runs WHERE marker="crashed"').fetchone()[0],'INTERRUPTED')
        s=self.signal();self.store.record(s,True);self.store.queue_message(s['signal_id'],'preview',ASOF)
        with self.store.db() as c:c.execute('UPDATE outbox SET state="IN_FLIGHT"')
        self.store.recover();self.assertEqual(self.store.outbox()[0]['state'],'DELIVERY_UNKNOWN')
    def test_disabled_archived_and_expired_suppression(self):
        s=self.signal();self.store.record(s,True);self.store.queue_message(s['signal_id'],'preview',ASOF)
        self.store.set_status('codex',self.model['key'],self.model['version'],'ARCHIVED')
        fake=mock.Mock();ExperimentalNotifier(self.store,fake,'unused').process(ASOF)
        fake.send_message.assert_not_called();self.assertEqual(self.store.outbox()[0]['state'],'SUPPRESSED')
        self.assertEqual(Runtime(self.store,self.runner).process(self.data,ASOF)['signals'],[])
    def test_legacy_flags_cannot_enable_delivery(self):
        fake=mock.Mock();s=self.signal();self.store.record(s,True);self.store.queue_message(s['signal_id'],'preview',ASOF)
        with mock.patch.dict(os.environ,{'TRADING_HUB_TELEGRAM_ENABLED':'1','TRADEDEN_QUANT_LIVE_ENABLED':'1'}):ExperimentalNotifier(self.store,fake,'unused').process(ASOF)
        fake.send_message.assert_not_called();self.assertEqual(self.store.outbox()[0]['state'],'DRY_RUN')
        with self.assertRaises(PermissionError):ApprovedTelegramAdapter(fake,'unused').send('preview')
    def test_recover_orphan_preview_without_replay(self):
        s=self.signal();self.store.record(s,True);self.assertEqual(self.store.outbox(),[])
        self.store.recover();self.store.recover();self.assertEqual(len(self.store.outbox()),1)
        ExperimentalNotifier(self.store).process(ASOF+121);self.assertEqual(self.store.outbox()[0]['state'],'EXPIRED')
    def test_disabling_during_worker_revokes_signal(self):
        def disable(*args):
            self.store.set_status('codex',self.model['key'],self.model['version'],'DISABLED')
            return self.runner()
        self.assertEqual(Runtime(self.store,disable).process(self.data,ASOF)['signals'],[])
        self.assertEqual(self.store.outbox(),[])
    def test_outcomes_no_missing_win_and_corrections(self):
        s=self.signal();self.store.record(s,True);runtime=Runtime(self.store)
        runtime.resolve(s['symbol'],ASOF+900);o=self.store.outcomes()[s['signal_id']];self.assertIsNone(o['simulated_net_r'])
        bar=future_bar(s);self.store.add_candles({'symbol':s['symbol'],'frames':{'M15':[bar]},'asof':ASOF+900})
        runtime.resolve(s['symbol'],ASOF+900);o=self.store.outcomes()[s['signal_id']];self.assertEqual(o['status'],'TP');self.assertGreater(o['simulated_net_r'],3)
        self.assertIsNone(o['actual_realized_r']);self.assertEqual(report(self.store)['performance']['resolved'],1)
        revised={**bar,'high':bar['high']+.1};self.store.add_candles({'symbol':s['symbol'],'frames':{'M15':[revised]},'asof':ASOF+901})
        runtime.resolve(s['symbol'],ASOF+901);o=self.store.outcomes()[s['signal_id']];self.assertEqual(o['status'],'INCOMPLETE');self.assertIsNone(o['simulated_net_r'])
        self.assertGreaterEqual(o['revision'],3)
    def test_tie_and_partial_entry_ambiguous(self):
        s=self.signal();p=Plan(s['signal_id'],s['symbol'],'LONG',ASOF,ASOF,s['entry'],s['stop_loss'],s['take_profit'],ASOF+3600,s['risk'],s['spread'])
        bar=future_bar(s,'BOTH');self.assertEqual(simulate(p,[bar],[],ASOF+900,0,{'swap_mode':0})['status'],'AMBIGUOUS')
        partial=Plan(p.signal_id,p.symbol,p.direction,ASOF,ASOF+30,p.entry,p.stop_loss,p.take_profit,p.deadline,p.risk,p.entry_spread)
        self.assertEqual(simulate(partial,[bar],[],ASOF+900,0,{'swap_mode':0})['status'],'INCOMPLETE')
    def test_resolution_keeps_signals_older_than_dashboard_window(self):
        s=self.signal();self.store.record(s,True)
        with self.store.db() as c:
            for i in range(1005):
                c.execute('INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?)',(f'newer_{i}','test','unused','1.0.0','OTHER','M15',ASOF+i+1,ASOF+i+1,'CLOSED','{}'))
        self.assertNotIn(s['signal_id'],[r.get('signal_id') for r in self.store.signals(1000)])
        self.store.add_candles({'symbol':s['symbol'],'frames':{'M15':[future_bar(s)]},'asof':ASOF+900})
        Runtime(self.store).resolve(s['symbol'],ASOF+900)
        self.assertEqual(self.store.outcomes()[s['signal_id']]['status'],'TP')
    def test_api_owner_only(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from quant_live.api import router
        app=FastAPI();app.include_router(router)
        with mock.patch('quant_live.api.service.store',return_value=self.store),mock.patch.dict(os.environ,{'TRADING_HUB_AUTH_MODE':'private'}):
            with TestClient(app,client=('127.0.0.1',1234)) as client:self.assertEqual(client.get('/api/quant-labs/live').status_code,200)
            with TestClient(app,client=('192.0.2.1',1234)) as client:self.assertEqual(client.get('/api/quant-labs/live').status_code,403)
            with mock.patch.dict(os.environ,{'TRADING_HUB_AUTH_MODE':'oidc'}):
                with TestClient(app,client=('127.0.0.1',1234)) as client:self.assertEqual(client.get('/api/quant-labs/live').status_code,403)

if __name__=='__main__':unittest.main()
