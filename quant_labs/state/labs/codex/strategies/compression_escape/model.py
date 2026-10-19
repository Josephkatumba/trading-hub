"""Codex-authored executable experimental model; no demonstrated edge.

Calculates a closed-M15 channel escape with H1 persistence, structural stops and
3R/4R paper objectives. Uses only the supplied read-only market snapshot.
"""
import math

def ema(values,period):
    value=values[0]
    for x in values[1:]:value=value+2.0/(period+1)*(x-value)
    return value

def detect(snapshot):
    frames=snapshot['frames'];bars=frames.get('M15',());higher=frames.get('H1',())
    if len(bars)<80 or len(higher)<50:return []
    recent=bars[-16:];ranges=[]
    for i in range(1,len(recent)):
        b=recent[i];previous=recent[i-1]['close']
        ranges.append(max(b['high']-b['low'],abs(b['high']-previous),abs(b['low']-previous)))
    atr=sum(ranges)/len(ranges)
    if atr<=0:return []
    last=bars[-1];prior=bars[-25:-1];hi=max(b['high'] for b in prior);lo=min(b['low'] for b in prior)
    if hi-lo>5*atr:return []
    candle_range=last['high']-last['low']
    if candle_range<=0 or abs(last['close']-last['open'])<0.5*candle_range:return []
    closes=[b['close'] for b in higher[-40:]]
    path=sum(abs(closes[i]-closes[i-1]) for i in range(1,len(closes)))
    efficiency=abs(closes[-1]-closes[0])/path if path else 0
    if efficiency<0.15:return []
    baseline=ema(closes,20);direction=None
    if last['close']>hi+0.1*atr and last['close']>last['open'] and closes[-1]>baseline:direction='LONG'
    if last['close']<lo-0.1*atr and last['close']<last['open'] and closes[-1]<baseline:direction='SHORT'
    if direction is None:return []
    long=direction=='LONG';quote=snapshot['quote'];entry=quote['ask'] if long else quote['bid']
    stop=(min(b['low'] for b in bars[-8:])-0.25*atr) if long else (max(b['high'] for b in bars[-8:])+0.25*atr)
    risk=entry-stop if long else stop-entry
    if not 0.5*atr<=risk<=3*atr:return []
    target_r=4 if efficiency>=0.5 else 3
    target=entry+target_r*risk if long else entry-target_r*risk
    return [{'direction':direction,'stop_loss':stop,'take_profit':target,'horizon_seconds':43200,'atr':atr,
             'rationale':'Closed M15 channel escape with H1 directional persistence and a buffered structural stop; experimental paper model.'}]
