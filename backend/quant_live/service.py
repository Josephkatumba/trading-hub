"""Nonblocking handoff from the one existing scanner; no MT5 initialization here."""
from collections import OrderedDict
from datetime import datetime,timezone,timedelta
import json
import logging
import os
from pathlib import Path
import threading
import time
from .adapter import from_collector,TF_SECONDS
from .execution import validate_bars
from .runtime import Runtime,register_codex
from .store import Store

LOGGER=logging.getLogger('trading_hub.quant_live')
ENABLED_ENV='TRADEDEN_QUANT_LIVE_ENABLED'
_runtime=None;_thread=None;_lock=threading.Lock();_start_lock=threading.Lock();_pending=OrderedDict();_last={'running':False,'last_processed':None,'last_error':None,'overwritten_snapshots':0}
_inputs={}

def observe_input(data,result):
    """Bounded owner diagnostics of the actual collector handoff, never fabricated input."""
    frames={tf:{'closed_count':len(rows),'last_closed_bar':rows[-1] if rows else None,
                'last_close_at':rows[-1]['utc']+TF_SECONDS[tf] if rows else None}
            for tf,rows in data['frames'].items()}
    failed=[r['status'] for r in result.get('runs',[]) if r['status']!='COMPLETE']
    with _lock:
        prior=_inputs.get(data['symbol'],{})
        runs=result.get('runs',[])
        _inputs[data['symbol']]={'source':data['source'],'broker_symbol':data['broker_symbol'],'asof':data['asof'],
            'source_basis':data['source_basis'],'time_verified':data['time_verified'],'input_sha256':data['input_sha256'],
            'quote':data['quote'],'metadata':data['metadata'],'frames':frames,'data_quality':data['data_quality'],
            'processed_count':prior.get('processed_count',0)+1,'cycle_status':result['status'],
            'last_model_runs':runs or prior.get('last_model_runs',[]),
            'last_model_run_at':data['asof'] if runs else prior.get('last_model_run_at'),
            'generated_signal_count':prior.get('generated_signal_count',0)+len(result.get('signals',[]))}
        while len(_inputs)>32:del _inputs[next(iter(_inputs))]
        _last.update(last_processed=time.time(),last_error=('MODEL_WORKER_'+failed[0]) if failed else None)
def enabled():return os.getenv(ENABLED_ENV,'').strip()=='1'
def store():
    from storage_config import data_directory
    return Store(data_directory()/'quant_live')
def requirements():
    if not enabled():return {}
    plan={'M1':120,'M15':300,'H1':160}
    for model in store().models():
        if not model['scan_enabled'] or model['status']!='EXPERIMENTAL':continue
        for tf,count in model['manifest'].get('requirements',{}).items():
            if tf in ('M1','M5','M15','H1','H4','D1') and isinstance(count,int) and 1<=count<=12000:
                # +1: the newest fetched candle is still forming and is discarded, so N closed candles need N+1.
                plan[tf]=max(plan.get(tf,0),min(count+1,12000))
    return plan
def offer(symbol,broker,frames,quote,metadata,basis,normalize):
    if not enabled():return
    # Copy plain values only. No terminal, account, client or order capability crosses the interface.
    payload=(symbol,broker,{tf:[dict(b) for b in rows] for tf,rows in frames.items()},dict(quote),dict(metadata),basis,normalize)
    with _lock:
        if symbol in _pending:_last['overwritten_snapshots']+=1
        _pending[symbol]=payload
        while len(_pending)>32:_pending.popitem(last=False)
def start(stop,history_fetch=None):
    with _start_lock:return _start(stop,history_fetch)

def _start(stop,history_fetch=None):
    global _thread,_runtime
    if not enabled():return None
    if _thread and _thread.is_alive():return _thread
    registry=store();register_codex(registry);registry.recover();_runtime=Runtime(registry)
    def loop():
        _last['running']=True;last_backfill=0;backfill_cursor=None
        try:
            while not stop.is_set():
                with _lock:payload=_pending.popitem(last=False)[1] if _pending else None
                if payload:
                    try:
                        data=from_collector(*payload);result=_runtime.process(data);observe_input(data,result)
                    except Exception as exc:LOGGER.exception('Experimental provider failed');_last['last_error']=type(exc).__name__
                # Bounded history recovery uses the engine's existing locked read callback.
                if history_fetch and time.time()-last_backfill>=300:
                    now=time.time()
                    try:
                        for s in registry.pending(after=backfill_cursor,limit=1):
                            backfill_cursor=(s['entry_at'],s['signal_id'])
                            end=datetime.fromtimestamp(min(now,s['deadline']),timezone.utc);begin=datetime.fromtimestamp(s['entry_at'],timezone.utc)
                            frames={}
                            for tf,seconds in [('M15',900),('M1',60)]:
                                rows=history_fetch(s['broker_symbol'],tf,begin-timedelta(seconds=seconds),end)
                                if rows is not None:frames[tf]=validate_bars(rows,seconds,now)[0][:12000]
                            registry.add_candles({'symbol':s['symbol'],'frames':frames,'asof':now})
                            _runtime.resolve(s['symbol'],now);break
                    except Exception as exc:
                        LOGGER.exception('Experimental outcome history unavailable');_last['last_error']=type(exc).__name__
                    last_backfill=now
                stop.wait(.1 if payload else .5)
        finally:_last['running']=False
    _thread=threading.Thread(target=loop,name='tradeden-quant-model-consumer',daemon=True);_thread.start();return _thread
def status():
    from .telegram import delivery_enabled
    approved=bool(store().delivery_approval()) if enabled() else False
    with _lock:return {'enabled':enabled(),'telegram_mode':'EXPERIMENTAL_APPROVED' if approved and delivery_enabled() else 'DRY_RUN',
                       'outbound_activation_approved':approved,'delivery_flag':delivery_enabled(),**_last,'latest_inputs':dict(_inputs)}
