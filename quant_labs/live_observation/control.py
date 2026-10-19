"""Controlled local restart preserving the running engine's effective environment.

Secrets stay in memory. Evidence contains public health data and equality checks,
never environment values for credentials or account identifiers.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
FLAG='TRADEDEN_QUANT_LIVE_ENABLED'

def read_env(pid):
    if sys.platform!='win32' or c.sizeof(c.c_void_p)!=8:raise RuntimeError('Requires verified x64 Windows process layout')
    kernel=c.WinDLL('kernel32',use_last_error=True);nt=c.WinDLL('ntdll')
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    nt.NtQueryInformationProcess.argtypes=[w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.c_void_p]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:raise c.WinError(c.get_last_error())
    def read(address,size):
        buf=c.create_string_buffer(size);got=c.c_size_t()
        if not kernel.ReadProcessMemory(handle,address,buf,size,c.byref(got)):raise c.WinError(c.get_last_error())
        return buf.raw[:got.value]
    try:
        info=(c.c_void_p*6)()
        if nt.NtQueryInformationProcess(handle,0,c.byref(info),c.sizeof(info),None)!=0:raise RuntimeError('Cannot inspect existing process environment')
        peb=read(info[1],0x40);params=int.from_bytes(peb[0x20:0x28],'little')
        raw=read(params,0x88);envptr=int.from_bytes(raw[0x80:0x88],'little')
        # Read aligned UTF-16 chunks until the environment's double NUL, without
        # reading beyond an allocated page or persisting credentials.
        data=b''
        for offset in range(0,2*1024*1024,2):
            data+=read(envptr+offset,2)
            if data.endswith(b'\x00\x00\x00\x00') and len(data)>4:break
        else:raise RuntimeError('Environment exceeds bounded inspection limit')
        lines=data.decode('utf-16-le').rstrip('\0').split('\0');result={}
        for line in lines:
            key,sep,value=line.partition('=')
            if sep and key:result[key]=value
        if not result.get('SystemRoot') and not result.get('SYSTEMROOT'):raise RuntimeError('Invalid environment layout')
        return result
    finally:kernel.CloseHandle(handle)

def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=20) as response:return json.load(response)

def digest_without_flag(raw):
    return hashlib.sha256(b'\n'.join(line for line in raw.splitlines() if not line.strip().startswith(FLAG.encode()+b'='))).hexdigest()

def permission_summary(health):
    return {'execution_enabled':health.get('execution_enabled'),'strategies':health.get('strategies'),
            'source_time_basis':health.get('source_time_basis'),
            'telegram_alerts_enabled':health.get('telegram_alerts',{}).get('enabled'),
            'signal_outcomes_enabled':health.get('signal_outcomes',{}).get('enabled'),
            'telegram_reports_enabled':health.get('telegram_reports',{}).get('enabled'),
            'strategy_bank_enabled':health.get('strategy_bank',{}).get('enabled')}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['inspect','restart']);parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--console-owner',type=int,help='Previously verified dedicated engine launcher PID')
    args=parser.parse_args();OUT.mkdir(exist_ok=True)
    env=read_env(args.pid);before=get('/api/health');env_path=ROOT/'backend/.env';raw=env_path.read_bytes()
    known={k:v for k,v in env.items() if k.startswith(('TRADEDEN_','TRADING_HUB_'))}
    safe={'captured_at':datetime.now(timezone.utc).isoformat(),'pid':args.pid,'health':before,
          'permissions':permission_summary(before),'effective_setting_names':sorted(known),
          'experimental_consumer_enabled':env.get(FLAG)=='1','env_other_lines_sha256':digest_without_flag(raw)}
    (OUT/'before.json').write_text(json.dumps(safe,indent=2),encoding='utf-8')
    print(json.dumps({k:safe[k] for k in ('captured_at','pid','permissions','experimental_consumer_enabled')},indent=2))
    if args.mode=='inspect':return
    if before.get('execution_enabled') is not False:raise RuntimeError('Unexpected execution setting; refusing restart')
    # Persist only the CEO-authorized flag, preserving every other .env byte-line.
    newline=b'\r\n' if b'\r\n' in raw else b'\n'
    lines=raw.splitlines(keepends=True);found=False;updated=[]
    for line in lines:
        if line.strip().startswith(FLAG.encode()+b'='):
            if not found:updated.append(FLAG.encode()+b'=1'+newline);found=True
        else:updated.append(line)
    changed=b''.join(updated)
    if not found:changed+=(b'' if not changed or changed.endswith((b'\r',b'\n')) else newline)+FLAG.encode()+b'=1'+newline
    if digest_without_flag(raw)!=digest_without_flag(changed):raise RuntimeError('Unrelated environment-file change refused')
    env_path.write_bytes(changed)
    next_env=dict(env);next_env[FLAG]='1'
    if any(next_env[k]!=v for k,v in env.items() if k!=FLAG):raise RuntimeError('Production environment drift refused')
    # Windows CTRL_BREAK supports Uvicorn's graceful SIGBREAK handling. It is
    # delivered solely to the verified engine's existing process group.
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.GenerateConsoleCtrlEvent.argtypes=[w.DWORD,w.DWORD]
    if not args.console_owner:raise RuntimeError('Verified dedicated engine console owner required')
    kernel.FreeConsole()
    if not kernel.AttachConsole(args.pid):raise c.WinError(c.get_last_error())
    handler_type=c.WINFUNCTYPE(w.BOOL,w.DWORD)
    handler=handler_type(lambda event:True)
    kernel.SetConsoleCtrlHandler.argtypes=[handler_type,w.BOOL]
    kernel.SetConsoleCtrlHandler(handler,True)
    clients=(w.DWORD*32)();count=kernel.GetConsoleProcessList(clients,32)
    permitted={os.getpid(),args.pid,args.console_owner}
    if count>32 or not count or any(pid not in permitted for pid in clients[:count]):
        kernel.FreeConsole();raise RuntimeError('Console contains unrelated clients; refused console signal')
    graceful=bool(kernel.GenerateConsoleCtrlEvent(1,0))
    deadline=time.monotonic()+35
    while graceful and time.monotonic()<deadline:
        try:
            with socket.create_connection(('127.0.0.1',8000),timeout=.5):pass
        except OSError:break
        time.sleep(.5)
    else:
        if not graceful:raise RuntimeError('Graceful process-group stop unavailable; no force-stop performed. Authorized flag persisted, old engine remains running.')
        raise RuntimeError('Old engine did not stop within grace period; no duplicate process launched')
    kernel.FreeConsole()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');log_path=OUT/('engine-'+stamp+'.log')
    with log_path.open('ab') as log:
        child=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8000'],cwd=ROOT/'backend',env=next_env,
                               stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    deadline=time.monotonic()+90;after=None
    while time.monotonic()<deadline:
        if child.poll() is not None:raise RuntimeError('Updated local engine exited; inspect local log')
        try:
            after=get('/api/health')
            if after.get('status')=='CONNECTED' and after.get('data_freshness',{}).get('market_count',0):break
        except Exception:pass
        time.sleep(1)
    if after is None:raise RuntimeError('No engine health after restart')
    paper=get('/api/quant-labs/live');same=permission_summary(before)==permission_summary(after)
    evidence={'captured_at':datetime.now(timezone.utc).isoformat(),'old_pid':args.pid,'pid':child.pid,'graceful_stop':graceful,
              'production_environment_preserved':True,'only_effective_setting_changed':FLAG,'production_permissions_unchanged':same,
              'other_env_file_lines_unchanged':digest_without_flag(raw)==digest_without_flag(env_path.read_bytes()),
              'health':after,'paper':paper,'engine_log':str(log_path)}
    (OUT/'restart.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps({k:evidence[k] for k in ('pid','graceful_stop','production_environment_preserved','production_permissions_unchanged','other_env_file_lines_unchanged')},indent=2))
    if not same:raise RuntimeError('Production permission mismatch after restart')

if __name__=='__main__':main()
