"""Local owner registry tools. No delivery activation or broker order commands."""
import argparse
import json
from pathlib import Path
from .store import Store
from .report import snapshot

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',required=True,help='Explicit local live registry directory')
    commands=parser.add_subparsers(dest='command',required=True)
    register=commands.add_parser('register')
    register.add_argument('--manifest',required=True);register.add_argument('--source',required=True)
    register.add_argument('--session-reference',required=True,help='Actual authoring AI session evidence, never an invented attribution')
    state=commands.add_parser('status');state.add_argument('--lab',choices=['codex','claude','kimi'],required=True)
    state.add_argument('--key',required=True);state.add_argument('--version',required=True)
    state.add_argument('--set',dest='status',choices=['EXPERIMENTAL','ARCHIVED','DISABLED','REJECTED'],required=True)
    approve=commands.add_parser('approve-delivery',help='Record an explicit CEO approval for EXPERIMENTAL paper-signal Telegram delivery')
    approve.add_argument('--approval',required=True,help='JSON file: approved_by, directive, production=false, scope=[{lab,key,version,tier}]')
    revoke=commands.add_parser('revoke-delivery');revoke.add_argument('--reason',required=True)
    cat=commands.add_parser('approve-category',help='Record CEO approval for research_observations or intel_briefings delivery')
    cat.add_argument('--category',required=True,choices=['research_observations','intel_briefings']);cat.add_argument('--approval',required=True)
    rcat=commands.add_parser('revoke-category');rcat.add_argument('--category',required=True,choices=['research_observations','intel_briefings']);rcat.add_argument('--reason',required=True)
    commands.add_parser('report');args=parser.parse_args();store=Store(args.store)
    if args.command=='register':
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        store.register(manifest,Path(args.source).read_text(encoding='utf-8'),{'lab':manifest['lab'],'session_reference':args.session_reference})
    elif args.command=='status':store.set_status(args.lab,args.key,args.version,args.status)
    elif args.command=='approve-delivery':store.approve_delivery(json.loads(Path(args.approval).read_text(encoding='utf-8')))
    elif args.command=='revoke-delivery':store.revoke_delivery(args.reason)
    elif args.command=='approve-category':store.approve_category(args.category,json.loads(Path(args.approval).read_text(encoding='utf-8')))
    elif args.command=='revoke-category':store.revoke_category(args.category,args.reason)
    print(json.dumps(snapshot(store),indent=2))

if __name__=='__main__':main()
