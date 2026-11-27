"""Register actual Codex source and run unchanged shared intent accounting sequentially."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from quant_labs.control import ControlPlane
from quant_labs.provider_bridge import register_source
from quant_labs.queue import run_one
from quant_labs.frozen import verify

def main():
    folder=Path(__file__).resolve().parent;control=ControlPlane(ROOT/'quant_labs/state');settings=control.settings();verify(settings['evaluator'])
    token=(control.workspace('codex')/'.lab-token').read_text(encoding='utf-8').strip()
    # Operator capability is used only by this owner-side frozen worker runner,
    # never by a model, a lab submission, a reviewer or a self-approval path.
    operator=json.loads((control.root/'owner/credentials.json').read_text(encoding='utf-8'))['operator:owner']
    models=json.loads((folder/'candidates.json').read_text(encoding='utf-8'));keys={m['key'] for m in models}
    with control.connect() as db:
        foreign=db.execute('SELECT strategy FROM jobs WHERE state IN ("QUEUED","RUNNING","PAUSED")').fetchall()
    if any(r[0] not in keys for r in foreign):raise RuntimeError('Unrelated pending evaluator job; do not take over another run')
    ledger=[]
    for candidate in models:
        manifest=json.loads(Path(candidate['manifest']).read_text(encoding='utf-8'))
        registered=register_source(control,token,'codex',manifest,Path(candidate['source']).read_text(encoding='utf-8'))
        print(json.dumps({'registered':candidate['key'],'source_sha256':candidate['source_sha256']}),flush=True)
    for symbol in ('EURUSD','XAUUSD','BTCUSD'):
        generated=json.loads((folder/f'intents_{symbol}.json').read_text(encoding='utf-8'))
        if generated['dataset']!=settings['dataset'] or generated['evaluator']!=settings['evaluator']:raise ValueError('Dataset/evaluator mismatch')
        for candidate in models:
            key=candidate['key'];result=generated['models'][key];intents=result['intents']
            if not intents:
                ledger.append({'key':key,'symbol':symbol,'status':'NO_DETECTIONS','intents':0});continue
            if len(intents)>2000:raise ValueError('Bounded experiment quota exceeded; no silent truncation')
            submitted=control.submit(token,'codex',key,candidate['version'],intents,'RESEARCH')
            if submitted['state']=='DUPLICATE':
                job=submitted['duplicate_of'];status='DUPLICATE_REUSED'
            else:
                completed=run_one(control,operator,wall_seconds=45,memory_mb=384)
                if completed.get('job')!=submitted['job']:raise RuntimeError('Unexpected queue job; no further work taken over')
                job=submitted['job'];status=completed['status']
            with control.connect() as db:
                row=db.execute('SELECT body FROM results WHERE job=?',(job,)).fetchone()
            evaluated=json.loads(row[0]) if row else None
            entry={'key':key,'symbol':symbol,'job':job,'status':status,'intents':len(intents),'detected':result['detections'],'qualification_rejections':result['rejections'],
                   'planned_rr_min':min(result['qualified_planned_rr']),'planned_rr_max':max(result['qualified_planned_rr']),
                   'net_planned_rr_min':min(result['qualified_net_planned_rr']),
                   'periods':evaluated['periods'] if evaluated else None,'resources':evaluated.get('resources') if evaluated else None}
            ledger.append(entry);(folder/'evaluations.json').write_text(json.dumps(ledger,indent=2),encoding='utf-8')
            print(json.dumps({'key':key,'symbol':symbol,'status':status,'intents':len(intents),
                              'test':evaluated['periods']['test']['normal'] if evaluated else None}),flush=True)
    public=control.public()
    (folder/'research_leaderboard.json').write_text(json.dumps({'new_candidate_results':[r for r in public['research_leaderboard'] if r['strategy'] in keys],
         'multiple_testing_family':public['multiple_testing_family'],'qualified_leaderboard':public['qualified_leaderboard'],'production_activation':False},indent=2),encoding='utf-8')

if __name__=='__main__':main()
