"""Capability-scoped registries and persistent sequential queue.

This is application-level isolation. An unrestricted shell under the same Windows
account remains outside this boundary; use separate OS identities for hostile code.
Lab source is stored for review and NEVER executed by this control plane.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import uuid
from .data import canonical,digest,SharedData
from .frozen import verify

LABS={'codex':'Codex Quant Lab','claude':'Claude Quant Lab','kimi':'Kimi Quant Lab'}
STAGES=('IDEA','RESEARCH','BACKTEST','HISTORICAL_VALIDATION','SHADOW_FORWARD_TEST','INDEPENDENT_REVIEW','CEO_APPROVAL','PRODUCTION')
ID=re.compile(r'^[a-z][a-z0-9_-]{0,63}$');VERSION=re.compile(r'^\d+\.\d+\.\d+$')
REQUIRED=('name','hypothesis','entry_conditions','exit_conditions','stop_loss_method','take_profit_method','risk_model','intended_conditions','limitations','timeframe')
def now():return datetime.now(timezone.utc).isoformat()
def uid():return uuid.uuid4().hex

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

class ControlPlane:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/'control.sqlite3'
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS credentials(hash TEXT PRIMARY KEY,role TEXT NOT NULL,lab TEXT);
            CREATE TABLE IF NOT EXISTS strategies(lab TEXT,id TEXT,version TEXT,body TEXT,source TEXT,sha TEXT,created TEXT,PRIMARY KEY(lab,id,version));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,lab TEXT,strategy TEXT,version TEXT,kind TEXT,body TEXT,at TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,lab TEXT,strategy TEXT,version TEXT,state TEXT,body TEXT,fingerprint TEXT,duplicate_of TEXT,created TEXT,updated TEXT,segments INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS results(job TEXT PRIMARY KEY,lab TEXT,body TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,job TEXT,reviewer_lab TEXT,verdict TEXT,evidence TEXT,at TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS only_one_running_worker ON jobs(state) WHERE state='RUNNING';
            CREATE TRIGGER IF NOT EXISTS strategy_no_update BEFORE UPDATE ON strategies BEGIN SELECT RAISE(ABORT,'immutable strategy version');END;
            CREATE TRIGGER IF NOT EXISTS strategy_no_delete BEFORE DELETE ON strategies BEGIN SELECT RAISE(ABORT,'preserve failed strategies');END;
            CREATE TRIGGER IF NOT EXISTS result_no_update BEFORE UPDATE ON results BEGIN SELECT RAISE(ABORT,'append new evaluation revision');END;
            CREATE TRIGGER IF NOT EXISTS result_no_delete BEFORE DELETE ON results BEGIN SELECT RAISE(ABORT,'preserve performance records');END;
            ''')
    def connect(self):
        c=sqlite3.connect(self.db,timeout=5,factory=ClosingConnection);c.row_factory=sqlite3.Row;return c
    def initialize(self,dataset,evaluator):
        verify(evaluator);SharedData(self.root/'shared',dataset)
        tokens={}
        with self.connect() as c:
            if c.execute('SELECT 1 FROM settings WHERE key="dataset"').fetchone():raise ValueError('already initialized')
            for key,value in [('dataset',dataset),('evaluator',evaluator),('paused',False),('max_pending_per_lab',8),('max_segments_per_job',20)]:
                c.execute('INSERT INTO settings VALUES(?,?)',(key,json.dumps(value)))
            for role,lab in [('lab',x) for x in LABS]+[('reviewer',x) for x in LABS]+[('operator',None),('ceo',None)]:
                token=secrets.token_urlsafe(32);tokens[f'{role}:{lab or "owner"}']=token
                c.execute('INSERT INTO credentials VALUES(?,?,?)',(digest(token.encode()),role,lab))
        for lab in LABS:
            folder=self.workspace(lab);folder.mkdir(parents=True,exist_ok=True)
            for name in ('registry.jsonl','experiments.jsonl','performance.jsonl'):(folder/name).touch(exist_ok=True)
            # Only this lab's development credential is put in its workspace.
            (folder/'.lab-token').write_text(tokens['lab:'+lab])
        secret_dir=self.root/'owner';secret_dir.mkdir(exist_ok=True)
        (secret_dir/'credentials.json').write_text(json.dumps(tokens,indent=2))
        return {'laboratories':list(LABS),'credentials_provisioned':True}
    def settings(self):
        with self.connect() as c:return {r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}
    def actor(self,token):
        with self.connect() as c:r=c.execute('SELECT role,lab FROM credentials WHERE hash=?',(digest(str(token).encode()),)).fetchone()
        if not r:raise PermissionError('invalid capability')
        return dict(r)
    def own(self,token,lab,roles=('lab',)):
        a=self.actor(token)
        if a['role'] not in roles or a['lab']!=lab:raise PermissionError('laboratory boundary denied')
        return a
    def operator(self,token):
        if self.actor(token)['role']!='operator':raise PermissionError('operator capability required')
    def workspace(self,lab):
        if lab not in LABS:raise ValueError('unknown lab')
        parent=(self.root/'labs').resolve();path=parent/lab
        if not parent.is_relative_to(self.root) or (path.exists() and path.resolve()!=path):raise PermissionError('workspace junction escapes laboratory root')
        return path
    def append_export(self,lab,name,row):
        folder=self.workspace(lab);path=folder/name
        if name not in ('registry.jsonl','experiments.jsonl','performance.jsonl') or (path.exists() and path.resolve().parent!=folder.resolve()):raise PermissionError('export path escapes laboratory')
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,allow_nan=False)+'\n')
    def event(self,c,lab,strategy,version,kind,body):
        c.execute('INSERT INTO events(lab,strategy,version,kind,body,at) VALUES(?,?,?,?,?,?)',(lab,strategy,version,kind,json.dumps(body),now()))
    def register(self,token,lab,spec,source):
        self.own(token,lab)
        if not ID.fullmatch(spec.get('id','')) or not VERSION.fullmatch(spec.get('version','')):raise ValueError('invalid strategy ID/version')
        if any(not isinstance(spec.get(k),str) or not spec[k].strip() for k in REQUIRED):raise ValueError('complete strategy specification required')
        if spec['timeframe'] not in ('M1','M15','H1','H4','D1'):raise ValueError('unsupported timeframe data')
        if not isinstance(source,str) or not source.strip() or len(source.encode())>262144:raise ValueError('reviewable source is required, maximum 256 KiB')
        trials=spec.get('declared_trials',1)
        if not isinstance(trials,int) or not 1<=trials<=100000:raise ValueError('declare all prior variants attempted')
        encoded=canonical(spec)
        if len(encoded)>65536:raise ValueError('strategy specification too large')
        sha=digest(source.encode());record={**spec,'lab':lab,'source_sha256':sha,'created_at':now()}
        with self.connect() as c:
            c.execute('INSERT INTO strategies VALUES(?,?,?,?,?,?,?)',(lab,spec['id'],spec['version'],encoded.decode(),source,sha,record['created_at']))
            self.event(c,lab,spec['id'],spec['version'],'IDEA',{'source_sha256':sha})
        self.append_export(lab,'registry.jsonl',record);return record
    def get_strategy(self,lab,sid,version):
        with self.connect() as c:r=c.execute('SELECT * FROM strategies WHERE lab=? AND id=? AND version=?',(lab,sid,version)).fetchone()
        if not r:raise KeyError('strategy version not registered')
        return dict(r)
    def submit(self,token,lab,sid,version,signals,purpose='RESEARCH'):
        self.own(token,lab);record=self.get_strategy(lab,sid,version);settings=self.settings();verify(settings['evaluator'])
        if purpose not in ('RESEARCH','INFRASTRUCTURE_TEST'):raise ValueError('unverified prospective submissions are not enabled')
        if not isinstance(signals,list) or not 1<=len(signals)<=2000:raise ValueError('1..2000 intents per bounded experiment')
        shared=SharedData(self.root/'shared',settings['dataset']);normalized=[]
        required={'symbol','direction','signal_bar_closed_at','entry_at','stop_loss','take_profit','horizon_seconds'}
        for s in signals:
            if not isinstance(s,dict) or set(s)!=required:raise ValueError('only signal intent fields accepted; no supplied outcomes, code or output paths')
            if s['direction'] not in ('LONG','SHORT') or f"{s['symbol']}_M15.json.gz" not in shared.manifest['files']:raise ValueError('unsupported market or direction')
            for k in required-{'symbol','direction'}:
                if isinstance(s[k],bool) or not isinstance(s[k],(int,float)) or not math.isfinite(s[k]):raise ValueError('finite numeric intent fields required')
            if s['entry_at']!=s['signal_bar_closed_at'] or s['entry_at']%60 or s['entry_at']<=0 or not 60<=s['horizon_seconds']<=604800:raise ValueError('invalid historical entry semantics/horizon')
            if s['stop_loss']<=0 or s['take_profit']<=0:raise ValueError('positive levels required')
            normalized.append({k:s[k] for k in sorted(required)})
        normalized.sort(key=lambda s:(s['symbol'],s['entry_at'],s['direction'],s['stop_loss'],s['take_profit']))
        if len({canonical(s) for s in normalized})!=len(normalized):raise ValueError('duplicate intent in experiment')
        fingerprint=digest(canonical({'signals':normalized,'dataset':settings['dataset'],'evaluator':settings['evaluator'],'timeframe':json.loads(record['body'])['timeframe'],'purpose':purpose}))
        job=uid();created=now()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            pending=c.execute('SELECT count(*) FROM jobs WHERE lab=? AND state IN ("QUEUED","RUNNING","PAUSED")',(lab,)).fetchone()[0]
            if pending>=settings['max_pending_per_lab']:raise ValueError('lab queue quota reached')
            old=c.execute('SELECT id FROM jobs WHERE fingerprint=? AND state!="DUPLICATE" ORDER BY created LIMIT 1',(fingerprint,)).fetchone()
            request={'strategy':json.loads(record['body']),'signals':normalized,'dataset':settings['dataset'],'evaluator':settings['evaluator'],
                     'source_sha256':record['sha'],'purpose':purpose,'lab':lab,'strategy_registered_at':record['created']}
            state='DUPLICATE' if old else 'QUEUED'
            c.execute('INSERT INTO jobs(id,lab,strategy,version,state,body,fingerprint,duplicate_of,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (job,lab,sid,version,state,json.dumps(request),fingerprint,old['id'] if old else None,created,created))
            self.event(c,lab,sid,version,'RESEARCH',{'job':job,'state':state,'fingerprint':fingerprint})
        export={'job':job,'strategy':sid,'version':version,'state':state,'at':created,'duplicate_of':old['id'] if old else None}
        self.append_export(lab,'experiments.jsonl',export);return export
    def pause(self,token,lab,job):
        self.own(token,lab)
        with self.connect() as c:
            r=c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not r or r['lab']!=lab:raise PermissionError('cannot pause another laboratory experiment')
            if r['state']=='RUNNING':
                runtime=self.root/'runtime'/job;runtime.mkdir(parents=True,exist_ok=True);(runtime/'pause').touch()
            elif r['state']=='QUEUED':c.execute('UPDATE jobs SET state="PAUSED",updated=? WHERE id=?',(now(),job))
            else:raise ValueError('job is not running or queued')
            self.event(c,lab,r['strategy'],r['version'],'PAUSE_REQUESTED',{'job':job})
    def resume(self,token,lab,job):
        self.own(token,lab)
        with self.connect() as c:
            r=c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not r or r['lab']!=lab:raise PermissionError('cannot resume another laboratory experiment')
            if r['state'] not in ('PAUSED','TIMED_OUT'):raise ValueError('job cannot resume')
            pending=c.execute('SELECT count(*) FROM jobs WHERE lab=? AND state IN ("QUEUED","RUNNING","PAUSED")',(lab,)).fetchone()[0]
            if r['state']=='TIMED_OUT' and pending>=self.settings()['max_pending_per_lab']:raise ValueError('lab queue quota reached')
            pause=self.root/'runtime'/job/'pause'
            if pause.exists():pause.unlink()
            c.execute('UPDATE jobs SET state="QUEUED",updated=? WHERE id=?',(now(),job))
            self.event(c,lab,r['strategy'],r['version'],'RESUMED',{'job':job})
    def global_pause(self,token,paused):
        self.operator(token)
        with self.connect() as c:
            c.execute('UPDATE settings SET value=? WHERE key="paused"',(json.dumps(bool(paused)),))
            if paused:
                for r in c.execute('SELECT id FROM jobs WHERE state="RUNNING"'):
                    folder=self.root/'runtime'/r['id'];folder.mkdir(parents=True,exist_ok=True);(folder/'pause').touch()
    def transition(self,token,lab,sid,version,stage,evidence=None):
        self.own(token,lab);self.get_strategy(lab,sid,version);evidence=evidence or {}
        with self.connect() as c:
            old=c.execute('SELECT kind FROM events WHERE lab=? AND strategy=? AND version=? AND kind IN ("IDEA","RESEARCH","BACKTEST","HISTORICAL_VALIDATION","SHADOW_FORWARD_TEST","REJECTED") ORDER BY seq DESC LIMIT 1',(lab,sid,version)).fetchone()['kind']
            if stage=='REJECTED':
                if not evidence.get('reason'):raise ValueError('rejection reason required')
            elif (old,stage)==('IDEA','RESEARCH'):pass
            elif (old,stage) in (('RESEARCH','BACKTEST'),('BACKTEST','HISTORICAL_VALIDATION')):
                r=c.execute('SELECT r.body FROM results r JOIN jobs j ON j.id=r.job WHERE j.lab=? AND j.strategy=? AND j.version=? AND j.state="COMPLETE"',(lab,sid,version)).fetchone()
                if not r:raise ValueError('shared evaluator evidence required')
            elif (old,stage)==('HISTORICAL_VALIDATION','SHADOW_FORWARD_TEST'):raise ValueError('prospective feed/commitment integration not activated')
            else:raise PermissionError('cannot skip lifecycle or self-approve independent/CEO/production stages')
            self.event(c,lab,sid,version,stage,evidence)
        return stage
    def review(self,token,job,verdict,evidence):
        actor=self.actor(token)
        if actor['role']!='reviewer':raise PermissionError('independent reviewer capability required')
        if verdict not in ('REJECTED','NEEDS_DATA','REVIEW_PENDING_FORWARD') or not evidence.strip():raise ValueError('documented non-production verdict required')
        with self.connect() as c:
            r=c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not r or r['lab']==actor['lab']:raise PermissionError('a laboratory cannot review its own strategy')
            if r['state']!='COMPLETE':raise ValueError('completed evaluation required')
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?)',(uid(),job,actor['lab'],verdict,evidence,now()))
            self.event(c,r['lab'],r['strategy'],r['version'],'INDEPENDENT_REVIEW_NOTE',{'job':job,'reviewer':actor['lab'],'verdict':verdict})
    def public(self):
        with self.connect() as c:
            strategies=[dict(r) for r in c.execute('SELECT lab,id,version,body,sha,created FROM strategies')]
            jobs=[dict(r) for r in c.execute('SELECT id,lab,strategy,version,state,duplicate_of,created,updated,segments FROM jobs ORDER BY created DESC')]
            results=[dict(r) for r in c.execute('SELECT * FROM results')]
            reviews=[dict(r) for r in c.execute('SELECT job,reviewer_lab,verdict,evidence,at FROM reviews')]
            segments=[dict(r) for r in c.execute('SELECT lab,body,at FROM events WHERE kind="WORKER_SEGMENT"')]
            rejected={lab:c.execute('SELECT count(*) FROM events WHERE lab=? AND kind="REJECTED"',(lab,)).fetchone()[0] for lab in LABS}
        history={r['job']:json.loads(r['body']) for r in results};leaderboard=[];resources=[]
        for segment in segments:
            body=json.loads(segment['body']);resources.append({'lab':segment['lab'],'at':segment['at'],**body})
        for j in jobs:
            r=history.get(j['id'])
            if not r:continue
            if r.get('purpose')=='INFRASTRUCTURE_TEST':continue
            m=r['periods']['test']['normal'];stress=r['periods']['test']['stress']
            leaderboard.append({'lab':j['lab'],'strategy':j['strategy'],'version':j['version'],'job':j['id'],'metrics':m,'stress':stress,'certified':False,'review':'INDEPENDENT_REVIEW_REQUIRED'})
        declared=sum(json.loads(s['body']).get('declared_trials',1) for s in strategies)
        family=max(1,declared,len([j for j in jobs if j['state']!='DUPLICATE']))
        high=0
        for i,item in enumerate(sorted(leaderboard,key=lambda x:x['metrics']['weekly_sign_flip_p'])):
            high=max(high,min(1,(family-i)*item['metrics']['weekly_sign_flip_p']));item['holm_p']=high
        leaderboard.sort(key=lambda r:r['metrics']['net_expectancy_r'] if r['metrics']['net_expectancy_r'] is not None else -1e99,reverse=True)
        return {'generated_at':now(),'mode':'ISOLATED LOCAL PROTOTYPE','production_connected':False,'labs':[{'id':lab,'name':name,
                'strategies':sum(s['lab']==lab for s in strategies),'active_experiments':sum(j['lab']==lab and j['state'] in ('QUEUED','RUNNING','PAUSED') for j in jobs),
                'rejected_experiments':rejected[lab],'completed_experiments':sum(j['lab']==lab and j['state']=='COMPLETE' for j in jobs),
                'forward_status':'NOT_STARTED'} for lab,name in LABS.items()],
                'strategies':[{**s,'body':json.loads(s['body'])} for s in strategies],'jobs':jobs,'research_leaderboard':leaderboard,
                'qualified_leaderboard':[],'reviews':reviews,'resources':resources,'settings':self.settings(),
                'multiple_testing_family':family,'prospective_forward_results':None,'historical_performance':history,
                'qualification_note':'Research metrics are not profitability certification. Forward evidence, independent review and CEO approval are required.'}
