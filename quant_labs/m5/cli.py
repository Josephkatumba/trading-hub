"""M5 extension commands.

  python -m quant_labs.m5.cli register-live --lab claude --manifest <m5-manifest.json> --source <model.py>
  python -m quant_labs.m5.cli submit claude <key> <version> <intents.json>
  python -m quant_labs.m5.cli --token-env TRADEDEN_OPERATOR_TOKEN run-one
  python -m quant_labs.m5.cli status
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from ..bootstrap import DEFAULT_STATE
from .control import M5Control
from .queue import run_one


def spec_from_live_manifest(manifest, lab):
    """Same mapping as provider_bridge.register_source, for an M5 live manifest."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    from quant_live.adapter import canonical as live_canonical
    if manifest.get('lab') != lab or manifest.get('authorship', {}).get('lab') != lab or not manifest.get('authorship', {}).get('session_reference'):
        raise ValueError('Own lab and actual authoring-session provenance required')
    return {'id': manifest['key'], 'version': manifest['version'], 'name': manifest['name'], 'timeframe': manifest['timeframe'],
            'hypothesis': manifest.get('hypothesis') or manifest['name'],
            'entry_conditions': 'Executable pure detect(snapshot), causally replayed with completed supplied candles only.',
            'exit_conditions': 'Fixed declared SL/TP and horizon from executable output; common frozen execution policy.',
            'stop_loss_method': manifest.get('risk_model', 'See registered executable.'),
            'take_profit_method': manifest.get('planned_rr', 'See registered executable.'),
            'risk_model': manifest.get('risk_model', 'One planned risk unit; simulated outcomes only.'),
            'intended_conditions': manifest.get('hypothesis') or manifest['name'],
            'limitations': manifest.get('known_limitations', 'No verified edge.'),
            'declared_trials': manifest.get('declared_trials_in_phase', 1), 'authorship': manifest['authorship'],
            'live_manifest_sha256': hashlib.sha256(live_canonical(manifest)).hexdigest()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', default=str(DEFAULT_STATE))
    p.add_argument('--token-env', default='TRADEDEN_LAB_TOKEN')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('register-live')
    a.add_argument('--lab', required=True)
    a.add_argument('--manifest', required=True)
    a.add_argument('--source', required=True)
    a = sub.add_parser('submit')
    a.add_argument('lab')
    a.add_argument('strategy')
    a.add_argument('version')
    a.add_argument('intents')
    a.add_argument('--purpose', default='RESEARCH')
    sub.add_parser('run-one')
    sub.add_parser('status')
    args = p.parse_args()
    control = M5Control(args.root)
    token = os.getenv(args.token_env, '').strip()
    if args.command == 'register-live':
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
        from quant_live.model_host import validate_source
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        source = Path(args.source).read_text(encoding='utf-8')
        validate_source(source)
        result = control.register(token, args.lab, spec_from_live_manifest(manifest, args.lab), source)
    elif args.command == 'submit':
        result = control.submit(token, args.lab, args.strategy, args.version, json.loads(Path(args.intents).read_text(encoding='utf-8')), args.purpose)
    elif args.command == 'run-one':
        result = run_one(control, token)
    else:
        result = control.public()
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
