"""Scoped SQLite admission guards, effective in the existing running consumer.

No engine reload or strategy-source change. Unresolved paths reserve their original
deadline; a known latest outcome releases a reservation at its recorded exit time.
"""
import json
import time

KEYS = tuple('trend_reclaim_r' + str(r) for r in (2, 3, 4, 5, 7, 9)) + ('range_sweep_reversion',)

def nonoverlapping(signals, outcomes):
    """Rebuild a cohort after late outcome revisions, rather than double-counting."""
    locks, accepted, excluded = {}, [], []
    seen = set()
    for signal in sorted(signals, key=lambda s: (s['entry_at'], s['signal_id'])):
        if not signal.get('confirmed'):
            continue
        identity = (signal['lab'], signal['model_key'], signal['model_version'], signal['symbol'])
        if signal['signal_id'] in seen or signal['entry_at'] < locks.get(identity, 0):
            excluded.append(signal['signal_id'])
            continue
        seen.add(signal['signal_id'])
        accepted.append(signal)
        outcome = outcomes.get(signal['signal_id'], {})
        locks[identity] = outcome['exit_at'] if outcome.get('simulated_net_r') is not None else signal['deadline']
    return accepted, excluded

DDL = '''
CREATE TABLE IF NOT EXISTS codex_forward_cohorts(
 lab TEXT, model TEXT, version TEXT, source_sha256 TEXT, instruments TEXT,
 started REAL, evidence TEXT, PRIMARY KEY(lab,model,version));
CREATE TABLE IF NOT EXISTS codex_forward_rejections(
 signal TEXT PRIMARY KEY, model TEXT, version TEXT, symbol TEXT,
 at REAL, reason TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS codex_forward_overlap_lookup ON signals(lab,model,version,symbol,created);
CREATE TRIGGER IF NOT EXISTS codex_forward_instrument_guard BEFORE INSERT ON signals
WHEN EXISTS(SELECT 1 FROM codex_forward_cohorts f WHERE f.lab=NEW.lab AND f.model=NEW.model AND f.version=NEW.version)
AND NOT EXISTS(SELECT 1 FROM codex_forward_cohorts f, json_each(f.instruments) i
 WHERE f.lab=NEW.lab AND f.model=NEW.model AND f.version=NEW.version AND i.value=NEW.symbol)
BEGIN
 INSERT OR IGNORE INTO codex_forward_rejections VALUES(NEW.id,NEW.model,NEW.version,NEW.symbol,NEW.created,'UNSUPPORTED_INSTRUMENT',NEW.body);
 SELECT RAISE(IGNORE);
END;
CREATE TRIGGER IF NOT EXISTS codex_forward_overlap_guard BEFORE INSERT ON signals
WHEN json_extract(NEW.body,'$.confirmed')=1
AND EXISTS(SELECT 1 FROM codex_forward_cohorts f WHERE f.lab=NEW.lab AND f.model=NEW.model AND f.version=NEW.version)
AND NOT EXISTS(SELECT 1 FROM signals WHERE id=NEW.id)
AND EXISTS(SELECT 1 FROM signals s
 WHERE s.lab=NEW.lab AND s.model=NEW.model AND s.version=NEW.version AND s.symbol=NEW.symbol
 AND json_extract(s.body,'$.confirmed')=1
 AND NEW.created < CASE
 WHEN (SELECT json_extract(o.body,'$.simulated_net_r') FROM outcomes o WHERE o.signal=s.id ORDER BY o.seq DESC LIMIT 1) IS NOT NULL
 THEN (SELECT json_extract(o.body,'$.exit_at') FROM outcomes o WHERE o.signal=s.id ORDER BY o.seq DESC LIMIT 1)
 ELSE json_extract(s.body,'$.deadline') END)
BEGIN
 INSERT OR IGNORE INTO codex_forward_rejections VALUES(NEW.id,NEW.model,NEW.version,NEW.symbol,NEW.created,'OVERLAPPING_MODEL_SYMBOL_OPPORTUNITY',NEW.body);
 SELECT RAISE(IGNORE);
END;
'''

def install(store, models, evidence):
    """Arm only the explicitly authorized seven identities before registration."""
    assert len(models) == 7 and {m['key'] for m in models} == set(KEYS)
    for model in models:
        assert model['lab'] == 'codex' and model['version'] == '0.1.0'
        assert model['manifest']['instruments'] == ['EURUSD', 'XAUUSD', 'BTCUSD']
    with store.db() as db:
        db.executescript(DDL)
        for model in models:
            old = db.execute('SELECT source_sha256,instruments FROM codex_forward_cohorts WHERE lab=? AND model=? AND version=?',
                             ('codex', model['key'], model['version'])).fetchone()
            instruments = json.dumps(model['manifest']['instruments'])
            if old:
                assert old['source_sha256'] == model['sha'] and old['instruments'] == instruments
            db.execute('INSERT OR IGNORE INTO codex_forward_cohorts VALUES(?,?,?,?,?,?,?)',
                       ('codex', model['key'], model['version'], model['sha'], instruments, time.time(), json.dumps(evidence)))
