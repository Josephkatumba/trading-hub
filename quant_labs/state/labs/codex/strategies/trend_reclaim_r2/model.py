"""Codex independent research: persistent H1 trend, closed M15 pullback reclaim.
No verified edge. TARGET_NET_R is a declared exit variant, never a fitted win rate.
"""
TARGET_NET_R = 2

def ema(values,period):
    value=values[0]
    for item in values[1:]:value+=2.0/(period+1)*(item-value)
    return value

def atr(bars):
    recent=bars[-16:]
    return sum(max(recent[i]['high']-recent[i]['low'],abs(recent[i]['high']-recent[i-1]['close']),abs(recent[i]['low']-recent[i-1]['close'])) for i in range(1,len(recent)))/15

def detect(snapshot):
    frames=snapshot['frames'];bars=frames.get('M15',());higher=frames.get('H1',())
    if len(bars)<80 or len(higher)<64:return []
    a=atr(bars);ha=atr(higher)
    if min(a,ha)<=0:return []
    hc=[b['close'] for b in higher[-64:]];path=sum(abs(hc[i]-hc[i-1]) for i in range(1,len(hc)))
    efficiency=abs(hc[-1]-hc[0])/path if path else 0
    if efficiency<0.30:return []
    fast=ema(hc,20);slow=ema(hc,50);slope=fast-ema(hc[:-3],20)
    closes=[b['close'] for b in bars[-41:-1]];baseline=ema(closes,20);last=bars[-1];previous=bars[-2]
    width=last['high']-last['low']
    if width<=0 or width>2.5*a or abs(last['close']-last['open'])<0.45*width:return []
    direction=None
    if hc[-1]>fast>slow and slope>0.15*ha and previous['close']<=baseline and last['close']>baseline+0.1*a and last['close']>last['open']:direction='LONG'
    if hc[-1]<fast<slow and slope<-0.15*ha and previous['close']>=baseline and last['close']<baseline-0.1*a and last['close']<last['open']:direction='SHORT'
    if direction is None:return []
    long=direction=='LONG';sign=1 if long else -1;quote=snapshot['quote'];meta=snapshot['metadata']
    entry=quote['ask'] if long else quote['bid']
    stop=min(b['low'] for b in bars[-6:])-0.2*a if long else max(b['high'] for b in bars[-6:])+0.2*a
    risk=sign*(entry-stop)
    if not 0.5*a<=risk<=3*a:return []
    commission=meta.get('commission_price');tick=meta.get('tick_size')
    if commission is None or tick is None or tick<=0:return []
    reserve=commission+0.75*(quote['ask']-quote['bid'])
    target=entry+sign*(TARGET_NET_R*(risk+reserve)+reserve+2*tick)
    horizons={2:21600,3:28800,4:43200,5:64800,7:86400,9:129600}
    return [{'direction':direction,'stop_loss':stop,'take_profit':target,'horizon_seconds':horizons[TARGET_NET_R],'atr':a,
             'rationale':'H1 persistence with a closed M15 EMA pullback reclaim, structural invalidation and a declared cost-buffered net-R exit variant; experimental.'}]
