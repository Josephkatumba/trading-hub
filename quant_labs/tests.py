"""Isolated milestone tests, including real Windows resource enforcement."""
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from .control import ControlPlane,LABS
from .data import snapshot,SharedData,digest,canonical
from .frozen import VERSION_DIR,verify
from .evaluation.v1.engine import evaluate
from .evaluation.v1.metrics import summarize
from .queue import run_one,run_process
from .preview import server,export

BASE=Path(__file__).resolve().parent
def spec(key='contract'):
    return {'id':key,'version':'1.0.0','name':'Contract fixture','hypothesis':'Infrastructure test only; no edge claim.',
            'entry_conditions':'Known candle open','exit_conditions':'One-hour time exit or first barrier','stop_loss_method':'Fixed loss-side fixture level',
            'take_profit_method':'2R fixture level','risk_model':'One planned risk unit','intended_conditions':'Synthetic fixture',
            'limitations':'Not a trading strategy','timeframe':'H1','declared_trials':1}
def fixture_cache(folder):
    folder.mkdir();start=datetime(2026,5,4,tzinfo=timezone.utc).timestamp();end=start+72*3600
    meta={'point':.00001,'tick_size':.00001,'swap_mode':0,'swap_rollover3days':3}
    original={'end':datetime.fromtimestamp(end,timezone.utc).isoformat(),'basis':'test UTC fixture','symbols':{'EURUSD':{'meta':meta}}}
    (folder/'manifest.json').write_text(json.dumps(original))
    for tf,step in [('M1',60),('M15',900),('H1',3600)]:
        bars=[{'utc':t,'time':t,'open':100,'high':100.3,'low':99.7,'close':100,'spread':.02} for t in range(int(start),int(end),step)]
        with gzip.open(folder/f'EURUSD_{tf}.json.gz','wt') as f:json.dump(bars,f)
    return start

