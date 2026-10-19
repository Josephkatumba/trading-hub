"""Five predeclared hypotheses; fixed parameters, causal H1 features, no optimizer."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import math
import numpy as np

@dataclass(frozen=True)
class Spec:
    key:str
    family:str
    idea:str
    entry_rule:str
    stop_rule:str
    target_rule:str
    horizon_hours:int
    intended_regime:str
    limitations:str
    version:str='1.0.0'
    risk_model:str='one planned-risk unit; one open position per strategy/instrument; no compounding'

SPECS=[
    Spec('drift48','persistent drift','A coherent two-day directional move may persist beyond trading costs.',
         'H1 at 00/06/12/18 UTC: 48-return log drift / sqrt(sum squared returns) >= 1.5 in magnitude; efficiency >= .25; enter next H1 open.',
         '2 prior H1 ATR(24) from executable entry.','1.5R fixed.',24,'TREND','Intraday hypothesis inspired by momentum, not a replication of monthly futures literature.'),
    Spec('robust_revert','robust statistical reversion','Extreme deviation from the rolling median may revert when its first reversal starts.',
         'Previous H1 close >2.5 scaled MAD(48) from prior median; current H1 moves toward median; same signed deviation; enter next open.',
         '1.5 prior H1 ATR(24).','Frozen median of 48 closes before trigger; >=1R executable reward.',12,'RANGE','Median is not intrinsic value; persistent trends can defeat reversion.'),
    Spec('compression_release','compression expansion','A first range escape after narrow trading may persist.',
         'Prior 12 H1 high-low range <=2.5 prior ATR(24); first close beyond it by .1 ATR; enter next open.',
         '1.5 prior H1 ATR(24).','2R fixed.',12,'VOLATILE','Few compressions may meet fixed rule; no thresholds retuned to increase count.'),
    Spec('shock_fade','transient shock reversal','A large directional shock followed by a reversal may reflect temporary dislocation.',
         'Prior H1 range >2.5 prior ATR(24), body >=70% range; current close crosses shock midpoint in opposite direction; enter next open.',
         'Beyond shock extreme by .2 prior ATR(24).','Shock open; >=1.2R executable reward.',6,'RANGE','No news feed; shocks can be permanent information, not temporary liquidity.'),
    Spec('relative_lag','cross-market residual reversal','BTC/ETH relative return shocks may mean-revert conditionally.',
         'BTC/ETH only: rolling prior 48 H1 returns OLS beta; current residual >2.5 prior residual SD; fade residual next H1 open.',
         '1.5 prior H1 ATR(24).','1.5R fixed.',6,'ANY','Unhedged single-leg residual signal; not market-neutral arbitrage. Both CFDs share crypto risk.')
]

def rolling(x,n,kind):
    out=np.full(len(x),np.nan)
    if len(x)<n:return out
    w=np.lib.stride_tricks.sliding_window_view(x,n)
    if kind=='mean': v=w.mean(axis=1)
    elif kind=='max':v=w.max(axis=1)
    elif kind=='min':v=w.min(axis=1)
    elif kind=='median':v=np.median(w,axis=1)
    elif kind=='mad':v=np.median(abs(w-np.median(w,axis=1)[:,None]),axis=1)*1.4826
    out[n-1:]=v
    return out

class Features:
    def __init__(self,bars):
        self.bars=bars
        for k in ('utc','open','high','low','close'): setattr(self,k,np.array([b[k] for b in bars],dtype=float))
        self.ret=np.r_[np.nan,np.diff(np.log(self.close))]
        prev=np.r_[self.close[0],self.close[:-1]]
        self.tr=np.maximum(self.high-self.low,np.maximum(abs(self.high-prev),abs(self.low-prev)))
        self.atr=rolling(self.tr,24,'mean')
        self.med=rolling(self.close,48,'median'); self.mad=rolling(self.close,48,'mad')
        self.vol=rolling(self.ret**2,24,'mean')**.5
        self.longvol=rolling(self.ret**2,120,'mean')**.5
        self.range_hi=rolling(self.high,12,'max');self.range_lo=rolling(self.low,12,'min')
        self.path=rolling(abs(self.ret),48,'mean')*48
        self.squares=rolling(self.ret**2,48,'mean')*48
    def regime(self,i):
        if self.longvol[i]>0 and self.vol[i]/self.longvol[i]>1.5:return 'VOLATILE'
        efficiency=abs(math.log(self.close[i]/self.close[i-48]))/self.path[i] if self.path[i]>0 else 0
        return 'TREND' if efficiency>=.3 else 'RANGE'
    def decide(self,key,i,other=None):
        # The slow lookbacks count observed closed H1 bars; never invent weekend bars.
        # A recent gap veto prevents entries immediately after an unverified outage.
        if i<121 or self.utc[i]-self.utc[i-12]!=12*3600: return None
        a=self.atr[i-1]
        if not math.isfinite(a) or a<=0:return None
        c=self.close; direction=None; stop_distance=target_r=target=stop=None
        if key=='drift48':
            if (int(self.utc[i]+3600)//3600)%24 not in (0,6,12,18):return None
            move=math.log(c[i]/c[i-48]); noise=math.sqrt(self.squares[i]); efficiency=abs(move)/self.path[i] if self.path[i]>0 else 0
            if noise<=0 or abs(move)/noise<1.5 or efficiency<.25:return None
            direction='LONG' if move>0 else 'SHORT';stop_distance=2*a;target_r=1.5
        elif key=='robust_revert':
            med=self.med[i-1];mad=self.mad[i-1]
            if not mad>0 or abs(c[i-1]-med)<2.5*mad:return None
            if c[i-1]>med and med<c[i]<c[i-1]:direction='SHORT'
            if c[i-1]<med and med>c[i]>c[i-1]:direction='LONG'
            stop_distance=1.5*a;target=med
        elif key=='compression_release':
            hi,lo=self.range_hi[i-1],self.range_lo[i-1]
            if hi-lo>2.5*a:return None
            if c[i]>hi+.1*a:direction='LONG'
            if c[i]<lo-.1*a:direction='SHORT'
            stop_distance=1.5*a;target_r=2
        elif key=='shock_fade':
            hi,lo=self.high[i-1],self.low[i-1];op=self.open[i-1];prior_atr=self.atr[i-2]
            if hi-lo<=2.5*prior_atr or abs(c[i-1]-op)<.7*(hi-lo):return None
            if c[i-1]>op and c[i]<(hi+lo)/2:direction='SHORT';stop=hi+.2*a
            if c[i-1]<op and c[i]>(hi+lo)/2:direction='LONG';stop=lo-.2*a
            target=op
        elif key=='relative_lag':
            if other is None:return None
            j=np.searchsorted(other.utc,self.utc[i])
            if j>=len(other.utc) or other.utc[j]!=self.utc[i] or j<49:return None
            if not np.array_equal(self.utc[i-49:i+1],other.utc[j-49:j+1]):return None
            x=other.ret[j-48:j];y=self.ret[i-48:i]
            var=np.var(x)
            if var<=0:return None
            beta=np.mean((x-x.mean())*(y-y.mean()))/var
            residual=y-beta*x;std=np.std(residual,ddof=1)
            z=(self.ret[i]-beta*other.ret[j]-residual.mean())/std if std>0 else 0
            if abs(z)<2.5:return None
            direction='SHORT' if z>0 else 'LONG';stop_distance=1.5*a;target_r=1.5
        if direction is None:return None
        return {'direction':direction,'stop_distance':stop_distance,'stop':stop,'target':target,'target_r':target_r,'regime':self.regime(i),'atr':a}
