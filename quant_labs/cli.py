"""Explicit local commands; only `run-one` starts a bounded foreground worker."""
import argparse
import json
import os
from pathlib import Path
from .bootstrap import DEFAULT_STATE
from .control import ControlPlane
from .queue import run_one

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(DEFAULT_STATE));p.add_argument('--token-env',default='TRADEDEN_LAB_TOKEN')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('register');a.add_argument('lab');a.add_argument('spec');a.add_argument('source')
    a=sub.add_parser('submit');a.add_argument('lab');a.add_argument('strategy');a.add_argument('version');a.add_argument('intents');a.add_argument('--purpose',default='RESEARCH')
    for name in ('pause','resume'):
        a=sub.add_parser(name);a.add_argument('lab');a.add_argument('job')
    for name in ('queue-pause','queue-resume','run-one','status'):sub.add_parser(name)
    a=sub.add_parser('transition');a.add_argument('lab');a.add_argument('strategy');a.add_argument('version');a.add_argument('stage');a.add_argument('--evidence',default='{}')
    a=sub.add_parser('review');a.add_argument('job');a.add_argument('verdict');a.add_argument('evidence')
    args=p.parse_args();c=ControlPlane(args.root);token=os.getenv(args.token_env,'')
    if args.command=='register':result=c.register(token,args.lab,json.loads(Path(args.spec).read_text(encoding='utf-8')),Path(args.source).read_text(encoding='utf-8'))
    elif args.command=='submit':result=c.submit(token,args.lab,args.strategy,args.version,json.loads(Path(args.intents).read_text(encoding='utf-8')),args.purpose)
    elif args.command=='run-one':result=run_one(c,token)
    elif args.command=='pause':c.pause(token,args.lab,args.job);result={'status':'pause requested'}
    elif args.command=='resume':c.resume(token,args.lab,args.job);result={'status':'queued for resume'}
    elif args.command=='queue-pause':c.global_pause(token,True);result={'queue':'paused'}
    elif args.command=='queue-resume':c.global_pause(token,False);result={'queue':'ready; individual paused jobs still need resume'}
    elif args.command=='transition':result=c.transition(token,args.lab,args.strategy,args.version,args.stage,json.loads(args.evidence))
    elif args.command=='review':c.review(token,args.job,args.verdict,args.evidence);result={'status':'independent review recorded; no promotion'}
    else:result=c.public()
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
