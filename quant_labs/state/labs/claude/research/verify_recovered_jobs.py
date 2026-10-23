"""Reproducibility check for recovered jobs (read-only with respect to all ledgers).

Re-runs each recovered job's exact immutable request with the same trusted run_process /
frozen worker in a temporary directory outside OneDrive and compares the periods and
trades with research/queue_runs/recovered_evaluations.json. Writes only a report.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from quant_labs.queue import run_process
from quant_labs.data import canonical, digest

HERE = Path(__file__).resolve().parent
records = json.loads((HERE / 'queue_runs/recovered_evaluations.json').read_text(encoding='utf-8'))
report = []
for rec in records:
    original = ROOT / 'quant_labs/state/runtime' / rec['original_job']
    payload = json.loads((original / 'worker-input.json').read_text())
    if digest(canonical(json.loads((original / 'request.json').read_bytes()))) != rec['request_sha256']:
        raise ValueError('request changed since recovery')
    with tempfile.TemporaryDirectory(prefix='tradeden_claude_verify_') as temporary:
        shutil.copyfile(original / 'request.json', Path(temporary) / 'request.json')
        result = run_process(temporary, payload, 45)
    same = result['status'] == 'COMPLETE' and result['periods'] == rec['result']['periods'] and result['trades'] == rec['result']['trades']
    report.append({'strategy': rec['strategy'], 'original_job': rec['original_job'], 'request_sha256': rec['request_sha256'],
                   'evaluator': rec['evaluator'], 'status': result['status'], 'identical_periods_and_trades': same})
    print(json.dumps(report[-1]))
(HERE / 'queue_runs/recovered_reproducibility.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
