"""Provision independent workspaces and import Codex's own prior research provenance."""
import json
from pathlib import Path
from .control import ControlPlane,LABS,REQUIRED
from .data import snapshot,digest
from .frozen import VERSION_DIR,verify

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
DEFAULT_STATE=BASE/'state'

def setup(root=DEFAULT_STATE,import_codex=True):
    root=Path(root).resolve();control=ControlPlane(root)
    if 'dataset' not in control.settings():
        evaluator=digest((VERSION_DIR/'freeze.json').read_bytes());verify(evaluator)
        dataset=snapshot(ROOT/'backend/data/research/bars',root/'shared')
        control.initialize(dataset,evaluator)
    for lab,name in LABS.items():
        instructions=f'''# {name}: independent development workspace

Your research ownership is `{lab}`. You may invent, reject and version any technically
supported hypothesis; there is no strategy-count limit. Own code and notes belong here.
Do not modify another laboratory, the shared data, evaluator, owner credentials,
production engine, Telegram settings, or historical records. Do not execute lab code
through the shared evaluator: submit declarative intents and retain source for review.

Use only this workspace's `.lab-token` for submission. Never use owner/reviewer/CEO
credentials to self-certify results. Record every variant and failed attempt. Increment
versions whenever rules or parameters change. Historical intents alone cannot prove
causality: source review and prospective evidence are required. A high planned R:R or
60–70% aspirational win rate is not a qualification criterion on its own.

See `quant_labs/docs/INTEGRATION.md` for the common schema and CLI. This workspace
starts ready for independent research; setup does not mean {name} has run experiments.

Application permissions do not constrain an unrestricted same-user shell. Do not grant
an untrusted agent unrestricted filesystem access; separate Windows identities or
containers are required for adversarial isolation. The common worker never runs your code.
'''
        if not (control.workspace(lab)/'AGENTS.md').exists():(control.workspace(lab)/'AGENTS.md').write_text(instructions,encoding='utf-8')
        if not (control.workspace(lab)/'README.md').exists():(control.workspace(lab)/'README.md').write_text(f'# {name}\n\nIndependent research workspace. Read AGENTS.md and the common integration guide before submitting.\n',encoding='utf-8')
        (control.workspace(lab)/'strategies').mkdir(exist_ok=True)
        (control.workspace(lab)/'notes').mkdir(exist_ok=True)
    if import_codex:
        old=ROOT/'research_autonomous/strategy_catalog.json'
        if old.exists():
            token=(control.workspace('codex')/'.lab-token').read_text(encoding='utf-8')
            for entry in json.loads(old.read_text(encoding='utf-8')):
                try:control.get_strategy('codex',entry['key'],entry['version']);continue
                except KeyError:pass
                source=(ROOT/'research_autonomous/hypotheses.py').read_text(encoding='utf-8')
                prior=[]
                for result in entry['market_results']:
                    periods=result.get('statistics',{})
                    prior.append({'experiment_id':result['experiment_id'],'symbol':result['symbol'],'status':result['status'],
                                  'test_resolved':periods.get('test',{}).get('normal',{}).get('resolved'),
                                  'test_expectancy_r':periods.get('test',{}).get('normal',{}).get('expectancy_r'),
                                  'test_total_r':periods.get('test',{}).get('normal',{}).get('total_r')})
                spec={'id':entry['key'],'version':entry['version'],'name':entry['key'],'timeframe':'H1','hypothesis':entry['idea'],
                      'entry_conditions':entry['entry_rule'],'exit_conditions':entry['target_rule']+f" Maximum hold {entry['horizon_hours']}h.",
                      'stop_loss_method':entry['stop_rule'],'take_profit_method':entry['target_rule'],'risk_model':entry['risk_model'],
                      'intended_conditions':entry['intended_regime'],'limitations':entry['limitations'],'declared_trials':16,
                      'prior_research':{'verified_by_shared_evaluator':False,'qualification':'NOT_QUALIFIED','forward_performance':None,
                                       'provenance':'research_autonomous/strategy_catalog.json','market_results':prior}}
                control.register(token,'codex',spec,source)
    return control

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(DEFAULT_STATE));args=parser.parse_args()
    control=setup(args.root);print(json.dumps({'labs':list(LABS),'dataset':control.settings()['dataset'],'evaluator':control.settings()['evaluator'],'production_connected':False},indent=2))
