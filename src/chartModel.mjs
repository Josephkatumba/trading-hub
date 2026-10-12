export const TV_SYMBOLS = Object.freeze({XAUUSD:"OANDA:XAUUSD",XAGUSD:"OANDA:XAGUSD",EURUSD:"FX:EURUSD",GBPUSD:"FX:GBPUSD",USDJPY:"FX:USDJPY",GBPJPY:"FX:GBPJPY",AUDUSD:"FX:AUDUSD",NZDUSD:"FX:NZDUSD",USDCAD:"FX:USDCAD",USDCHF:"FX:USDCHF",EURJPY:"FX:EURJPY",NAS100:"OANDA:NAS100USD",US500:"OANDA:SPX500USD",GER40:"CAPITALCOM:GER40",BTCUSD:"BITSTAMP:BTCUSD",ETHUSD:"BITSTAMP:ETHUSD"});
export const INTERVALS = Object.freeze({M5:"5",M15:"15",H1:"60",H4:"240",D1:"D"});
export function widgetConfig(symbol,timeframe){
  if(!TV_SYMBOLS[symbol]||!INTERVALS[timeframe])throw new Error("Unsupported chart selection");
  return {autosize:true,symbol:TV_SYMBOLS[symbol],interval:INTERVALS[timeframe],timezone:"Etc/UTC",theme:"dark",style:"1",locale:"en",allow_symbol_change:false,calendar:false,support_host:"https://www.tradingview.com"};
}
export function candlesForChart(rows=[]){
  const unique=new Map();
  for(const r of rows){
    if([r.time,r.open,r.high,r.low,r.close].every(Number.isFinite)&&r.high>=Math.max(r.open,r.close)&&r.low<=Math.min(r.open,r.close)&&r.high>=r.low)
      unique.set(r.time,{time:r.time,open:r.open,high:r.high,low:r.low,close:r.close});
  }
  return [...unique.values()].sort((a,b)=>a.time-b.time);
}
export function chartMarkers(candles,episodes=[],outcomes=[]){
  if(!candles.length)return [];
  const first=candles[0].time,last=candles.at(-1).time;
  const markers=[];
  function add(stamp,text,long,color){
    const epoch=Date.parse(stamp)/1000;
    if(!Number.isFinite(epoch)||epoch<first||epoch>last)return;
    let lo=0,hi=candles.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(candles[mid].time<=epoch)lo=mid+1;else hi=mid;}
    markers.push({time:candles[Math.max(0,lo-1)].time,position:long?"belowBar":"aboveBar",shape:long?"arrowUp":"arrowDown",color,text});
  }
  for(const e of episodes)add(e.confirmation_time||e.observed_at,`${e.strategy_id||"Trendline"} · ${e.confirmation?"confirmed":"observation"}`,e.direction==="LONG","#78dba9");
  const seen=new Set();
  for(const o of outcomes){
    const key=[o.setup_id,o.observation_id,o.horizon,o.label_definition].join("|");
    if(seen.has(key))continue;seen.add(key);
    // resolved_at is generation time, not the historical barrier-hit time.
    const stamp=o.first_hit_time||o.target_hit_at||o.invalidation_hit_at||o.horizon_end;
    if(o.outcome_status==="DUPLICATE_OUTCOME_CONFLICT")continue;
    add(stamp,`${o.timestamp_quality==="VERIFIED"?"Hypothetical":"Unverified hypothetical"} ${o.label||"pending"} · ${o.horizon} horizon`,o.direction==="LONG",o.label==="WIN"?"#62c9a1":"#eba17b");
  }
  return markers.sort((a,b)=>a.time-b.time);
}
export function planLines(episode){
  if(!episode)return [];
  const plan=episode.confirmed_plan;
  const values=plan?{entry:plan.entry,stop_loss:plan.stop_loss,take_profit:plan.take_profit}:
    {entry:episode.proposed_entry??episode.entry,stop_loss:episode.proposed_stop_loss??episode.stop_loss,take_profit:episode.proposed_take_profit??episode.take_profit};
  return [["entry","Entry","#71b9ed"],["stop_loss","Stop","#e98683"],["take_profit","Target","#78dba9"]]
    .filter(([key])=>Number.isFinite(values[key])).map(([key,title,color])=>({price:values[key],color,lineWidth:2,lineStyle:2,axisLabelVisible:true,title:plan?`Confirmed ${title}`:`Observation ${title}`}));
}
