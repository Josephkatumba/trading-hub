"""Deterministic SYNTHETIC market data for integration proof, never performance evidence."""
from datetime import datetime,timezone
from .adapter import from_collector

ASOF=1792396800.0

def normalizer(epoch,basis):
    if basis!='UTC':return {'normalization_status':'UNVERIFIED'}
    return {'normalization_status':'VERIFIED','normalized_utc':datetime.fromtimestamp(epoch,timezone.utc).isoformat()}

def raw_fixture(asof=ASOF):
    frames={}
    for tf,seconds,count in [('M15',900,300),('H1',3600,160),('M1',60,120)]:
        end=asof-asof%seconds
        rows=[]
        for i in range(count):
            close=100 if tf!='H1' else 90+i*.05
            rows.append({'time':end-(count-i)*seconds,'open':close-.01,'high':close+.1,'low':close-.1,'close':close,'spread_points':1,'tick_volume':100})
        if tf=='M15':rows[-1].update(open=100,high=100.45,low=99.98,close=100.4)
        frames[tf]=rows
    return frames,{'bid':100.4,'ask':100.41,'raw_tick_at':asof,'received_at':asof}, {'point':.01,'tick_size':.01,'tradable_long':True,'tradable_short':True,'commission_price':.00007,'swap_mode':0,'cost_basis':'SYNTHETIC TEST ONLY'}

def snapshot(asof=ASOF):
    frames,quote,meta=raw_fixture(asof)
    return from_collector('EURUSD','EURUSD.TEST',frames,quote,meta,'UTC',normalizer)

def future_bar(signal,kind='TP'):
    p=signal['entry'];stop=signal['stop_loss'];tp=signal['take_profit']
    return {'utc':signal['entry_at'],'open':p,'high':tp+.1 if kind in ('TP','BOTH') else p+.1,
            'low':stop-.1 if kind in ('SL','BOTH') else p-.1,'close':p,'spread':.01}