class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='tests_tmp',dir=BASE/'verification')
        self.root=Path(self.temp.name);self.start=fixture_cache(self.root/'cache')
        self.c=ControlPlane(self.root/'state');self.dataset=snapshot(self.root/'cache',self.c.root/'shared')
        self.identity=digest((VERSION_DIR/'freeze.json').read_bytes());self.c.initialize(self.dataset,self.identity)
        self.tokens=json.loads((self.c.root/'owner/credentials.json').read_text());self.operator=self.tokens['operator:owner']
        self.intents=[{'symbol':'EURUSD','direction':'LONG','signal_bar_closed_at':self.start+12*3600,'entry_at':self.start+12*3600,'stop_loss':99,'take_profit':102.06,'horizon_seconds':3600}]
    def tearDown(self):self.temp.cleanup()
    def register(self,lab='codex',key='contract'):
        return self.c.register(self.tokens['lab:'+lab],lab,spec(key),'# reviewable infrastructure source\n')
    def submit(self,lab='codex',key='contract'):
        return self.c.submit(self.tokens['lab:'+lab],lab,key,'1.0.0',self.intents)
    def test_three_separate_workspaces_credentials(self):
        self.assertEqual(len(set(self.tokens.values())),8)
        for lab in LABS:self.assertTrue((self.c.workspace(lab)/'registry.jsonl').exists())
    def test_cross_lab_registration_denied(self):
        with self.assertRaises(PermissionError):self.c.register(self.tokens['lab:codex'],'kimi',spec(),'x')
        self.assertEqual(self.c.public()['labs'][2]['strategies'],0)
    def test_same_id_allowed_in_each_lab_without_overwrite(self):
        for lab in LABS:self.register(lab)
        self.assertEqual([r['strategies'] for r in self.c.public()['labs']],[1,1,1])
    def test_strategy_versions_immutable(self):
        self.register()
        with self.assertRaises(sqlite3.IntegrityError):self.register()
    def test_invalid_strategy_path_rejected(self):
        s=spec();s['id']='../kimi/bad'
        with self.assertRaises(ValueError):self.c.register(self.tokens['lab:codex'],'codex',s,'x')
    def test_cross_lab_submission_denied(self):
        self.register('kimi')
        with self.assertRaises(PermissionError):self.c.submit(self.tokens['lab:codex'],'kimi','contract','1.0.0',self.intents)
    def test_own_credential_cannot_run_worker(self):
        with self.assertRaises(PermissionError):run_one(self.c,self.tokens['lab:codex'])
    def test_intents_cannot_supply_outcomes(self):
        self.register();bad=[{**self.intents[0],'r_multiple':7}]
        with self.assertRaises(ValueError):self.c.submit(self.tokens['lab:codex'],'codex','contract','1.0.0',bad)
    def test_future_and_nonfinite_intents_rejected(self):
        self.register();bad=[{**self.intents[0],'entry_at':float('nan')}]
        with self.assertRaises(ValueError):self.c.submit(self.tokens['lab:codex'],'codex','contract','1.0.0',bad)
    def test_duplicate_global_experiment_reused_not_overwritten(self):
        self.register();self.register('claude');a=self.submit();b=self.submit('claude')
        self.assertEqual(b['state'],'DUPLICATE');self.assertEqual(b['duplicate_of'],a['job'])
    def test_same_intents_account_identically_for_three_labs(self):
        data=SharedData(self.c.root/'shared',self.dataset)
        answers=[]
        for lab in LABS:answers.append(evaluate(data,{'strategy':spec(),'signals':self.intents,'lab':lab}))
        self.assertEqual(canonical(answers[0]),canonical(answers[1]));self.assertEqual(canonical(answers[1]),canonical(answers[2]))
        r=answers[0]['trades'][0];p=r['plan'];fill=r['normal']
        expected=(fill['exit_price']-fill['entry_price']-fill['commission_price']-fill['financing_price'])/p['risk']
        self.assertAlmostEqual(fill['r'],expected)
    def test_shared_data_no_writer_or_path_escape(self):
        data=SharedData(self.c.root/'shared',self.dataset)
        self.assertFalse(hasattr(data,'write'));self.assertEqual(data.read('../../owner','H1'),[])
        with self.assertRaises(ValueError):SharedData(self.c.root/'shared','../credentials')
    def test_changed_data_detected(self):
        data=SharedData(self.c.root/'shared',self.dataset);meta=next(iter(data.manifest['files'].values()))
        file=self.c.root/'shared/blobs'/(meta['sha256']+'.gz');file.chmod(0o666);file.write_bytes(b'corrupt')
        symbol,tf=next(k for k,v in data.manifest['files'].items() if v==meta).split('_')
        with self.assertRaises(ValueError):data.read(symbol,tf.split('.')[0])
    def test_frozen_evaluator_identity(self):
        self.assertEqual(verify(self.identity)['version'],'tradeden-shared-eval-1.0.0')
        with self.assertRaises(ValueError):verify('0'*64)
    def test_frozen_accounting_zero_unknown_win_rate(self):
        m=summarize([{'normal':{'status':'INCOMPLETE'},'plan':None}],0,86400)
        self.assertIsNone(m['win_rate']);self.assertIsNone(m['net_expectancy_r'])
    def test_pending_queue_quota(self):
        self.register()
        for index in range(8):
            s={**self.intents[0],'take_profit':103+index};self.c.submit(self.tokens['lab:codex'],'codex','contract','1.0.0',[s])
        with self.assertRaises(ValueError):self.submit()
    def test_pause_resume_persists(self):
        self.register();job=self.submit()['job'];self.c.pause(self.tokens['lab:codex'],'codex',job)
        self.assertEqual(self.c.public()['jobs'][0]['state'],'PAUSED')
        reopened=ControlPlane(self.c.root);reopened.resume(self.tokens['lab:codex'],'codex',job)
        self.assertEqual(reopened.public()['jobs'][0]['state'],'QUEUED')
    def test_cannot_pause_other_lab(self):
        self.register();job=self.submit()['job']
        with self.assertRaises(PermissionError):self.c.pause(self.tokens['lab:kimi'],'kimi',job)
    def test_checkpoint_matches_uninterrupted(self):
        data=SharedData(self.c.root/'shared',self.dataset);signals=[{**self.intents[0],'entry_at':self.start+x*3600,'signal_bar_closed_at':self.start+x*3600} for x in (12,15)]
        request={'strategy':spec(),'signals':signals};stored=[];counter=[0]
        def pause():counter[0]+=1;return counter[0]>1
        first=evaluate(data,request,save=stored.append,should_pause=pause)
        self.assertEqual(first['status'],'PAUSED')
        continued=evaluate(data,request,checkpoint=stored[-1]);full=evaluate(data,request)
        self.assertEqual(continued['periods'],full['periods']);self.assertEqual(continued['trades'],full['trades'])
    def test_global_pause_does_not_spawn_worker(self):
        self.register();self.submit();self.c.global_pause(self.operator,True)
        self.assertEqual(run_one(self.c,self.operator)['status'],'PAUSED')
    def test_pipeline_cannot_self_approve(self):
        self.register()
        for stage in ('INDEPENDENT_REVIEW','CEO_APPROVAL','PRODUCTION'):
            with self.assertRaises(PermissionError):self.c.transition(self.tokens['lab:codex'],'codex','contract','1.0.0',stage)
    def test_self_review_denied(self):
        self.register();job=self.submit()['job']
        with self.assertRaises(PermissionError):self.c.review(self.tokens['reviewer:codex'],job,'NEEDS_DATA','self review')
    def test_qualified_board_empty_no_forward_fabrication(self):
        self.assertEqual(self.c.public()['qualified_leaderboard'],[]);self.assertIsNone(self.c.public()['prospective_forward_results'])
    def test_actual_worker_limits_accounting_and_immutable_result(self):
        self.register();job=self.submit()['job'];answer=run_one(self.c,self.operator,wall_seconds=10,memory_mb=128)
        self.assertEqual(answer['status'],'COMPLETE',answer);self.assertTrue(answer['resources']['enforced'])
        self.assertEqual(answer['resources']['cpu_cap_percent'],20);self.assertEqual(answer['resources']['memory_limit_mb'],128)
        self.assertEqual(answer['resources']['max_processes'],1)
        with self.c.connect() as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE results SET body="{}" WHERE job=?',(job,))
        with self.assertRaises(PermissionError):self.c.review(self.tokens['lab:claude'],job,'NEEDS_DATA','wrong role')
        self.c.review(self.tokens['reviewer:claude'],job,'NEEDS_DATA','Independent fixture accounting checked; no forward evidence.')
        self.assertEqual(len(self.c.public()['reviews']),1)
    def test_real_memory_cap(self):
        r=run_process(self.root/'memory',{'probe':'memory','memory_mb':64,'cpu_percent':20,'cpu_seconds':5,'wall_seconds':5},5)
        self.assertEqual(r['status'],'RESOURCE_LIMIT')
    def test_real_hard_wall_timeout(self):
        started=time.monotonic();r=run_process(self.root/'timeout',{'probe':'timeout','memory_mb':64,'cpu_percent':20,'cpu_seconds':5,'wall_seconds':1},1)
        self.assertEqual(r['status'],'TIMED_OUT');self.assertLess(time.monotonic()-started,4)
    def test_local_dashboard_read_only(self):
        http=server(self.c,0);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(http.server_port)
        try:
            with urlopen(base+'/api/research') as response:state=json.load(response)
            self.assertEqual(len(state['labs']),3);self.assertNotIn('credentials',state)
            for req in (Request(base+'/api/research',data=b'{}',method='POST'),base+'/../owner/credentials.json'):
                try:urlopen(req)
                except HTTPError as exc:exc.close()
                else:self.fail('read-only route boundary failed')
            file=export(self.c,self.root/'dashboard.html');self.assertIn('type="application/json">{',file.read_text(encoding='utf-8'))
        finally:http.shutdown();http.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
