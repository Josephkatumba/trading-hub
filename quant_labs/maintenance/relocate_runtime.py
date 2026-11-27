"""Move temporary evaluation runtime folders out of OneDrive (CEO-approved 2026-10-20).

Root cause addressed: OneDrive briefly locks freshly written files, so the frozen v1
worker's atomic checkpoint rename intermittently fails with PermissionError(13).

The frozen queue/worker hard-code `<state>/runtime`, so nothing in them changes. This tool:
  1. refuses to run while any v1 or M5 job is RUNNING;
  2. writes a permanent evidence archive (zip) and SHA-256 manifest of every runtime
     file into `<state>/runtime_relocation/` (stays in the repository / OneDrive);
  3. copies the folder to a local target, verifies every hash, and replaces the original
     folder with a directory junction pointing at the target;
  4. re-verifies every hash through the junction and records the location in
     `<state>/runtime_location.json`.

Target is configurable: --target, else TRADEDEN_QUANT_RUNTIME_DIR, else
%LOCALAPPDATA%/TradeDen/quant_labs. Default is a dry run; pass --apply to change anything.
Permanent records (control.sqlite3 results/events, lab exports, source hashes) are not touched.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import zipfile

STATE = Path(__file__).resolve().parents[1] / 'state'
FOLDERS = {'v1': Path('runtime'), 'm5': Path('m5') / 'runtime'}


def default_target():
    return Path(os.environ.get('TRADEDEN_QUANT_RUNTIME_DIR') or Path(os.environ['LOCALAPPDATA']) / 'TradeDen' / 'quant_labs')


def is_junction(path):
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400) and Path(path).is_dir()  # FILE_ATTRIBUTE_REPARSE_POINT
    except (FileNotFoundError, AttributeError):
        return False


def hashes(folder):
    out = {}
    for p in sorted(Path(folder).rglob('*')):
        if p.is_file():
            out[p.relative_to(folder).as_posix()] = {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
    return out


def running_jobs(state):
    total = 0
    for db in (state / 'control.sqlite3', state / 'm5' / 'control_m5.sqlite3'):
        if db.exists():
            c = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True)
            total += c.execute("SELECT count(*) FROM jobs WHERE state='RUNNING'").fetchone()[0]
            c.close()
    return total


def retry(action, attempts=40):
    """OneDrive briefly locks freshly written paths; retry renames/removals with bounded back-off."""
    import time
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(min(0.1 * (attempt + 1), 1.0))


def junction(link, target):
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
    if result.returncode != 0 or not is_junction(link):
        raise RuntimeError('junction creation failed: ' + (result.stderr or result.stdout).strip())


def relocate(state, target, apply=False, only=None):
    state, target = Path(state).resolve(), Path(target).resolve()
    if running_jobs(state):
        raise RuntimeError('an evaluation job is RUNNING; relocate only while the queues are idle')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence_dir = state / 'runtime_relocation'
    report = {'at': stamp, 'target_root': str(target), 'apply': apply, 'folders': {}}
    for name, rel in FOLDERS.items():
        if only and name != only:
            continue
        source = state / rel
        destination = target / name
        if not source.exists():
            report['folders'][name] = {'status': 'ABSENT'}
            continue
        if is_junction(source):
            report['folders'][name] = {'status': 'ALREADY_RELOCATED', 'resolves_to': str(source.resolve())}
            continue
        before = hashes(source)
        entry = {'source': str(source), 'destination': str(destination), 'files': len(before), 'bytes': sum(v['bytes'] for v in before.values())}
        if apply:
            resumed = destination.exists() and any(destination.iterdir())
            if resumed and hashes(destination) != before:
                raise RuntimeError(f'destination not empty and differs from source: {destination}')
            evidence_dir.mkdir(exist_ok=True)
            manifest = evidence_dir / f'{name}_runtime_manifest_{stamp}.json'
            manifest.write_text(json.dumps(before, indent=1), encoding='utf-8')
            archive = evidence_dir / f'{name}_runtime_{stamp}.zip'
            with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
                for relpath in before:
                    z.write(source / relpath, relpath)
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None or sorted(z.namelist()) != sorted(before):
                    raise RuntimeError('evidence archive verification failed')
            if not resumed:
                shutil.copytree(source, destination, dirs_exist_ok=True)
            if hashes(destination) != before:
                raise RuntimeError('copy verification failed; original left in place')
            parked = source.with_name(source.name + '.pre_relocation')
            try:
                retry(lambda: source.rename(parked))
            except PermissionError:
                raise RuntimeError(f'{source} is locked (typically a shell/process whose current directory is inside it). '
                                   'Originals are untouched; a verified copy is at the destination. Close that process and re-run with --apply.')
            try:
                junction(source, destination)
            except Exception:
                retry(lambda: parked.rename(source))
                raise
            if hashes(source) != before:
                raise RuntimeError(f'junction verification failed; originals kept at {parked}')
            retry(lambda: shutil.rmtree(parked))  # verified copy + permanent archive/manifest exist
            entry.update(status='RELOCATED', evidence_archive=str(archive.relative_to(state)), evidence_manifest=str(manifest.relative_to(state)),
                         manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(), verified_files=len(before))
        else:
            entry['status'] = 'DRY_RUN'
        report['folders'][name] = entry
    if apply:
        location = state / 'runtime_location.json'
        history = json.loads(location.read_text(encoding='utf-8')).get('history', []) if location.exists() else []
        location.write_text(json.dumps({'current': {n: str((target / n)) for n in FOLDERS}, 'configured_by': 'quant_labs/maintenance/relocate_runtime.py',
                                        'env_override': 'TRADEDEN_QUANT_RUNTIME_DIR', 'history': history + [report]}, indent=1), encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', default=str(STATE))
    p.add_argument('--target', default=None)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--only', choices=sorted(FOLDERS))
    a = p.parse_args()
    print(json.dumps(relocate(a.state, a.target or default_target(), a.apply, a.only), indent=1))


if __name__ == '__main__':
    main()
