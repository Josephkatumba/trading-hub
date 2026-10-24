"""Conservative TradeDen engine watchdog (no paid infrastructure).

Relaunches the market engine with the official launcher ONLY when its process is gone: the local
port 8000 is not listening for 3 consecutive checks. It never kills or restarts a running engine
(a slow or degraded engine is reported, not touched), allows at most 3 relaunches per hour, waits a
grace period after each launch, and appends every decision to data/ops/watchdog.jsonl.

  python -m ops.watchdog --once            one check, no action (diagnostic)
  python -m ops.watchdog --loop            supervise (opt-in; see docs for Task Scheduler setup)
  python -m ops.watchdog --loop --dry-run  supervise but only log what it would do
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8000
CHECK_SECONDS = 60
FAILS_BEFORE_LAUNCH = 3
GRACE_SECONDS = 240
MAX_LAUNCHES_PER_HOUR = 3


def port_listening(port=PORT, host='127.0.0.1'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        return s.connect_ex((host, port)) == 0


def health_ok(timeout=20):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/health', timeout=timeout) as r:
            d = json.load(r)
            return r.status == 200, d
    except Exception as exc:
        return False, {'error': type(exc).__name__}


def launch():
    """Start the engine the way backend/start_engine.bat does (uvicorn on 127.0.0.1:8000), but hidden.

    No cmd.exe wrapper: Popen escapes embedded quotes as \\" which cmd cannot parse, so the old
    'cmd /k cd /d "..."' relaunch failed and left a visible error window every time. Output goes to
    data/ops/engine.log instead of a console.
    """
    backend = ROOT / 'backend'
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and (exe.parent / 'python.exe').exists():
        exe = exe.parent / 'python.exe'
    log_path = backend / 'data/ops/engine.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    with log_path.open('a', encoding='utf-8') as log:
        log.write(f'\n--- watchdog relaunch {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n')
        log.flush()
        args = [str(exe), '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', str(PORT)]
        kw = dict(cwd=str(backend), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)
        try:  # outlive the watchdog's Task Scheduler job when the job allows it
            subprocess.Popen(args, creationflags=flags | getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0), **kw)
        except OSError:
            subprocess.Popen(args, creationflags=flags, **kw)


class Watchdog:
    def __init__(self, probe_port=port_listening, probe_health=health_ok, launcher=launch, clock=time.time, log_path=None, dry_run=False):
        self.probe_port, self.probe_health, self.launcher, self.clock, self.dry_run = probe_port, probe_health, launcher, clock, dry_run
        self.log_path = Path(log_path or ROOT / 'backend/data/ops/watchdog.jsonl')
        self.fails, self.launches, self.grace_until = 0, [], 0.0

    def log(self, **row):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at': self.clock(), **row}) + '\n')

    def tick(self):
        now = self.clock()
        if now < self.grace_until:
            return 'GRACE'
        if self.probe_port():
            self.fails = 0
            ok, detail = self.probe_health()
            state = 'HEALTHY' if ok and detail.get('mt5_connected') else 'DEGRADED_RUNNING'
            if state != 'HEALTHY':
                self.log(state=state, detail=detail, action='none (a running engine is never killed)')
            return state
        self.fails += 1
        if self.fails < FAILS_BEFORE_LAUNCH:
            self.log(state='DOWN_SUSPECTED', consecutive=self.fails)
            return 'DOWN_SUSPECTED'
        self.launches = [t for t in self.launches if now - t < 3600]
        if len(self.launches) >= MAX_LAUNCHES_PER_HOUR:
            self.log(state='DOWN', action='relaunch suppressed: hourly limit reached; manual attention needed')
            return 'DOWN_LIMIT'
        self.log(state='DOWN', action='relaunch' + (' (dry run)' if self.dry_run else ''))
        if not self.dry_run:
            self.launcher()
        self.launches.append(now)
        self.fails, self.grace_until = 0, now + GRACE_SECONDS
        return 'RELAUNCHED'


LOCK_PORT = 8799


def single_instance_lock():
    """Hold a loopback port for the process lifetime; a second watchdog cannot bind it and exits."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.setsockopt(socket.SOL_SOCKET, getattr(socket, 'SO_EXCLUSIVEADDRUSE', socket.SO_REUSEADDR), 1)
        lock.bind(('127.0.0.1', LOCK_PORT))
        lock.listen(1)
        return lock
    except OSError:
        lock.close()
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--once', action='store_true')
    p.add_argument('--loop', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    if a.once or not a.loop:
        ok, detail = health_ok()
        print(json.dumps({'port_listening': port_listening(), 'health_ok': ok,
                          'mt5_connected': detail.get('mt5_connected'), 'execution_enabled': detail.get('execution_enabled')}))
        return
    lock = single_instance_lock()
    dog = Watchdog(dry_run=a.dry_run)
    if lock is None:
        dog.log(state='WATCHDOG_ALREADY_RUNNING', action='exit (single instance)')
        return 0
    dog.log(state='WATCHDOG_STARTED', dry_run=a.dry_run)
    while True:
        dog.tick()
        time.sleep(CHECK_SECONDS)


if __name__ == '__main__':
    sys.exit(main())
