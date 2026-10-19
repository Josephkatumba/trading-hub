"""Persistent sequential foreground queue. Running one command does not start a service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .control import now
from .data import canonical,digest
from .frozen import verify

def run_process(folder,payload,wall_seconds):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'worker-input.json';path.write_bytes(canonical(payload))
    output=folder/'worker-result.json'
    if output.exists():output.unlink()
    started=time.monotonic()
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (folder/'worker.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('worker.py')),str(path)],
                                 stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=flags)
        (folder/'worker-pid.json').write_text(json.dumps({'pid':process.pid,'started_at':now(),'wall_seconds':wall_seconds}))
        try:
            process.wait(timeout=wall_seconds)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5)
            return {'status':'TIMED_OUT','reason':'hard wall-clock limit reached','resources':{'wall_seconds':time.monotonic()-started,'hard_timeout_enforced':True}}
        except BaseException:
            process.kill();process.wait(timeout=5);raise
    if not output.exists():return {'status':'RESOURCE_LIMIT' if process.returncode else 'FAILED','reason':'worker terminated without complete output','resources':{'wall_seconds':time.monotonic()-started}}
    return json.loads(output.read_text())

def run_one(control,operator_token,wall_seconds=30,memory_mb=384):
    control.operator(operator_token)
    if not 1<=wall_seconds<=45 or not 64<=memory_mb<=512:raise ValueError('worker policy exceeded')
    settings=control.settings();verify(settings['evaluator'])
    with control.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if settings['paused']:return {'status':'PAUSED','scope':'queue'}
        if c.execute('SELECT 1 FROM jobs WHERE state="RUNNING"').fetchone():return {'status':'BUSY'}
        job=c.execute('SELECT * FROM jobs WHERE state="QUEUED" ORDER BY created LIMIT 1').fetchone()
        if not job:return {'status':'EMPTY'}
        if job['segments']>=settings['max_segments_per_job']:
            c.execute('UPDATE jobs SET state="RESOURCE_LIMIT",updated=? WHERE id=?',(now(),job['id']))
            return {'status':'RESOURCE_LIMIT','job':job['id'],'reason':'maximum resume segments reached'}
        c.execute('UPDATE jobs SET state="RUNNING",segments=segments+1,updated=? WHERE id=?',(now(),job['id']))
        control.event(c,job['lab'],job['strategy'],job['version'],'WORKER_STARTED',{'job':job['id']})
    folder=control.root/'runtime'/job['id'];folder.mkdir(parents=True,exist_ok=True)
    request=json.loads(job['body']);path=folder/'request.json';content=canonical(request)
    if path.exists() and path.read_bytes()!=content:
        with control.connect() as c:
            c.execute('UPDATE jobs SET state="FAILED",updated=? WHERE id=?',(now(),job['id']))
            control.event(c,job['lab'],job['strategy'],job['version'],'WORKER_FAILED',{'job':job['id'],'reason':'runtime request changed'})
        return {'job':job['id'],'status':'FAILED','reason':'runtime request changed; evaluation refused'}
    if not path.exists():path.write_bytes(content)
    payload={'root':str(control.root),'evaluator':settings['evaluator'],'request_sha256':digest(content),
             'wall_seconds':wall_seconds,'memory_mb':memory_mb,'cpu_percent':20,'cpu_seconds':20}
    try:result=run_process(folder,payload,wall_seconds)
    except BaseException as exc:
        with control.connect() as c:
            c.execute('UPDATE jobs SET state="FAILED",updated=? WHERE id=?',(now(),job['id']))
            control.event(c,job['lab'],job['strategy'],job['version'],'WORKER_FAILED',{'job':job['id'],'reason':repr(exc)})
        raise
    status=result['status']
    if status not in ('COMPLETE','PAUSED','FAILED','TIMED_OUT','RESOURCE_LIMIT'):raise ValueError('invalid worker response')
    with control.connect() as c:
        if status=='COMPLETE':
            result.update(dataset=request['dataset'],evaluator_identity=settings['evaluator'],source_sha256=request['source_sha256'],request_fingerprint=job['fingerprint'])
            c.execute('INSERT INTO results VALUES(?,?,?,?)',(job['id'],job['lab'],json.dumps(result),now()))
        c.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(status,now(),job['id']))
        control.event(c,job['lab'],job['strategy'],job['version'],'WORKER_SEGMENT',{'job':job['id'],'status':status,'resources':result.get('resources',{}),'reason':result.get('reason')})
    control.append_export(job['lab'],'experiments.jsonl',{'job':job['id'],'state':status,'at':now(),'resources':result.get('resources',{})})
    if status=='COMPLETE':control.append_export(job['lab'],'performance.jsonl',{'job':job['id'],'evaluator':settings['evaluator'],'dataset':request['dataset'],'periods':result['periods'],'profitability_certified':False})
    return {'job':job['id'],'status':status,'resources':result.get('resources',{}),'reason':result.get('reason')}
