"""Evidence-first admission of seven unchanged Codex paper models. No delivery path."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from quant_labs.paper_integration.guards import KEYS, install, nonoverlapping
from quant_labs.data import canonical
from quant_labs.frozen import verify
from quant_labs.queue import run_process
from quant_labs.provider_bridge import cached_snapshot
from quant_live.model_host import validate_source
from quant_live.runtime import bounded_model, qualify
from quant_live.store import Store
from quant_labs.live_observation.control import permission_summary

OUT = Path(__file__).resolve().parent
DB = ROOT / 'backend/data/quant_live/signals.sqlite3'
def dump(name, data):
    target = OUT / name
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(target)

def load_models():
    result = []
    with closing(sqlite3.connect((ROOT / 'quant_labs/state/control.sqlite3').resolve().as_uri()+'?mode=ro', uri=True)) as db:
        for key in KEYS:
            folder = ROOT / 'quant_labs/state/labs/codex/strategies' / key
            manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            source = (folder / 'model.py').read_text(encoding='utf-8')
            validate_source(source)
            sha = hashlib.sha256(source.encode()).hexdigest()
            registered = db.execute('SELECT sha,source FROM strategies WHERE lab=? AND id=? AND version=?',('codex',key,'0.1.0')).fetchone()
            assert registered and registered == (sha,source), key
            assert manifest['instruments'] == ['EURUSD','XAUUSD','BTCUSD']
            result.append(dict(lab='codex', key=key, version='0.1.0', manifest=manifest, source=source, sha=sha,
                               raw_source_sha256=hashlib.sha256((folder/'model.py').read_bytes()).hexdigest(),
                               raw_manifest_sha256=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest()))
    return result

def get(route):
    with urllib.request.urlopen('http://127.0.0.1:8000'+route, timeout=20) as response:
        return json.load(response)

def evaluate():
    models = load_models()
    old = json.loads((ROOT/'quant_labs/next_phase/evaluations.json').read_text())
    recoveries = json.loads((ROOT/'quant_labs/next_phase/retry_evaluations.json').read_text())
    results = []
    for case in old:
        assert case['key'] in KEYS
        folder = ROOT / 'quant_labs/state/runtime' / case['job']
        payload = json.loads((folder/'worker-input.json').read_text())
        verify(payload['evaluator'])
        expected = case['periods']
        if expected is None:
            expected = next(x['result']['periods'] for x in recoveries if x['original_job']==case['job'])
        with tempfile.TemporaryDirectory(prefix='tradeden_admission_validation_') as scratch:
            Path(scratch,'request.json').write_bytes((folder/'request.json').read_bytes())
            result = run_process(scratch,payload,45)
        row = dict(key=case['key'],symbol=case['symbol'],original_job=case['job'],original_state=case['status'],
                   request_sha256=payload['request_sha256'],evaluator=payload['evaluator'],result=result,
                   identical_periods=result.get('periods')==expected)
        results.append(row); dump('shared_evaluator_validation.json',results)
        print(json.dumps({k:row[k] for k in ('key','symbol','identical_periods')}),flush=True)
        assert result['status']=='COMPLETE' and row['identical_periods'], row['key']+':'+row['symbol']
    assert len(results)==21
    dump('preserved_sources.json',[{k:m[k] for k in ('key','version','sha','raw_source_sha256','raw_manifest_sha256')} for m in models])

def probes():
    results=[]
    for model in load_models():
        for symbol in model['manifest']['instruments']:
            # Refresh actual quote evidence for each worker, never relabel a timestamp.
            report=get('/api/quant-labs/live')
            data=cached_snapshot(report,DB,symbol,model['manifest']['requirements'])
            now=time.time(); quote_age=now-data['quote']['tick_at']
            counts={tf:len(bars) for tf,bars in data['frames'].items()}
            reasons=[]
            if not data['time_verified'] or not -5<=now-data['asof']<=60 or not -5<=quote_age<=30:reasons.append('STALE_OR_UNVERIFIED_INPUT')
            for tf,minimum in [('M15',80),('H1',64)]:
                bars=data['frames'][tf];seconds={'M15':900,'H1':3600}[tf]
                if len(bars)<minimum or not 0<=now-bars[-1]['utc']-seconds<=2*seconds:reasons.append('MISSING_OR_STALE_'+tf)
            assert not reasons, (symbol,reasons)
            with tempfile.TemporaryDirectory(prefix='tradeden_genuine_probe_') as scratch:
                output=bounded_model(SimpleNamespace(folder=Path(scratch)),model,data)
            decisions=[]
            for decision in output.get('decisions',[]):
                signal,reason=qualify(data,model,decision,time.time())
                decisions.append(dict(raw_decision=decision,qualifies=signal is not None,rejection_reason=reason))
            row=dict(key=model['key'],symbol=symbol,source_sha256=model['sha'],source=data['source'],
                     input_sha256=data['input_sha256'],asof=data['asof'],quote=data['quote'],quote_age=quote_age,
                     metadata=data['metadata'],counts=counts,
                     latest_closed={tf:bars[-1]['utc'] if bars else None for tf,bars in data['frames'].items()},
                     source_status=report['runtime']['latest_inputs'][symbol]['source'],
                     status=output['status'],resources=output.get('resources'),decisions=decisions,
                     live_signal_writes=0,outbound_calls=0)
            results.append(row);dump('genuine_provider_probes.json',results)
            print(json.dumps(dict(key=model['key'],symbol=symbol,status=output['status'],counts=counts)),flush=True)
            assert output['status']=='COMPLETE',row

def enroll():
    models=load_models()
    validation=json.loads((OUT/'shared_evaluator_validation.json').read_text())
    evidence=json.loads((OUT/'genuine_provider_probes.json').read_text())
    preserved=json.loads((OUT/'preserved_sources.json').read_text())
    assert [{k:m[k] for k in ('key','version','sha','raw_source_sha256','raw_manifest_sha256')} for m in models] == preserved
    assert len(validation)==21 and all(x['identical_periods'] and x['result']['status']=='COMPLETE' for x in validation)
    assert len(evidence)==21 and all(x['status']=='COMPLETE' for x in evidence)
    before_health=get('/api/health');before=get('/api/quant-labs/live')
    assert before_health['execution_enabled'] is False
    assert before['telegram_mode']=='DRY_RUN' and not before['outbound_activation_approved']
    with closing(sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        existing=db.execute('SELECT lab,key,version,status,scan_enabled,alert_enabled,sha,body FROM models').fetchall()
        with closing(sqlite3.connect(OUT/'pre_admission.sqlite3')) as backup:
            db.backup(backup)
    # Backup is private runtime evidence and deliberately ignored by Git.
    store=Store(DB.parent)
    install(store,models,{'directive':'CEO seven unchanged Codex models, experimental paper only; no delivery or execution',
                          'historical':'shared_evaluator_validation.json','genuine_provider':'genuine_provider_probes.json'})
    for model in models:
        store.register(model['manifest'],model['source'],model['manifest']['authorship'])
        m=store.model('codex',model['key'],'0.1.0')
        assert (m['status'],m['scan_enabled'],m['alert_enabled'])==('EXPERIMENTAL',1,0)
    after=get('/api/quant-labs/live');after_health=get('/api/health')
    with store.db() as db:
        for row in existing:
            assert tuple(db.execute('SELECT lab,key,version,status,scan_enabled,alert_enabled,sha,body FROM models WHERE lab=? AND key=? AND version=?',row[:3]).fetchone())==row
    assert permission_summary(before_health)==permission_summary(after_health)
    assert before_health['strategy_bank'].get('telegram_enabled')==after_health['strategy_bank'].get('telegram_enabled')
    assert before_health['uptime_started']==after_health['uptime_started']
    assert after['telegram_mode']=='DRY_RUN' and not after['outbound_activation_approved']
    dump('admission.json',dict(at=datetime.now(timezone.utc).isoformat(),keys=list(KEYS),version='0.1.0',
         classifications='EXPERIMENTAL',alerts_enabled=False,execution_enabled=False,engine_restarted=False,
         production_permissions_unchanged=True,existing_models_unchanged=True,
         engine_uptime_started=after_health['uptime_started'],before_runtime=before['runtime'].get('last_processed'),
         source_evidence='preserved_sources.json',historical_records_untouched=True))
    print('Seven EXPERIMENTAL models enrolled; alerts remain zero; no restart.')

def forward():
    report=get('/api/quant-labs/live')
    with closing(sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        cohorts=[dict(r) for r in db.execute('SELECT * FROM codex_forward_cohorts')]
        runs=[dict(r) for r in db.execute('SELECT * FROM runs')]
        output=[]
        for cohort in cohorts:
            raw=[json.loads(r['body']) for r in db.execute('SELECT body FROM signals WHERE lab=? AND model=? AND version=? AND created>=? ORDER BY created,id',
                 (cohort['lab'],cohort['model'],cohort['version'],cohort['started']))]
            latest={r['signal']:json.loads(r['body']) for r in db.execute('SELECT signal,body FROM outcomes ORDER BY seq')}
            accepted,excluded=nonoverlapping(raw,latest)
            from quant_live.report import metrics
            executions=[]
            for r in runs:
                body=json.loads(r['body'])
                if r['at']>=cohort['started'] and body.get('source_sha256')==cohort['source_sha256']:
                    identity={}
                    floor=int(body.get('input_data_timestamp',r['at'])//900)*900
                    for symbol in json.loads(cohort['instruments']):
                        for closed in (floor,floor-900,floor-1800):
                            marker=hashlib.sha256(canonical([cohort['lab'],cohort['model'],cohort['version'],symbol,float(closed)])).hexdigest()
                            if marker==r['marker']:identity=dict(symbol=symbol,bar_closed_at=closed)
                    executions.append(dict(marker=r['marker'],state=r['state'],at=r['at'],**body,**identity))
            m=next(m for lab in report['labs'] if lab['id']=='codex' for m in lab['models'] if m['key']==cohort['model'])
            output.append(dict(key=cohort['model'],version=cohort['version'],started=cohort['started'],
                 source_sha256=cohort['source_sha256'],status=m['status'],scan_enabled=m['scan_enabled'],alert_enabled=m['alert_enabled'],
                 run_states=dict(Counter(r['state'] for r in executions)),runs=executions,
                 raw_detections=len(raw),statistics=metrics(accepted,latest),
                 revision_overlap_exclusions=excluded,
                 admission_rejections=[dict(r) for r in db.execute('SELECT signal,symbol,at,reason FROM codex_forward_rejections WHERE model=?',(cohort['model'],))]))
    dump('forward_performance.json',dict(observed_at=time.time(),models=output,
         basis='Forward only since per-model enrollment; latest outcome revision; chronological same-model/symbol overlap exclusion; no historical results imported.',
         family_pooling='No pooled return or independent-discovery claim across correlated target variants.',
         runtime={k:report['runtime'].get(k) for k in ('running','last_processed','last_error','enabled','telegram_mode','outbound_activation_approved')}))
    print(json.dumps([{k:r[k] for k in ('key','status','scan_enabled','alert_enabled','run_states','raw_detections')} for r in output],indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['evaluate','probe','enroll','forward'])
    {'evaluate':evaluate,'probe':probes,'enroll':enroll,'forward':forward}[p.parse_args().action]()
