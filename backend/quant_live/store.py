"""Durable model identities, signal transitions, outcome revisions and outbox."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from .adapter import canonical
from .model_host import validate_source

LAB_NAMES={'codex':'Codex Quant Lab','claude':'Claude Quant Lab','kimi':'Kimi Quant Lab'}
# Evidence tiers for approved EXPERIMENTAL paper delivery. Neither is production.
TIERS={'PAPER_CANDIDATE':'EXPERIMENTAL','RESEARCH_ONLY':'EXPERIMENTAL · RESEARCH ONLY (no positive out-of-sample evidence)'}
# Independent outbound categories beside the experimental trade-signal approval ('delivery_approval').
CATEGORIES=('research_observations','intel_briefings')
PROJECT=Path(__file__).resolve().parents[2]
class Store:
    def __init__(self,folder):
        self.folder=Path(folder).resolve();self.folder.mkdir(parents=True,exist_ok=True);self.path=self.folder/'signals.sqlite3'
        with self.db() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS models(lab TEXT,key TEXT,version TEXT,body TEXT,source TEXT,sha TEXT,status TEXT,scan_enabled INTEGER,alert_enabled INTEGER,registered REAL,PRIMARY KEY(lab,key,version));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,signal TEXT,kind TEXT,body TEXT,at REAL);
            CREATE TABLE IF NOT EXISTS signals(id TEXT PRIMARY KEY,lab TEXT,model TEXT,version TEXT,symbol TEXT,timeframe TEXT,bar REAL,created REAL,state TEXT,body TEXT,UNIQUE(lab,model,version,symbol,bar));
            CREATE TABLE IF NOT EXISTS runs(marker TEXT PRIMARY KEY,state TEXT,at REAL,body TEXT);
            CREATE TABLE IF NOT EXISTS outcomes(seq INTEGER PRIMARY KEY AUTOINCREMENT,signal TEXT,body TEXT,sha TEXT,at REAL);
            CREATE TABLE IF NOT EXISTS outbox(signal TEXT PRIMARY KEY,state TEXT,message TEXT,body TEXT,updated REAL);
            CREATE TABLE IF NOT EXISTS candles(symbol TEXT,tf TEXT,utc REAL,body TEXT,PRIMARY KEY(symbol,tf,utc));
            CREATE TABLE IF NOT EXISTS candle_revisions(seq INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,tf TEXT,utc REAL,body TEXT,at REAL);
            CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY,owner TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            INSERT OR IGNORE INTO settings VALUES('delivery_approval','null');
            CREATE INDEX IF NOT EXISTS candle_conflicts ON candle_revisions(symbol,tf,utc);
            CREATE INDEX IF NOT EXISTS outcome_history ON outcomes(signal,seq);
            CREATE INDEX IF NOT EXISTS signal_recency ON signals(created DESC);
            CREATE INDEX IF NOT EXISTS pending_order ON signals(state,created,id);
            ''')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=3);c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()
    def register(self,manifest,source,authorship):
        lab,key,version=(manifest[k] for k in ('lab','key','version'))
        if lab not in LAB_NAMES or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',key) or not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('invalid model identity')
        if authorship.get('lab')!=lab or not authorship.get('session_reference'):raise ValueError('actual authorship session evidence required')
        validate_source(source)
        if manifest.get('timeframe') not in ('M1','M5','M15','H1','H4','D1'):raise ValueError('unsupported model timeframe')
        req=manifest.get('requirements',{})
        if not isinstance(req,dict) or any(tf not in ('M1','M5','M15','H1','H4','D1') or not isinstance(n,int) or isinstance(n,bool) or not 1<=n<=12000 for tf,n in req.items()):raise ValueError('invalid or unbounded data requirements')
        if not manifest.get('instruments') or not manifest.get('name'):raise ValueError('complete model metadata required')
        body={**manifest,'authorship':authorship,'classification':'EXPERIMENTAL'};sha=hashlib.sha256(source.encode()).hexdigest()
        with self.db() as c:
            old=c.execute('SELECT sha,body FROM models WHERE lab=? AND key=? AND version=?',(lab,key,version)).fetchone()
            if old:
                if old['sha']!=sha or json.loads(old['body'])!=body:raise ValueError('model version immutable; increment its version')
                return
            c.execute('INSERT INTO models VALUES(?,?,?,?,?,?,?,?,?,?)',(lab,key,version,json.dumps(body),source,sha,'EXPERIMENTAL',1,0,time.time()))
    def models(self):
        with self.db() as c:rows=c.execute('SELECT * FROM models ORDER BY lab,key,version').fetchall()
        return [{**dict(r),'manifest':json.loads(r['body'])} for r in rows]
    def model(self,lab,key,version):return next((m for m in self.models() if (m['lab'],m['key'],m['version'])==(lab,key,version)),None)
    def set_status(self,lab,key,version,status):
        if status not in ('EXPERIMENTAL','DISABLED','ARCHIVED','REJECTED'):raise ValueError('verified status cannot be self-assigned')
        with self.db() as c:
            c.execute('UPDATE models SET status=?,scan_enabled=?,alert_enabled=0 WHERE lab=? AND key=? AND version=?',(status,int(status=='EXPERIMENTAL'),lab,key,version))
            c.execute('INSERT INTO events(signal,kind,body,at) VALUES(NULL,"MODEL_STATUS",?,?)',(json.dumps({'lab':lab,'key':key,'version':version,'status':status}),time.time()))
    def delivery_approval(self):
        with self.db() as c:r=c.execute('SELECT value FROM settings WHERE key="delivery_approval"').fetchone()
        value=json.loads(r['value']) if r else None
        return value if isinstance(value,dict) and value.get('approved') is True else None
    def approve_delivery(self,approval):
        """Record an explicit CEO approval for EXPERIMENTAL paper-signal delivery of listed models only."""
        if not str(approval.get('approved_by','')).strip() or not str(approval.get('directive','')).strip():raise ValueError('named approver and directive required')
        if approval.get('production') is not False:raise ValueError('production delivery cannot be approved here')
        scope=approval.get('scope')
        if not isinstance(scope,list) or not scope:raise ValueError('explicit model scope required')
        for item in scope:
            if item.get('tier') not in TIERS:raise ValueError('unknown evidence tier')
            m=self.model(item.get('lab'),item.get('key'),item.get('version'))
            if not m or m['status']!='EXPERIMENTAL':raise ValueError('only registered EXPERIMENTAL models can be approved')
        record={**approval,'approved':True,'recorded_at':time.time()}
        with self.db() as c:
            c.execute('UPDATE settings SET value=? WHERE key="delivery_approval"',(json.dumps(record),))
            c.execute('UPDATE models SET alert_enabled=0')
            for item in scope:c.execute('UPDATE models SET alert_enabled=1 WHERE lab=? AND key=? AND version=? AND status="EXPERIMENTAL"',(item['lab'],item['key'],item['version']))
            self.event(c,None,'DELIVERY_APPROVAL',record,record['recorded_at'])
        return record
    def revoke_delivery(self,reason):
        with self.db() as c:
            c.execute('UPDATE settings SET value="null" WHERE key="delivery_approval"');c.execute('UPDATE models SET alert_enabled=0')
            self.event(c,None,'DELIVERY_REVOKED',{'reason':reason},time.time())
    def tier(self,lab,key,version):
        approval=self.delivery_approval() or {}
        return next((i['tier'] for i in approval.get('scope',[]) if (i['lab'],i['key'],i['version'])==(lab,key,version)),None)
    def claim_delivery(self,sid,at):
        """Atomic QUEUED -> IN_FLIGHT; a crash afterwards becomes DELIVERY_UNKNOWN and is never replayed."""
        with self.db() as c:return c.execute('UPDATE outbox SET state="IN_FLIGHT",updated=? WHERE signal=? AND state="QUEUED"',(at,sid)).rowcount==1
    def finish_delivery(self,sid,state,body,at):
        with self.db() as c:
            c.execute('UPDATE outbox SET state=?,body=?,updated=? WHERE signal=? AND state="IN_FLIGHT"',(state,json.dumps(body),at,sid))
            self.event(c,sid,'TELEGRAM_'+state,body,at)
    # ----- Notification categories B (research observations) and C (intelligence briefings) -----
    def _notifications(self,c):
        c.execute('CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,category TEXT,ref TEXT,state TEXT,message TEXT,body TEXT,created REAL,updated REAL)')
    def category_approval(self,category):
        if category not in CATEGORIES:raise ValueError('unknown notification category')
        with self.db() as c:r=c.execute('SELECT value FROM settings WHERE key=?',('approval:'+category,)).fetchone()
        value=json.loads(r['value']) if r else None
        return value if isinstance(value,dict) and value.get('approved') is True else None
    def approve_category(self,category,approval):
        """Explicit CEO approval for outbound delivery of one category; never covers trade signals or production."""
        if category not in CATEGORIES:raise ValueError('unknown notification category')
        if not str(approval.get('approved_by','')).strip() or not str(approval.get('directive','')).strip():raise ValueError('named approver and directive required')
        if approval.get('production') is not False:raise ValueError('production delivery cannot be approved here')
        record={**approval,'category':category,'approved':True,'recorded_at':time.time()}
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('approval:'+category,json.dumps(record)))
            self.event(c,None,'CATEGORY_APPROVAL',record,record['recorded_at'])
        return record
    def revoke_category(self,category,reason):
        if category not in CATEGORIES:raise ValueError('unknown notification category')
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('approval:'+category,'null'))
            self.event(c,None,'CATEGORY_REVOKED',{'category':category,'reason':reason},time.time())
    def notify_record(self,nid,category,ref,state,message,body,at):
        """Insert once (id is the dedupe key: same observation or briefing slot never recorded twice)."""
        with self.db() as c:
            self._notifications(c)
            return c.execute('INSERT OR IGNORE INTO notifications VALUES(?,?,?,?,?,?,?,?)',(nid,category,ref,state,message,json.dumps(body),at,at)).rowcount==1
    def notify_transition(self,nid,old,new,body,at):
        with self.db() as c:
            self._notifications(c)
            ok=c.execute('UPDATE notifications SET state=?,body=?,updated=? WHERE id=? AND state=?',(new,json.dumps(body),at,nid,old)).rowcount==1
            if ok:self.event(c,None,'NOTIFY_'+new,{'id':nid,**body},at)
            return ok
    def notifications(self,category=None,limit=200):
        with self.db() as c:
            self._notifications(c)
            rows=c.execute('SELECT * FROM notifications WHERE (? IS NULL OR category=?) ORDER BY created DESC LIMIT ?',(category,category,limit)).fetchall()
        return [{**dict(r),'body':json.loads(r['body'] or '{}')} for r in rows]
    def event(self,c,sid,kind,body,at):c.execute('INSERT INTO events(signal,kind,body,at) VALUES(?,?,?,?)',(sid,kind,json.dumps(body),at))
    def claim(self,marker,at):
        with self.db() as c:
            try:c.execute('INSERT INTO runs VALUES(?,?,?,?)',(marker,'RUNNING',at,'{}'));return True
            except sqlite3.IntegrityError:return False
    def finish_run(self,marker,status,body):
        with self.db() as c:c.execute('UPDATE runs SET state=?,body=? WHERE marker=?',(status,json.dumps(body),marker))
    def recover(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM leases WHERE expires>?',(time.time(),)).fetchone():return False
            c.execute('UPDATE runs SET state="INTERRUPTED" WHERE state="RUNNING"')
            # A remote send may have succeeded before a crash. Never replay it automatically.
            c.execute('UPDATE outbox SET state="DELIVERY_UNKNOWN" WHERE state="IN_FLIGHT"')
            self._notifications(c);c.execute('UPDATE notifications SET state="DELIVERY_UNKNOWN" WHERE state="IN_FLIGHT"')
            # Repair a power loss between durable signal creation and preview enqueue.
            # The notifier still applies expiry/status and never sends in this release.
            from .telegram import message
            for row in c.execute('SELECT s.body FROM signals s LEFT JOIN outbox o ON o.signal=s.id WHERE o.signal IS NULL').fetchall():
                signal=json.loads(row['body'])
                if signal.get('confirmed'):
                    try:text=message(signal)
                    except ValueError as exc:  # incomplete record: never formatted or sent; recovery continues
                        self.event(c,signal.get('signal_id'),'RECOVERY_SKIPPED_INCOMPLETE',{'reason':str(exc)},time.time());continue
                    c.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?)',(signal['signal_id'],'QUEUED',text,'{}',time.time()))
            return True
    def lease(self,owner,at,seconds=20):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM leases WHERE name="model_worker"').fetchone()
            if row and row['expires']>at:return False
            c.execute('INSERT OR REPLACE INTO leases VALUES("model_worker",?,?)',(owner,at+seconds));return True
    def release(self,owner):
        with self.db() as c:c.execute('DELETE FROM leases WHERE owner=?',(owner,))
    def record(self,record,confirmed,reason=None):
        record={**record,'confirmed':bool(confirmed),'qualification_reason':reason}
        sid=record['signal_id'];at=record['entry_at'];state='ACTIVE' if confirmed else 'CLOSED'
        with self.db() as c:
            cursor=c.execute('INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,record['lab'],record['model_key'],record['model_version'],record['symbol'],record['timeframe'],record['signal_bar_closed_at'],at,state,json.dumps(record)))
            if not cursor.rowcount:return False
            self.event(c,sid,'DETECTED',{'input_sha256':record['input_sha256']},at)
            for transition in ('CONFIRMED','ACTIVE') if confirmed else ('CLOSED',):self.event(c,sid,transition,{'reason':reason},at)
        return True
    def signals(self,limit=200):
        with self.db() as c:rows=c.execute('SELECT * FROM signals ORDER BY created DESC LIMIT ?',(min(limit,1000),)).fetchall()
        return [{**json.loads(r['body']),'state':r['state']} for r in rows]
    def signal(self,sid):
        with self.db() as c:r=c.execute('SELECT * FROM signals WHERE id=?',(sid,)).fetchone()
        return {**json.loads(r['body']),'state':r['state']} if r else None
    def pending(self,symbol=None,after=None,limit=16):
        def query(cursor):
            with self.db() as c:
                rows=c.execute('SELECT * FROM signals WHERE state IN ("ACTIVE","UNRESOLVED") AND (? IS NULL OR symbol=?) AND (created,id)>(?,?) ORDER BY created,id LIMIT ?',
                               (symbol,symbol,*(cursor or (-1,'')),min(limit,16))).fetchall()
            return [{**json.loads(r['body']),'state':r['state']} for r in rows]
        rows=query(after)
        return rows if rows or after is None else query(None)
    def add_candles(self,snapshot):
        with self.db() as c:
            for tf in snapshot['frames']:
                for b in snapshot['frames'].get(tf,[]):
                    # Outcome evidence compares executable prices, not optional model features.
                    content=canonical({k:b[k] for k in ('utc','open','high','low','close','spread')}).decode();old=c.execute('SELECT body FROM candles WHERE symbol=? AND tf=? AND utc=?',(snapshot['symbol'],tf,b['utc'])).fetchone()
                    if not old:c.execute('INSERT INTO candles VALUES(?,?,?,?)',(snapshot['symbol'],tf,b['utc'],content))
                    elif old['body']!=content:
                        exists=c.execute('SELECT 1 FROM candle_revisions WHERE symbol=? AND tf=? AND utc=? AND body=?',(snapshot['symbol'],tf,b['utc'],content)).fetchone()
                        if not exists:
                            c.execute('INSERT INTO candle_revisions(symbol,tf,utc,body,at) VALUES(?,?,?,?,?)',(snapshot['symbol'],tf,b['utc'],content,snapshot['asof']))
                            affected=c.execute('SELECT id FROM signals WHERE symbol=? AND created-900<=? AND json_extract(body,"$.deadline")>=? AND state IN ("TP_HIT","SL_HIT","CLOSED")',
                                               (snapshot['symbol'],b['utc'],b['utc'])).fetchall()
                            for row in affected:
                                self._outcome(c,row['id'],{'status':'DATA_CONFLICT','r':None,'simulated_net_r':None,'actual_realized_r':None,'reason':'closed candle conflict invalidates the prior paper outcome'},snapshot['asof'])
                        # Conflicting closed-bar evidence is not silently rewritten.
    def candles(self,symbol,tf,start,end):
        with self.db() as c:rows=c.execute('SELECT b.body FROM candles b WHERE symbol=? AND tf=? AND utc>=? AND utc<=? AND NOT EXISTS (SELECT 1 FROM candle_revisions r WHERE r.symbol=b.symbol AND r.tf=b.tf AND r.utc=b.utc) ORDER BY utc LIMIT 12000',(symbol,tf,start,end)).fetchall()
        return [json.loads(r['body']) for r in rows]
    def has_conflicts(self,symbol,start,end):
        with self.db() as c:return bool(c.execute('SELECT 1 FROM candle_revisions WHERE symbol=? AND utc>=? AND utc<=? LIMIT 1',(symbol,start,end)).fetchone())
    def outcome(self,sid,result,at):
        with self.db() as c:return self._outcome(c,sid,result,at)
    def _outcome(self,c,sid,result,at):
        sha=hashlib.sha256(canonical(result)).hexdigest()
        old=c.execute('SELECT * FROM outcomes WHERE signal=? ORDER BY seq DESC LIMIT 1',(sid,)).fetchone()
        if old and old['sha']==sha:return False
        revision={'revision':json.loads(old['body'])['revision']+1 if old else 1,'supersedes':old['seq'] if old else None,**result}
        c.execute('INSERT INTO outcomes(signal,body,sha,at) VALUES(?,?,?,?)',(sid,json.dumps(revision),sha,at))
        status=result['status'];stage='TP_HIT' if status=='TP' else 'SL_HIT' if status=='SL' else 'CLOSED' if status=='TIME_EXIT' else 'ACTIVE' if status=='PENDING' else 'UNRESOLVED'
        c.execute('UPDATE signals SET state=? WHERE id=?',(stage,sid));self.event(c,sid,stage,revision,at)
        if stage in ('TP_HIT','SL_HIT'):self.event(c,sid,'CLOSED',{'outcome':stage},at)
        # Outcome update only for a signal that was actually delivered; first final outcome only.
        sent=c.execute('SELECT 1 FROM outbox WHERE signal=? AND state="SENT"',(sid,)).fetchone()
        if sent and status in ('TP','SL','TIME_EXIT') and result.get('simulated_net_r') is not None:
            from .telegram import outcome_message
            row=c.execute('SELECT body FROM signals WHERE id=?',(sid,)).fetchone()
            c.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?)',(sid+'#outcome','QUEUED',outcome_message(json.loads(row['body']),result),'{}',at))
        return True
    def outcomes(self):
        with self.db() as c:rows=c.execute('SELECT o.* FROM outcomes o JOIN (SELECT signal,max(seq) seq FROM outcomes GROUP BY signal) x ON o.seq=x.seq').fetchall()
        return {r['signal']:json.loads(r['body']) for r in rows}
    def queue_message(self,sid,message,at):
        with self.db() as c:c.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?)',(sid,'QUEUED',message,'{}',at))
    def outbox(self):
        with self.db() as c:return [dict(r) for r in c.execute('SELECT * FROM outbox ORDER BY updated DESC LIMIT 200')]
