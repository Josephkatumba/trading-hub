"""M5 ledger and queue, separate from the v1 ledger so v1 workers never see M5 jobs.

Capabilities (lab / operator) are the existing ones, checked read-only against the main
control plane. Strategy versions and results are immutable, as in v1.
"""
import json
import math
from ..control import ControlPlane, ID, VERSION, REQUIRED, now, uid
from ..data import canonical, digest, SharedData
from . import frozen

EXPORTS = ('m5_registry.jsonl', 'm5_experiments.jsonl', 'm5_performance.jsonl')
SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS strategies(lab TEXT,id TEXT,version TEXT,body TEXT,source TEXT,sha TEXT,created TEXT,PRIMARY KEY(lab,id,version));
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,lab TEXT,strategy TEXT,version TEXT,kind TEXT,body TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,lab TEXT,strategy TEXT,version TEXT,state TEXT,body TEXT,fingerprint TEXT,duplicate_of TEXT,created TEXT,updated TEXT,segments INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS results(job TEXT PRIMARY KEY,lab TEXT,body TEXT,created TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS only_one_running_worker ON jobs(state) WHERE state='RUNNING';
CREATE TRIGGER IF NOT EXISTS strategy_no_update BEFORE UPDATE ON strategies BEGIN SELECT RAISE(ABORT,'immutable strategy version');END;
CREATE TRIGGER IF NOT EXISTS strategy_no_delete BEFORE DELETE ON strategies BEGIN SELECT RAISE(ABORT,'preserve failed strategies');END;
CREATE TRIGGER IF NOT EXISTS result_no_update BEFORE UPDATE ON results BEGIN SELECT RAISE(ABORT,'append new evaluation revision');END;
CREATE TRIGGER IF NOT EXISTS result_no_delete BEFORE DELETE ON results BEGIN SELECT RAISE(ABORT,'preserve performance records');END;
'''


class M5Control:
    def __init__(self, root):
        self.base = ControlPlane(root)
        self.root = self.base.root
        self.folder = self.root / 'm5'
        self.folder.mkdir(exist_ok=True)
        self.db = self.folder / 'control_m5.sqlite3'
        with self.connect() as c:
            c.executescript(SCHEMA)

    def connect(self):
        import sqlite3
        from ..control import ClosingConnection
        c = sqlite3.connect(self.db, timeout=5, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        return c

    def settings(self):
        s = self.base.settings()
        return {'dataset': s['dataset'], 'evaluator': s['evaluator'], 'm5_extension': frozen.identity(),
                'paused': s['paused'], 'max_pending_per_lab': s['max_pending_per_lab'], 'max_segments_per_job': s['max_segments_per_job']}

    def export(self, lab, name, row):
        folder = self.base.workspace(lab)
        path = folder / name
        if name not in EXPORTS or (path.exists() and path.resolve().parent != folder.resolve()):
            raise PermissionError('export path escapes laboratory')
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, allow_nan=False) + '\n')

    def event(self, c, lab, strategy, version, kind, body):
        c.execute('INSERT INTO events(lab,strategy,version,kind,body,at) VALUES(?,?,?,?,?,?)',
                  (lab, strategy, version, kind, json.dumps(body), now()))

    def register(self, token, lab, spec, source):
        self.base.own(token, lab)
        if not ID.fullmatch(spec.get('id', '')) or not VERSION.fullmatch(spec.get('version', '')):
            raise ValueError('invalid strategy ID/version')
        if any(not isinstance(spec.get(k), str) or not spec[k].strip() for k in REQUIRED):
            raise ValueError('complete strategy specification required')
        if spec['timeframe'] != 'M5':
            raise ValueError('M5 ledger accepts M5 strategies only; use the v1 ledger for other timeframes')
        if not isinstance(source, str) or not source.strip() or len(source.encode()) > 262144:
            raise ValueError('reviewable source is required, maximum 256 KiB')
        trials = spec.get('declared_trials', 1)
        if not isinstance(trials, int) or not 1 <= trials <= 100000:
            raise ValueError('declare all prior variants attempted')
        encoded = canonical(spec)
        if len(encoded) > 65536:
            raise ValueError('strategy specification too large')
        sha = digest(source.encode())
        record = {**spec, 'lab': lab, 'source_sha256': sha, 'created_at': now(), 'ledger': frozen.VERSION}
        with self.connect() as c:
            c.execute('INSERT INTO strategies VALUES(?,?,?,?,?,?,?)', (lab, spec['id'], spec['version'], encoded.decode(), source, sha, record['created_at']))
            self.event(c, lab, spec['id'], spec['version'], 'IDEA', {'source_sha256': sha})
        self.export(lab, 'm5_registry.jsonl', record)
        return record

    def get_strategy(self, lab, sid, version):
        with self.connect() as c:
            r = c.execute('SELECT * FROM strategies WHERE lab=? AND id=? AND version=?', (lab, sid, version)).fetchone()
        if not r:
            raise KeyError('M5 strategy version not registered')
        return dict(r)

    def submit(self, token, lab, sid, version, signals, purpose='RESEARCH'):
        self.base.own(token, lab)
        record = self.get_strategy(lab, sid, version)
        settings = self.settings()
        frozen.verify(settings['m5_extension'])
        if purpose not in ('RESEARCH', 'INFRASTRUCTURE_TEST'):
            raise ValueError('unverified prospective submissions are not enabled')
        if not isinstance(signals, list) or not 1 <= len(signals) <= 2000:
            raise ValueError('1..2000 intents per bounded experiment')
        shared = SharedData(self.root / 'shared', settings['dataset'])
        required = {'symbol', 'direction', 'signal_bar_closed_at', 'entry_at', 'stop_loss', 'take_profit', 'horizon_seconds'}
        normalized = []
        for s in signals:
            if not isinstance(s, dict) or set(s) != required:
                raise ValueError('only signal intent fields accepted; no supplied outcomes, code or output paths')
            if s['direction'] not in ('LONG', 'SHORT') or f"{s['symbol']}_M1.json.gz" not in shared.manifest['files'] or f"{s['symbol']}_M15.json.gz" not in shared.manifest['files']:
                raise ValueError('unsupported market or direction')
            for k in required - {'symbol', 'direction'}:
                if isinstance(s[k], bool) or not isinstance(s[k], (int, float)) or not math.isfinite(s[k]):
                    raise ValueError('finite numeric intent fields required')
            if s['entry_at'] != s['signal_bar_closed_at'] or s['entry_at'] % 300 or s['entry_at'] <= 0 or not 60 <= s['horizon_seconds'] <= 604800:
                raise ValueError('invalid M5 entry semantics/horizon')
            if s['stop_loss'] <= 0 or s['take_profit'] <= 0:
                raise ValueError('positive levels required')
            normalized.append({k: s[k] for k in sorted(required)})
        normalized.sort(key=lambda s: (s['symbol'], s['entry_at'], s['direction'], s['stop_loss'], s['take_profit']))
        if len({canonical(s) for s in normalized}) != len(normalized):
            raise ValueError('duplicate intent in experiment')
        fingerprint = digest(canonical({'signals': normalized, 'dataset': settings['dataset'], 'evaluator': settings['evaluator'],
                                        'm5_extension': settings['m5_extension'], 'timeframe': 'M5', 'purpose': purpose}))
        job, created = uid(), now()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            pending = c.execute('SELECT count(*) FROM jobs WHERE lab=? AND state IN ("QUEUED","RUNNING","PAUSED")', (lab,)).fetchone()[0]
            if pending >= settings['max_pending_per_lab']:
                raise ValueError('lab M5 queue quota reached')
            old = c.execute('SELECT id FROM jobs WHERE fingerprint=? AND state!="DUPLICATE" ORDER BY created LIMIT 1', (fingerprint,)).fetchone()
            request = {'strategy': json.loads(record['body']), 'signals': normalized, 'dataset': settings['dataset'],
                       'evaluator': settings['evaluator'], 'm5_extension': settings['m5_extension'], 'source_sha256': record['sha'],
                       'purpose': purpose, 'lab': lab, 'strategy_registered_at': record['created']}
            state = 'DUPLICATE' if old else 'QUEUED'
            c.execute('INSERT INTO jobs(id,lab,strategy,version,state,body,fingerprint,duplicate_of,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (job, lab, sid, version, state, json.dumps(request), fingerprint, old['id'] if old else None, created, created))
            self.event(c, lab, sid, version, 'RESEARCH', {'job': job, 'state': state, 'fingerprint': fingerprint})
        export = {'job': job, 'strategy': sid, 'version': version, 'state': state, 'at': created, 'duplicate_of': old['id'] if old else None}
        self.export(lab, 'm5_experiments.jsonl', export)
        return export

    def public(self):
        with self.connect() as c:
            strategies = [dict(r) for r in c.execute('SELECT lab,id,version,sha,created FROM strategies')]
            jobs = [dict(r) for r in c.execute('SELECT id,lab,strategy,version,state,duplicate_of,created,updated,segments FROM jobs ORDER BY created DESC')]
            results = {r['job']: json.loads(r['body']) for r in c.execute('SELECT * FROM results')}
        return {'ledger': frozen.VERSION, 'strategies': strategies, 'jobs': jobs,
                'results': {j: {'periods': r['periods'], 'rejections': r['rejections'], 'm5_admitted': r.get('m5_admitted')} for j, r in results.items()},
                'qualified_leaderboard': [], 'profitability_certified': False,
                'note': 'M5 research metrics; not profitability certification. Shared M1 history (and so M5) starts July 2026.'}
