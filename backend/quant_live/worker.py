"""Isolated bounded pure-model worker. No broker handle, I/O builtins or notifier."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quant_live.resources import enforce,usage
from quant_live.model_host import execute

def main(path):
    folder=Path(path).resolve().parent;payload=json.loads(Path(path).read_text(encoding='utf-8'))
    timer=threading.Timer(6,lambda:os._exit(124));timer.daemon=True;timer.start()
    try:
        enforce(memory_mb=192,cpu_percent=15,cpu_seconds=4)
        if hashlib.sha256(payload['source'].encode()).hexdigest()!=payload['source_sha256']:raise ValueError('model version source changed')
        result={'status':'COMPLETE','decisions':execute(payload['source'],payload['snapshot']),'resources':usage()}
    except Exception as exc:result={'status':'FAILED','reason':type(exc).__name__+': '+str(exc),'resources':usage()}
    finally:timer.cancel()
    (folder/'result.json').write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
if __name__=='__main__':main(sys.argv[1])
