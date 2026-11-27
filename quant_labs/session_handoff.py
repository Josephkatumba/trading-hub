"""Read-only engine checks and consistent local database snapshots; no restart."""
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    private = ROOT / 'quant_labs/session_private_backups' / stamp
    private.mkdir(parents=True)
    snapshots = []
    for relative in ('quant_labs/state/control.sqlite3', 'backend/data/quant_live/signals.sqlite3'):
        source = ROOT / relative
        target = private / (source.parent.name + '_' + source.name)
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
                check = dst.execute('PRAGMA integrity_check').fetchone()[0]
                assert check == 'ok', (relative, check)
        snapshots.append({'source': relative, 'snapshot': str(target.relative_to(ROOT)),
                          'integrity_check': check, 'bytes': target.stat().st_size,
                          'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    def get(route):
        with urllib.request.urlopen('http://127.0.0.1:8000' + route, timeout=20) as response:
            return json.load(response)
    from quant_labs.live_observation.control import permission_summary
    health = get('/api/health')
    live = get('/api/quant-labs/live')
    baseline = json.loads((ROOT / 'quant_labs/next_phase/live_baseline.json').read_text())
    # Evidence schemas differ between observation phases; retain explicit current flags.
    permissions = permission_summary(health)
    assert permissions == permission_summary(baseline['health']), 'Production permission drift'
    assert health.get('strategy_bank', {}).get('telegram_enabled') == baseline['health'].get('strategy_bank', {}).get('telegram_enabled')
    assert health.get('ok') is True and health.get('mt5_connected') is True
    assert permissions['execution_enabled'] is False
    assert live.get('telegram_mode') == 'DRY_RUN' and live.get('outbound_activation_approved') is False
    freeze_path = ROOT / 'quant_labs/evaluation/v1/freeze.json'
    freeze = json.loads(freeze_path.read_text())
    checked = 0
    for group, folder in (('files', freeze_path.parent), ('trusted_interfaces', ROOT / 'quant_labs')):
        for name, expected in freeze[group].items():
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected, name
            checked += 1
    blobs = ROOT / 'quant_labs/state/shared/blobs'
    inventory = [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size,
                  'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in sorted(blobs.rglob('*')) if p.is_file()]
    evidence = {'captured_at': stamp, 'engine_ok': health.get('ok'),
                'mt5_connected': health.get('mt5_connected'), 'uptime_started': health.get('uptime_started'),
                'permissions': permissions, 'strategy_bank_telegram_enabled': health.get('strategy_bank', {}).get('telegram_enabled'),
                'paper_mode': live.get('mode'), 'telegram_mode': live.get('telegram_mode'),
                'outbound_activation_approved': live.get('outbound_activation_approved'),
                'runtime': live.get('runtime'), 'signals_in_current_view': len(live.get('signals', [])),
                'frozen_hashes_verified': checked, 'database_snapshots': snapshots,
                'retained_shared_blobs': inventory,
                'private_files_retained_in_place': ['backend/.env', 'quant_labs/state/owner/', 'quant_labs/state/labs/*/.lab-token'],
                'restart_performed': False, 'push_performed': False, 'deployment_performed': False}
    out = ROOT / 'quant_labs/SESSION_HANDOFF_VERIFICATION.json'
    out.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in evidence.items() if k not in ('runtime', 'retained_shared_blobs')}, indent=2))

if __name__ == '__main__':
    main()
