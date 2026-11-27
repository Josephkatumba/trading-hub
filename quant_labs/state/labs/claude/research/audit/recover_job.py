"""Exact-request recovery of any lab's job that FAILED on the OneDrive PermissionError lock.

Same pattern as research/recover_failed_jobs.py and quant_labs/next_phase/retry_evaluations.py:
the canonical FAILED job and the owning lab's records are untouched; the immutable request is
re-run by the trusted run_process/frozen worker in a temp folder outside OneDrive, and the
result is written to this audit folder only.
Usage: python recover_job.py <job_id_prefix>
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))
from quant_labs.queue import run_process
from quant_labs.data import canonical, digest

STATE = ROOT / 'quant_labs/state'
OUT = Path(__file__).resolve().parent / 'recovered'
OUT.mkdir(exist_ok=True)
prefix = sys.argv[1]
db = sqlite3.connect(f"file:{(STATE / 'control.sqlite3').as_posix()}?mode=ro", uri=True)
job, lab, strategy, version, state = db.execute("SELECT id,lab,strategy,version,state FROM jobs WHERE id LIKE ?", (prefix + '%',)).fetchone()
assert state == 'FAILED', state
original = STATE / 'runtime' / job
failure = json.loads((original / 'worker-result.json').read_text())
assert 'PermissionError' in failure.get('reason', ''), failure
payload = json.loads((original / 'worker-input.json').read_text())
assert digest(canonical(json.loads((original / 'request.json').read_bytes()))) == payload['request_sha256']
with tempfile.TemporaryDirectory(prefix='tradeden_audit_retry_') as tmp:
    shutil.copyfile(original / 'request.json', Path(tmp) / 'request.json')
    result = run_process(tmp, payload, 45)
record = {'lab': lab, 'strategy': strategy, 'version': version, 'original_job': job, 'original_failure': failure,
          'request_sha256': payload['request_sha256'], 'evaluator': payload['evaluator'], 'retry_status': result['status'], 'result': result}
(OUT / f'{lab}_{strategy}_{version}_{job[:8]}.json').write_text(json.dumps(record), encoding='utf-8')
print(json.dumps({'lab': lab, 'strategy': strategy, 'version': version, 'job': job[:8], 'status': result['status']}))
