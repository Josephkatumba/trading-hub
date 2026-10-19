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
    commands.add_parser('report');args=parser.parse_args();store=Store(args.store)
    if args.command=='register':
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        store.register(manifest,Path(args.source).read_text(encoding='utf-8'),{'lab':manifest['lab'],'session_reference':args.session_reference})
    elif args.command=='status':store.set_status(args.lab,args.key,args.version,args.status)
    print(json.dumps(snapshot(store),indent=2))

if __name__=='__main__':main()
