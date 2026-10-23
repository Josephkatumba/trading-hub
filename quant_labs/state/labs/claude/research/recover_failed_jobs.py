"""Supplemental exact-request recovery for Claude jobs that failed on a transient I/O error.

Follows the established pattern of quant_labs/next_phase/retry_evaluations.py: the
canonical FAILED job, its runtime folder and ledger rows are left untouched; the exact
immutable request is re-run by the same trusted run_process/frozen worker in a temporary
directory outside the OneDrive-synced workspace (root cause: OneDrive briefly locks
freshly written checkpoint files, so the worker's atomic rename gets 'Access is denied').
Only PermissionError failures are retried; any other failure stays for investigation.
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from quant_labs.queue import run_process  # trusted interface, unchanged
from quant_labs.data import canonical, digest

STATE = ROOT / 'quant_labs/state'
OUT = Path(__file__).resolve().parent / 'queue_runs' / 'recovered_evaluations.json'


def main():
    db = sqlite3.connect(f"file:{(STATE / 'control.sqlite3').as_posix()}?mode=ro", uri=True)
    failed = db.execute("SELECT id,strategy,version FROM jobs WHERE lab='claude' AND state='FAILED' ORDER BY created").fetchall()
    records = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else []
    done = {r['original_job'] for r in records if r['retry_status'] == 'COMPLETE'}
    for job, strategy, version in failed:
        if job in done:
            continue
        original = STATE / 'runtime' / job
        original_result = json.loads((original / 'worker-result.json').read_text())
        if 'PermissionError' not in original_result.get('reason', ''):
            print(json.dumps({'job': job, 'skipped': 'non-transient failure; operator investigation required'}))
            continue
        payload = json.loads((original / 'worker-input.json').read_text())
        request = (original / 'request.json').read_bytes()
        if digest(canonical(json.loads(request))) != payload['request_sha256']:
            raise ValueError('immutable request changed; recovery refused')
        with tempfile.TemporaryDirectory(prefix='tradeden_claude_retry_') as temporary:
            destination = Path(temporary)
            shutil.copyfile(original / 'request.json', destination / 'request.json')
            result = run_process(destination, payload, 45)
        record = {'strategy': strategy, 'version': version, 'original_job': job, 'original_status': 'FAILED',
                  'original_failure': original_result, 'retry_status': result['status'], 'request_sha256': payload['request_sha256'],
                  'evaluator': payload['evaluator'], 'result': result,
                  'recovery': 'Exact immutable request, same frozen worker/accounting, temporary directory outside the synced workspace; canonical FAILED job unchanged.'}
        records.append(record)
        OUT.write_text(json.dumps(records, indent=1), encoding='utf-8')
        test = result.get('periods', {}).get('test', {}).get('normal', {})
        print(json.dumps({'strategy': strategy, 'job': job[:8], 'retry_status': result['status'], 'test_exp': test.get('net_expectancy_r'),
                          'wall_s': round(result.get('resources', {}).get('wall_seconds', 0), 1)}))


if __name__ == '__main__':
    main()
