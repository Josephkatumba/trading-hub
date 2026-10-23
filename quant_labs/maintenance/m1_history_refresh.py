"""Maintenance-window M1 history retrieval into a NEW research cache and dataset.

Run only inside an approved maintenance window (see docs/M1_MAINTENANCE_RUNBOOK.md):
TradeDen stopped, MT5 "Max bars in chart" raised and the terminal restarted.

Safety:
  * refuses while the TradeDen engine answers on 127.0.0.1:8000 (no competing session);
  * refuses unless terminal_info().maxbars >= --min-maxbars (default 1,000,000);
  * downloads broker M1 bars only, through backend/research/history.download (verified time
    normalisation; bars that cannot be normalised are dropped, never guessed);
  * never fills gaps; reports them;
  * writes a new cache folder; M15/H1/H4/D1 files are copied byte-for-byte from the existing
    cache; the existing cache, shared dataset and control-plane settings are not modified;
  * checks that every minute present in both the old and new M1 series is identical;
  * snapshots the new cache as a new content-addressed dataset and prints its ID.
Adopting the new dataset for evaluation is a separate owner decision.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OLD_CACHE = ROOT / 'backend/data/research/bars'
TERMINAL = r'C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe'


def engine_running(url='http://127.0.0.1:8000/api/quant-labs/live'):
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False


def load(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def compare_overlap(old, new):
    """Minutes present in both series must be identical (no silent revisions)."""
    old_by = {b['utc']: b for b in old}
    keys = ('open', 'high', 'low', 'close', 'spread')
    overlap = differ = 0
    for b in new:
        o = old_by.get(b['utc'])
        if o is not None:
            overlap += 1
            differ += any(abs(o[k] - b[k]) > 1e-12 for k in keys)
    return {'overlap_minutes': overlap, 'differing_minutes': differ}


def gaps(bars, step=60):
    return sum(1 for a, b in zip(bars, bars[1:]) if b['utc'] - a['utc'] != step)


def refresh(mt5, download, symbols, start, end, out_dir, old_cache=OLD_CACHE):
    """Core procedure with injectable mt5/download (tested with fakes)."""
    out_dir.mkdir(parents=True, exist_ok=False)
    old_manifest = json.loads((old_cache / 'manifest.json').read_text(encoding='utf-8'))
    manifest = {**old_manifest, 'end': end.isoformat(), 'symbols': {}, 'm1_extension': {'requested_start': start.isoformat(), 'at': datetime.now(timezone.utc).isoformat()}}
    report = {}
    for symbol in symbols:
        entry = dict(old_manifest['symbols'][symbol])
        for tf in ('M15', 'H1', 'H4', 'D1'):
            shutil.copy2(old_cache / f'{symbol}_{tf}.json.gz', out_dir / f'{symbol}_{tf}.json.gz')
        bars = download(mt5, entry['meta']['broker_symbol'], 'M1', start, end)
        old = load(old_cache / f'{symbol}_M1.json.gz') if (old_cache / f'{symbol}_M1.json.gz').exists() else []
        with gzip.open(out_dir / f'{symbol}_M1.json.gz', 'wt', encoding='utf-8') as f:
            json.dump(bars, f, separators=(',', ':'))
        entry['M1'] = {'bars': len(bars), 'first': datetime.fromtimestamp(bars[0]['utc'], timezone.utc).isoformat() if bars else None,
                       'last': datetime.fromtimestamp(bars[-1]['utc'], timezone.utc).isoformat() if bars else None}
        manifest['symbols'][symbol] = entry
        report[symbol] = {**entry['M1'], 'previous_bars': len(old), 'gaps_reported_not_filled': gaps(bars), **compare_overlap(old, bars)}
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2024-10-15')
    p.add_argument('--min-maxbars', type=int, default=1_000_000)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    old_manifest = json.loads((OLD_CACHE / 'manifest.json').read_text(encoding='utf-8'))
    symbols = sorted(s for s, v in old_manifest['symbols'].items() if 'meta' in v)
    plan = {'symbols': symbols, 'start': a.start, 'engine_running': engine_running(), 'terminal': TERMINAL}
    if not a.apply:
        print(json.dumps({'mode': 'PREFLIGHT_ONLY', **plan}, indent=1))
        return
    if plan['engine_running']:
        raise SystemExit('TradeDen engine is running; stop it in the approved maintenance window first')
    sys.path.insert(0, str(ROOT / 'backend'))
    import MetaTrader5 as mt5
    from research.history import download
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f'MT5 initialize failed: {mt5.last_error()}')
    try:
        maxbars = mt5.terminal_info().maxbars
        if maxbars < a.min_maxbars:
            raise SystemExit(f'terminal maxbars={maxbars} < {a.min_maxbars}; raise "Max. bars in chart" and restart MT5 first')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out = ROOT / f'backend/data/research/bars_m1_extended_{stamp}'
        report = refresh(mt5, download, symbols, datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc), datetime.now(timezone.utc), out)
    finally:
        mt5.shutdown()  # closes this script's IPC connection only
    sys.path.insert(0, str(ROOT))
    from quant_labs.data import snapshot
    dataset = snapshot(out, ROOT / 'quant_labs/state/shared')
    result = {'maxbars': maxbars, 'cache': str(out), 'new_dataset': dataset, 'symbols': report,
              'adoption': 'NOT ADOPTED: control-plane dataset setting unchanged; owner decision required'}
    (out / 'REFRESH_REPORT.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
