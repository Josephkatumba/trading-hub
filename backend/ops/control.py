"""Persistent owner intent. Missing/corrupt state fails closed at Windows logon."""
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STATE_FILE = Path(os.getenv('TRADEDEN_CONTROL_FILE', str(Path(__file__).resolve().parents[1] / 'data/ops/control.json')))


def read_state():
    try:
        value = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        if value['state'] not in ('RUNNING', 'PAUSED', 'STOPPED'):
            raise ValueError('invalid state')
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'STOPPED', 'reason': 'No valid owner start request'}


@contextmanager
def state_lock():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.with_suffix('.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
        stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def set_state(state, reason='Owner request', expected=None):
    with state_lock():
        if expected is not None and read_state()['state'] != expected:
            return
        _write_state(state, reason)


def _write_state(state, reason):
    if state not in ('RUNNING', 'PAUSED', 'STOPPED'):
        raise ValueError(state)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=STATE_FILE.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'state': state, 'reason': reason}, stream)
        os.replace(name, STATE_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'resume', 'pause', 'stop', 'status'])
    action = parser.parse_args().action
    if action != 'status':
        set_state({'start': 'RUNNING', 'resume': 'RUNNING', 'pause': 'PAUSED', 'stop': 'STOPPED'}[action])
    if action in ('start', 'resume'):
        from ops.watchdog import launch, port_listening
        if not port_listening():
            launch()
        subprocess.Popen([sys.executable, '-m', 'ops.watchdog', '--loop'],
                         cwd=Path(__file__).resolve().parents[1],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(json.dumps(read_state()))


if __name__ == '__main__':
    main()
