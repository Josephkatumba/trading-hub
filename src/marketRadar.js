import {engineFetch} from "./engine.js";

const DEMO_MARKETS = [
  {symbol:"XAUUSD",price:3348.2,change_pct:0.42,state:"WATCHING",score:74,setup:"Trendline reversal",reason:"Waiting for rejection + retest.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"BEARISH",structure:"Lower highs + lower lows",stage:"TRENDLINE TEST",insight:"Bearish structure is active. Confirmation is still required.",rsi:44,action:"WAIT",trigger:"Wait for rejection and a confirmed retest before considering the setup."},
  {symbol:"EURUSD",price:1.1742,change_pct:-0.16,state:"WATCHING",score:61,setup:"Trendline reversal",reason:"Resistance is being tested.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"BEARISH",structure:"Lower highs + lower lows",stage:"TRENDLINE TEST",insight:"Bearish structure with momentum alignment.",rsi:46,action:"WAIT",trigger:"Resistance is active, but confirmation is still missing."},
  {symbol:"GBPUSD",price:1.3518,change_pct:0.09,state:"WATCHING",score:54,setup:"Trendline reversal",reason:"Approaching a reaction zone.",session:"New York",market_bias:"RANGE / NEUTRAL",momentum:"NEUTRAL",higher_timeframe_bias:"NEUTRAL",structure:"Mixed / range",stage:"STRUCTURE BIAS",insight:"Mixed structure. Wait for cleaner directional evidence.",rsi:51,action:"WAIT",trigger:"No clean directional sequence yet."}
];

let refreshTimer = null;
let latestMarkets = [];
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const stateClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-");
const biasClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-").replace(/\//g,"-");
const fmt = (n,d=4) => Number(n||0).toLocaleString(undefined,{maximumFractionDigits:d});

function actionClass(action){return String(action||"WAIT").toLowerCase().replace(/\s+/g,"-");}
function actionIcon(action){return String(action||"WAIT").toUpperCase()==="BUY"?"↗":String(action||"WAIT").toUpperCase()==="SELL"?"↘":"•";}

function scoreBars(m){
  const b=m.score_breakdown||{};
  const max={trendline:20,structure:15,support_resistance:15,rejection:15,session:10,volatility:10,momentum:10,higher_timeframe:5};
  return Object.keys(max).map(k=>{
    const label=k.replace(/_/g," ").toUpperCase();
    const value=Number(b[k]||0);
    return '<div class="score-row"><span>'+label+'</span><i><b style="width:'+Math.min(value/max[k]*100,100)+'%"></b></i><strong>'+value+'/'+max[k]+'</strong></div>';
  }).join("");
}

function row(m){
  const bias=m.market_bias||"RANGE / NEUTRAL";
  const move=Number(m.change_pct||0);
  const action=String(m.action||"WAIT").toUpperCase();
  return '<button class="radar-row radar-row-btn" data-symbol="'+esc(m.symbol)+'">'
    +'<div class="radar-symbol"><b>'+esc(m.symbol)+'</b><small>'+esc(m.stage||m.setup||"No setup")+'</small></div>'
    +'<div class="radar-price"><b>'+fmt(m.price)+'</b><small class="'+(move>=0?"up":"down")+'">'+(move>=0?"+":"")+move.toFixed(2)+'% / 24h</small></div>'
    +'<div class="radar-bias"><span class="bias-pill '+biasClass(bias)+'">'+esc(bias)+'</span><small>'+esc(m.momentum||"NEUTRAL")+'</small></div>'
    +'<div><span class="radar-state '+stateClass(m.state)+'">'+esc(m.state)+'</span></div>'
    +'<div class="radar-score"><div class="score-ring"><span>'+Number(m.score||0)+'</span></div></div>'
    +'</button>';
}

function setupMap(m){
  const price=Number(m.price||0);
  const high=Number(m.london_high||price*1.004);
  const low=Number(m.london_low||price*0.996);
  const key=Number(m.nearest_level||price);
  const span=Math.max(Math.abs(high-low),Math.abs(price)*0.002,0.0001);
  const min=Math.min(low,key,price)-span*.45;
  const max=Math.max(high,key,price)+span*.45;
  const y=v=>Math.max(4,Math.min(96,((max-v)/(max-min))*100));
  const pos=v=>y(v).toFixed(1);
  const priceY=pos(price), highY=pos(high), lowY=pos(low), keyY=pos(key);
  const action=String(m.action||"WAIT").toUpperCase();
  const accent=action==="BUY"?"buy":action==="SELL"?"sell":"wait";
  return '<div class="live-price-map">'
    +'<div class="map-header"><div><span class="kicker">SETUP MAP</span><b>Price structure &amp; reaction zones</b></div><span class="map-live"><i class="live-dot"></i>LIVE</span></div>'
    +'<div class="map-canvas">'
    +'<div class="map-grid"><i></i><i></i><i></i><i></i><i></i></div>'
    +'<div class="map-zone london" style="top:'+highY+'%;height:'+Math.max(8,lowY-highY)+'%"><span>LONDON RANGE</span></div>'
    +'<div class="map-line key" style="top:'+keyY+'%"><span>KEY LEVEL · '+fmt(key,4)+'</span></div>'
    +'<div class="map-line price '+accent+'" style="top:'+priceY+'%"><span>LIVE PRICE · '+fmt(price)+'</span></div>'
    +'<div class="map-node high" style="top:'+highY+'%"><span>HIGH</span></div>'
    +'<div class="map-node low" style="top:'+lowY+'%"><span>LOW</span></div>'
    +'<div class="map-axis"><span>'+fmt(max,4)+'</span><span>'+fmt((max+min)/2,4)+'</span><span>'+fmt(min,4)+'</span></div>'
    +'</div>'
    +'<div class="map-footer"><span><i class="dot entry"></i>Price</span><span><i class="dot level"></i>Key level</span><span><i class="dot range"></i>London range</span><span><i class="dot danger"></i>Risk/invalid</span></div>'
    +'</div>';
}

function lifecycle(m){
  const action=String(m.action||"WAIT").toUpperCase();
  const state=String(m.state||"WATCHING").toUpperCase();
  const steps=[
    ["STRUCTURE",["DEVELOPING","CONFIRMING"].includes(state)||action!=="WAIT"],
    ["TRENDLINE",String(m.stage||"").includes("TRENDLINE")],
    ["REACTION",action!=="WAIT" || /reject|retest|confirm/i.test(String(m.reason||""))],
    ["CONFIRM",action!=="WAIT" && state==="CONFIRMING"]
  ];
  return '<div class="setup-lifecycle">'+steps.map((s,i)=>'<div class="'+(s[1]?"done":"")+'"><span class="life-index">0'+(i+1)+'</span><b>'+s[0]+'</b><i></i></div>').join("")+'</div>';
}

function renderDetail(m){
  if(!m) return '<div class="radar-empty"><div class="radar-empty-orb">⌁</div><b>No active setup</b><p>The scanner is waiting for a clean directional sequence. No trade is a valid state.</p></div>';
  const london=(m.london_high!=null&&m.london_low!=null) ? '<div><span>LONDON RANGE</span><b>'+fmt(m.london_low,2)+' — '+fmt(m.london_high,2)+'</b></div>' : "";
  const key=m.nearest_level ? '<div><span>KEY LEVEL</span><b>'+fmt(m.nearest_level,4)+' · '+esc(m.nearest_level_type||"LEVEL")+'</b></div>' : "";
  const action=String(m.action||"WAIT").toUpperCase();
  const risk=m.stop_loss!=null?fmt(m.stop_loss,2):"Not calculated";
  const reward=m.take_profit!=null?fmt(m.take_profit,2):"Not calculated";
  return '<div class="radar-detail">'
    +'<div class="radar-detail-top"><div><span class="kicker">LIVE MARKET INTELLIGENCE · PRIMARY FEED</span><h2>'+esc(m.symbol)+'</h2><p>'+esc(m.stage||"NO SETUP")+' · '+esc(m.session||"Session unknown")+' · '+esc(m.setup||"Trendline reversal")+'</p></div><div class="radar-big-score"><strong>'+Number(m.score||0)+'</strong><small>/100</small></div></div>'
    +'<div class="live-command-head"><div class="live-verdict '+actionClass(action)+'"><span class="action-icon">'+actionIcon(action)+'</span><div><small>ENGINE VERDICT</small><b>'+esc(action)+'</b><em>'+esc(m.state||"WATCHING")+'</em></div></div><div class="live-thesis"><span>ONE-LINE THESIS</span><b>'+esc(m.insight||m.reason||"Waiting for more market structure.")+'</b></div></div>'
    +setupMap(m)
    +'<div class="live-intel-grid"><div class="live-intel-copy"><span class="kicker">AI MARKET READ</span><p>'+esc(m.insight||m.reason||"Waiting for more market structure.")+'</p><div class="ai-action-note"><span>NEXT OBSERVATION</span><b>'+esc(m.trigger||"Wait for a clean setup.")+'</b></div></div><div><span class="kicker">SETUP LIFECYCLE</span>'+lifecycle(m)+'</div></div>'
    +'<div class="radar-level-strip"><div><span>LIVE PRICE</span><b>'+fmt(m.price)+'</b></div><div><span>INVALIDATION / STOP</span><b>'+risk+'</b></div><div><span>TARGET</span><b>'+reward+'</b></div></div>'
    +'<div class="radar-checks"><div><span>BIAS</span><b>'+esc(m.market_bias||"—")+'</b></div><div><span>MOMENTUM</span><b>'+esc(m.momentum||"—")+' · RSI '+(m.rsi!=null?Number(m.rsi).toFixed(0):"—")+'</b></div><div><span>H1 BIAS</span><b>'+esc(m.higher_timeframe_bias||"—")+'</b></div><div><span>STRUCTURE</span><b>'+esc(m.structure||"—")+'</b></div><div><span>SPREAD</span><b>'+fmt(m.spread,3)+'</b></div>'+london+key+'</div>'
    +'<div class="radar-reason"><span>WHY THE ENGINE SAYS THIS</span><p>'+esc(m.reason||"No clean sequence detected.")+'</p></div>'
    +'<div class="score-breakdown"><div class="kicker">CONFLUENCE MODEL</div>'+scoreBars(m)+'</div>'
    +'<div class="radar-warning"><b>DISCIPLINE GATE</b><span>Potential setup only. Trading Hub observes and explains. Your confirmation rules remain the final gate before execution.</span></div>'
    +'</div>';
}
