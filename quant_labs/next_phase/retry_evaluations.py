"""Supplemental exact-request recovery, preserving failed canonical job evidence."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from quant_labs.queue import run_process

folder=Path(__file__).resolve().parent
ledger=json.loads((folder/'evaluations.json').read_text(encoding='utf-8'));retries=[]
for entry in ledger:
    if entry['status']!='FAILED':continue
    original=ROOT/'quant_labs/state/runtime'/entry['job'];payload=json.loads((original/'worker-input.json').read_text())
    original_result=json.loads((original/'worker-result.json').read_text())
    if 'PermissionError' not in original_result.get('reason',''):continue
    with tempfile.TemporaryDirectory(prefix='tradeden_exact_retry_') as temporary:
        destination=Path(temporary);shutil.copyfile(original/'request.json',destination/'request.json')
        result=run_process(destination,payload,45)
    record={'key':entry['key'],'symbol':entry['symbol'],'original_job':entry['job'],'original_status':'FAILED',
            'original_failure':original_result,'retry_status':result['status'],'result':result,
            'request_sha256':payload['request_sha256'],'evaluator':payload['evaluator'],
            'recovery':'Exact immutable request, same frozen worker/accounting, temporary directory outside synced workspace; canonical FAILED job is unchanged.'}
    retries.append(record);(folder/'retry_evaluations.json').write_text(json.dumps(retries,indent=2),encoding='utf-8')
    print(json.dumps({'key':entry['key'],'symbol':entry['symbol'],'retry_status':result['status'],'resources':result.get('resources')}),flush=True)
