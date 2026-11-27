"""Bounded M5 evaluation worker (same Job Object limits as v1); runs no lab source code."""
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quant_labs.resources import enforce, usage
from quant_labs.data import SharedData, digest, canonical


def atomic(path, obj):
    """Atomic replace that tolerates the brief OneDrive/AV lock seen on freshly written files."""
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(canonical(obj))
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def main(path):
    payload = json.loads(Path(path).read_text())
    folder = Path(path).resolve().parent
    output = folder / 'worker-result.json'
    started = time.monotonic()
    timer = threading.Timer(payload['wall_seconds'] + 2, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        enforce(payload['memory_mb'], payload['cpu_percent'], payload['cpu_seconds'])
        from quant_labs.m5 import frozen
        frozen.verify(payload['m5_extension'])
        from quant_labs.m5.data import M5SharedData
        from quant_labs.m5.engine import evaluate
        request = json.loads((folder / 'request.json').read_text())
        if digest(canonical(request)) != payload['request_sha256']:
            raise ValueError('immutable request modified')
        checkpoint_file = folder / 'checkpoint.json'
        checkpoint = json.loads(checkpoint_file.read_text()) if checkpoint_file.exists() else None
        data = M5SharedData(SharedData(Path(payload['root']) / 'shared', request['dataset']))
        result = evaluate(data, request, checkpoint, lambda record: atomic(checkpoint_file, record), lambda: (folder / 'pause').exists())
        result.pop('checkpoint', None)
        result['resources'] = {**usage(), 'wall_seconds': time.monotonic() - started}
        atomic(output, result)
    except MemoryError:
        atomic(output, {'status': 'RESOURCE_LIMIT', 'reason': 'Windows committed-memory cap reached', 'resources': usage()})
    except Exception as exc:
        atomic(output, {'status': 'FAILED', 'reason': repr(exc), 'resources': usage()})
    finally:
        timer.cancel()


if __name__ == '__main__':
    main(sys.argv[1])
