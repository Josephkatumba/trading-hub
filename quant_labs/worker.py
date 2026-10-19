"""Trusted bounded worker entry point; no user source imports or executable plugins."""
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quant_labs.resources import enforce,usage
from quant_labs.frozen import verify
from quant_labs.data import SharedData,digest,canonical

def atomic(path,obj):
    temporary=path.with_suffix('.tmp');temporary.write_bytes(canonical(obj));temporary.replace(path)

def main(path):
    payload=json.loads(Path(path).read_text());folder=Path(path).resolve().parent
    output=folder/'worker-result.json';started=time.monotonic()
    # Secondary bounded watchdog survives controller failure; evaluator has no daemon loop.
    timer=threading.Timer(payload['wall_seconds']+2,lambda:os._exit(124));timer.daemon=True;timer.start()
    try:
        limits=enforce(payload['memory_mb'],payload['cpu_percent'],payload['cpu_seconds'])
        if payload.get('probe')=='memory':
            bytearray(1024*1024*payload['memory_mb']*2)
        elif payload.get('probe')=='timeout':
            time.sleep(payload['wall_seconds']+5)
        elif payload.get('probe')=='limits':
            atomic(output,{'status':'COMPLETE','resources':usage()});return
        verify(payload['evaluator'])
        from quant_labs.evaluation.v1.engine import evaluate
        request=json.loads((folder/'request.json').read_text())
        if digest(canonical(request))!=payload['request_sha256']:raise ValueError('immutable request modified')
        checkpoint_file=folder/'checkpoint.json'
        checkpoint=json.loads(checkpoint_file.read_text()) if checkpoint_file.exists() else None
        def save(record):atomic(checkpoint_file,record)
        result=evaluate(SharedData(Path(payload['root'])/'shared',request['dataset']),request,checkpoint,save,lambda:(folder/'pause').exists())
        result.pop('checkpoint',None)
        result['resources']={**usage(),'wall_seconds':time.monotonic()-started}
        atomic(output,result)
    except MemoryError:
        atomic(output,{'status':'RESOURCE_LIMIT','reason':'Windows committed-memory cap reached','resources':usage()})
    except Exception as exc:
        atomic(output,{'status':'FAILED','reason':repr(exc),'resources':usage()})
    finally:timer.cancel()

if __name__=='__main__':main(sys.argv[1])
