"""Identity of the M5 extension, bound to the frozen v1 evaluator identity it wraps."""
import json
from pathlib import Path
from ..data import canonical, digest
from ..frozen import VERSION_DIR, verify as verify_v1

FOLDER = Path(__file__).resolve().parent
FILES = ('__init__.py', 'data.py', 'engine.py', 'frozen.py', 'control.py', 'queue.py', 'worker.py', 'cli.py')
VERSION = 'tradeden-m5-extension-1.0.0'


def v1_identity():
    return digest((VERSION_DIR / 'freeze.json').read_bytes())


def seal():
    manifest = {'version': VERSION, 'files': {name: digest((FOLDER / name).read_bytes()) for name in FILES},
                'wraps_v1_evaluator': v1_identity(),
                'origin': 'separately versioned M5 admission layer; v1 evaluator and trusted interfaces unchanged'}
    (FOLDER / 'freeze.json').write_bytes(canonical(manifest))
    return digest(canonical(manifest))


def identity():
    return digest((FOLDER / 'freeze.json').read_bytes())


def verify(expected=None):
    raw = (FOLDER / 'freeze.json').read_bytes()
    if expected is not None and digest(raw) != expected:
        raise ValueError('M5 extension identity differs from registered contract')
    manifest = json.loads(raw)
    for name, sha in manifest['files'].items():
        if digest((FOLDER / name).read_bytes()) != sha:
            raise ValueError('M5 extension modified: ' + name)
    verify_v1(manifest['wraps_v1_evaluator'])  # also checks v1 files and trusted interfaces
    return manifest
