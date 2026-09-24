// Risk = money lost if the planned stop is hit:
//   |entry - initial stop| x volume x contract value per point (+ commission/swap).
// MT5 deal/position CSV exports carry entry, exit, volume and profit but not the
// stop loss at entry, so imported trades have risk 0/missing. That means
// UNAVAILABLE, not zero risk: these helpers never estimate it, and R multiples
// are only used when backed by recorded risk (or supplied explicitly as non-zero).
export const hasRecordedRisk=t=>Number(t?.risk)>0;
export function hasRecordedR(t){
  if(t?.r==null||t.r==="")return false;
  const r=Number(t.r);
  return Number.isFinite(r)&&(r!==0||hasRecordedRisk(t));
}
export function averageR(trades){
  const rs=trades.filter(hasRecordedR).map(t=>Number(t.r));
  return {value:rs.length?rs.reduce((s,x)=>s+x,0)/rs.length:null,count:rs.length,total:trades.length};
}
export const formatR=v=>v==null?"Unavailable":(v>=0?"+":"")+Number(v).toFixed(2)+"R";
