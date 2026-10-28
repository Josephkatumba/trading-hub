// Presentation only: never changes source records or qualification.
export const FRAME_SECONDS={M5:300,M15:900,H1:3600,H4:14400,D1:86400};
export function candleTime(candles,stamp,timeframe){
  if(typeof stamp!=="string"||!/(Z|[+-]\d\d:\d\d)$/.test(stamp))return null;
  const epoch=Date.parse(stamp)/1000;
  let lo=0,hi=candles.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(candles[mid].time<=epoch)lo=mid+1;else hi=mid;}
  const bar=candles[lo-1];
  // Do not snap weekend gaps or out-of-window events onto unrelated candles.
  return bar&&epoch<bar.time+FRAME_SECONDS[timeframe]?bar.time:null;
}
export function qualifiedSignals(rows,symbol,timeframe){
  return rows.filter(r=>r.symbol===symbol&&r.timeframe===timeframe&&r.mode==="LIVE"&&r.trade_qualified===true);
}
export function researchEvents(episodes=[],outcomes=[]){
  const byId=new Map(episodes.map(e=>[e.setup_id,e]));
  const events=[];
  for(const e of episodes){
    events.push({...e,kind:"Observation",stamp:e.observed_at});
    if(e.confirmation_time)events.push({...e,kind:"Confirmation",stamp:e.confirmation_time});
    if(e.lifecycle_state==="EXPIRED")events.push({...e,kind:"Expired",stamp:e.closed_event?.occurred_at});
  }
  for(const o of outcomes){
    if(o.outcome_status==="DUPLICATE_OUTCOME_CONFLICT")continue;
    events.push({...o,strategy_id:o.strategy_id||byId.get(o.setup_id)?.strategy_id,
      kind:"Hypothetical outcome",stamp:o.observed_at});
  }
  return events;
}
export function researchGroups(candles,events,filters={}){
  const groups=new Map();let omitted=0;
  for(const e of events){
    if(filters.strategy&&e.strategy_id!==filters.strategy||filters.kind&&e.kind!==filters.kind||
       filters.horizon&&e.horizon!==filters.horizon||filters.outcome&&e.label!==filters.outcome)continue;
    const day=String(e.stamp||"").slice(0,10);
    if(filters.from&&day<filters.from||filters.to&&day>filters.to)continue;
    const time=candleTime(candles,e.stamp,filters.timeframe);
    if(time===null){omitted++;continue;}
    if(!groups.has(time))groups.set(time,[]);
    groups.get(time).push(e);
  }
  const all=[...groups].sort((a,b)=>a[0]-b[0]);
  const shown=all.slice(-Math.min(200,Math.max(1,Number(filters.limit)||20)));
  return {groups:shown,total:all.length,omitted,markers:shown.map(([time,rows])=>({id:String(time),time,
    position:"aboveBar",shape:"circle",color:"#b9b2db",text:rows.length>1?String(rows.length):"R"}))};
}
