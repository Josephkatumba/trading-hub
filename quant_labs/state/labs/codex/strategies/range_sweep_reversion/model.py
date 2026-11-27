"""Codex independent research: failed channel escape in a low-persistence H1 regime."""
def atr(bars):
    recent=bars[-16:]
    return sum(max(recent[i]['high']-recent[i]['low'],abs(recent[i]['high']-recent[i-1]['close']),abs(recent[i]['low']-recent[i-1]['close'])) for i in range(1,len(recent)))/15

def detect(snapshot):
    frames=snapshot['frames'];bars=frames.get('M15',());higher=frames.get('H1',())
    if len(bars)<80 or len(higher)<64:return []
    a=atr(bars);ha=atr(higher)
    if min(a,ha)<=0:return []
    hc=[b['close'] for b in higher[-40:]];path=sum(abs(hc[i]-hc[i-1]) for i in range(1,len(hc)))
    efficiency=abs(hc[-1]-hc[0])/path if path else 0
    if efficiency>0.30 or abs(hc[-1]-hc[0])>1.2*ha:return []
    prior=bars[-33:-1];hi=max(b['high'] for b in prior);lo=min(b['low'] for b in prior)
    if not 3*a<=hi-lo<=10*a:return []
    last=bars[-1];width=last['high']-last['low']
    if width<=0 or abs(last['close']-last['open'])<0.4*width:return []
    direction=None
    if last['low']<lo-0.05*a and last['close']>lo+0.1*a and last['close']>last['open']:direction='LONG'
    if last['high']>hi+0.05*a and last['close']<hi-0.1*a and last['close']<last['open']:direction='SHORT'
    if direction is None:return []
    long=direction=='LONG';sign=1 if long else -1;quote=snapshot['quote'];meta=snapshot['metadata']
    entry=quote['ask'] if long else quote['bid'];stop=last['low']-0.15*a if long else last['high']+0.15*a
    risk=sign*(entry-stop)
    if not 0.5*a<=risk<=3*a:return []
    target=min(hi-0.15*a,entry+9*risk) if long else max(lo+0.15*a,entry-9*risk)
    commission=meta.get('commission_price')
    if commission is None:return []
    reserve=commission+0.75*(quote['ask']-quote['bid'])
    if (sign*(target-entry)-reserve)/(risk+reserve)<2:return []
    return [{'direction':direction,'stop_loss':stop,'take_profit':target,'horizon_seconds':43200,'atr':a,
             'rationale':'Failed M15 range escape with H1 low persistence; objective is the opposite observed range boundary, capped at 9R; experimental.'}]
