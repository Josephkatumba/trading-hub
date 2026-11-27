"""Evaluator identity covers execution, accounting and policy together."""
import json
from pathlib import Path
from .data import canonical,digest

VERSION_DIR=Path(__file__).resolve().parent/'evaluation/v1'
EXTRA=('data.py','worker.py','resources.py','control.py','queue.py')
def seal():
    files={p.name:digest(p.read_bytes()) for p in VERSION_DIR.iterdir() if p.suffix in ('.py','.json','.tzif') and p.name!='freeze.json'}
    manifest={'version':'tradeden-shared-eval-1.0.0','files':files,'trusted_interfaces':{name:digest((VERSION_DIR.parents[1]/name).read_bytes()) for name in EXTRA},'origin':'independent-execution-1.0.1; common accounting and policy frozen for all laboratories'}
    (VERSION_DIR/'freeze.json').write_bytes(canonical(manifest))
    return digest(canonical(manifest))
def verify(expected):
    raw=(VERSION_DIR/'freeze.json').read_bytes()
    if digest(raw)!=expected:raise ValueError('evaluator identity differs from registered frozen contract')
    manifest=json.loads(raw)
    actual={p.name for p in VERSION_DIR.iterdir() if p.suffix in ('.py','.json','.tzif') and p.name!='freeze.json'}
    if actual!=set(manifest['files']):raise ValueError('evaluator file inventory changed')
    for name,sha in manifest['files'].items():
        if digest((VERSION_DIR/name).read_bytes())!=sha:raise ValueError('frozen evaluator modified: '+name)
    for name,sha in manifest['trusted_interfaces'].items():
        if digest((VERSION_DIR.parents[1]/name).read_bytes())!=sha:raise ValueError('trusted evaluator interface modified: '+name)
    return manifest
