"""Local socket smoke test: PAUSED only, never initializes or closes MT5."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

backend = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    state = root / 'control.json'
    state.write_text(json.dumps({'state': 'PAUSED'}))
    env = {**os.environ, 'TRADEDEN_CONTROL_FILE': str(state), 'TRADING_HUB_DATA_DIR': directory}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with (root/'engine.log').open('w') as log:
        child = subprocess.Popen([sys.executable, '-m', 'ops.engine'], cwd=backend, env=env, creationflags=flags, stdout=log, stderr=log)
        try:
            for _ in range(60):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
                        health = json.load(response)
                    break
                except OSError:
                    if child.poll() is not None:
                        raise AssertionError('Engine exited: ' + (root/'engine.log').read_text())
                    time.sleep(.25)
            else:
                raise AssertionError('Paused API did not start')
            assert health['process_control']['state'] == 'PAUSED', health
            assert health['execution_enabled'] is False
            assert health['mt5_connected'] is False
            assert not health['telegram_alerts']['running']
            assert not health['telegram_reports']['running']
            duplicate = subprocess.Popen([sys.executable, '-m', 'ops.engine'], cwd=backend, env=env, creationflags=flags, stdout=log, stderr=log)
            assert duplicate.wait(timeout=10) == 0
            assert child.poll() is None
            print('PASS: paused dashboard API; MT5 disconnected; Telegram/report workers inactive; duplicate engine rejected')
            state.write_text(json.dumps({'state': 'STOPPED'}))
            assert child.wait(timeout=20) == 0
            dog = subprocess.Popen([sys.executable, '-m', 'ops.watchdog', '--loop'], cwd=backend, env=env, creationflags=flags, stdout=log, stderr=log)
            assert dog.wait(timeout=10) == 0
            print('PASS: graceful STOPPED exit; stopped watchdog exits without recovery; no MT5 launch requested')
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
