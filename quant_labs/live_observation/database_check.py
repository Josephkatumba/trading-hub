"""Read-only verification of live laboratory identities, provenance and delivery state."""
import hashlib
import json
from pathlib import Path
import sqlite3

root=Path(__file__).resolve().parents[2];output=Path(__file__).resolve().parent
path=root/'backend/data/quant_live/signals.sqlite3'
with sqlite3.connect('file:'+path.resolve().as_posix()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    models=[dict(r) for r in db.execute('SELECT lab,key,version,status,scan_enabled,alert_enabled,sha FROM models')]
    runs=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute('SELECT * FROM runs ORDER BY at')]
    signals=[json.loads(r[0]) for r in db.execute('SELECT body FROM signals')]
    previews=[dict(r) for r in db.execute('SELECT signal,state,message,body FROM outbox')]
    source=root/'quant_labs/state/labs/codex/strategies/compression_escape/model.py'
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    evidence={'database':str(path),'models':models,'model_source_hash_matches':all(m['sha']==sha for m in models if m['lab']=='codex'),
              'runs':runs,'run_states':dict(db.execute('SELECT state,count(*) FROM runs GROUP BY state')),
              'signals':signals,'signal_count':len(signals),'qualified_count':sum(bool(s.get('confirmed')) for s in signals),
              'previews':previews,'preview_count':len(previews),'outbox_states':dict(db.execute('SELECT state,count(*) FROM outbox GROUP BY state')),
              'delivery_approval':json.loads(db.execute('SELECT value FROM settings WHERE key="delivery_approval"').fetchone()[0]),
              'cached_candle_count':db.execute('SELECT count(*) FROM candles').fetchone()[0],
              'outcome_revision_count':db.execute('SELECT count(*) FROM outcomes').fetchone()[0]}
(output/'database_check.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print(json.dumps({k:evidence[k] for k in ('models','model_source_hash_matches','run_states','signal_count','qualified_count','preview_count','outbox_states','delivery_approval','cached_candle_count','outcome_revision_count')},indent=2))
