import {engineFetch} from "./engine.js";

const DEMO_MARKETS = [
  {symbol:"XAUUSD",price:3348.2,change_pct:0.42,state:"WATCHING",score:74,setup:"Trendline reversal",reason:"Waiting for rejection + retest.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"BEARISH",structure:"Lower highs + lower lows",stage:"TRENDLINE TEST",insight:"Bearish structure is active. Confirmation is still required.",rsi:44},
  {symbol:"EURUSD",price:1.1742,change_pct:-0.16,state:"WATCHING",score:61,setup:"Trendline reversal",reason:"Resistance is being tested.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"BEARISH",structure:"Lower highs + lower lows",stage:"TRENDLINE TEST",insight:"Bearish structure with momentum alignment.",rsi:46},
  {symbol:"GBPUSD",price:1.3518,change_pct:0.09,state:"WATCHING",score:54,setup:"Trendline reversal",reason:"Approaching a reaction zone.",session:"New York",market_bias:"RANGE / NEUTRAL",momentum:"NEUTRAL",higher_timeframe_bias:"NEUTRAL",structure:"Mixed / range",stage:"STRUCTURE BIAS",insight:"Mixed structure. Wait for cleaner directional evidence.",rsi:51}
];

let refreshTimer = null;
let latestMarkets = [];
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const stateClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-");
const biasClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-").replace(/\//g,"-");
const fmt = (n,d=4) => Number(n||0).toLocaleString(undefined,{maximumFractionDigits:d});

function row(m){
  const bias=m.market_bias||"RANGE / NEUTRAL";
  const move=Number(m.change_pct||0);
  return '<button class="radar-row radar-row-btn" data-symbol="'+esc(m.symbol)+'">'
    +'<div class="radar-symbol"><b>'+esc(m.symbol)+'</b><small>'+esc(m.stage||m.setup||"No setup")+'</small></div>'
    +'<div class="radar-price"><b>'+fmt(m.price)+'</b><small class="'+(move>=0?"up":"down")+'">'+(move>=0?"+":"")+move.toFixed(2)+'% / 24h</small></div>'
    +'<div class="radar-bias"><span class="bias-pill '+biasClass(bias)+'">'+esc(bias)+'</span><small>'+esc(m.momentum||"NEUTRAL")+'</small></div>'
    +'<div><span class="radar-state '+stateClass(m.state)+'">'+esc(m.state)+'</span></div>'
    +'<div class="radar-score"><div class="score-ring"><span>'+Number(m.score||0)+'</span></div></div>'
    +'</button>';
}

function scoreBars(m){
  const b=m.score_breakdown||{};
  const max={trendline:20,structure:15,support_resistance:15,rejection:15,session:10,volatility:10,momentum:10,higher_timeframe:5};
  return Object.keys(max).map(k=>{
    const label=k.replace(/_/g," ").toUpperCase();
    const value=Number(b[k]||0);
    return '<div class="score-row"><span>'+label+'</span><i><b style="width:'+Math.min(value/max[k]*100,100)+'%"></b></i><strong>'+value+'/'+max[k]+'</strong></div>';
  }).join("");
}

function renderDetail(m){
  if(!m) return '<div class="radar-empty"><b>No active setup</b><p>The scanner is waiting for a clean directional sequence. That is a valid market state.</p></div>';
  const london=(m.london_high&&m.london_low)
    ? '<div><span>LONDON RANGE</span><b>'+fmt(m.london_low,2)+' — '+fmt(m.london_high,2)+'</b></div>'
    : "";
  const key=m.nearest_level
    ? '<div><span>KEY LEVEL</span><b>'+fmt(m.nearest_level,4)+' · '+esc(m.nearest_level_type||"LEVEL")+'</b></div>'
    : "";
  return '<div class="radar-detail">'
    +'<div class="radar-detail-top"><div><span class="kicker">MARKET INTELLIGENCE</span><h2>'+esc(m.symbol)+'</h2><p>'+esc(m.stage||"NO SETUP")+' · '+esc(m.session||"Session unknown")+'</p></div><div class="radar-big-score">'+Number(m.score||0)+'<small>/100</small></div></div>'
    +'<div class="radar-action-card '+String(m.action||"WAIT").toLowerCase().replace(/\s+/g,"-")+'"><span>SCANNER DIRECTION</span><b>'+esc(m.action||"WAIT")+'</b><small>'+esc(m.trigger||"Wait for a clean setup.")+'</small></div><div class="radar-insight-card"><span>WHAT THE ENGINE SEES</span><p>'+esc(m.insight||m.reason||"Waiting for more market structure.")+'</p></div>'
    +'<div class="radar-checks"><div><span>BIAS</span><b>'+esc(m.market_bias||"—")+'</b></div><div><span>MOMENTUM</span><b>'+esc(m.momentum||"—")+' · RSI '+(m.rsi!=null?Number(m.rsi).toFixed(0):"—")+'</b></div><div><span>H1 BIAS</span><b>'+esc(m.higher_timeframe_bias||"—")+'</b></div><div><span>STRUCTURE</span><b>'+esc(m.structure||"—")+'</b></div><div><span>PRICE</span><b>'+fmt(m.price)+'</b></div><div><span>SPREAD</span><b>'+fmt(m.spread,3)+'</b></div>'+london+key+'</div>'
    +'<div class="radar-reason"><span>ENGINE REASONING</span><p>'+esc(m.reason||"No clean sequence detected.")+'</p></div>'
    +'<div class="score-breakdown"><div class="kicker">100-POINT SETUP MODEL</div>'+scoreBars(m)+'</div>'
    +'<div class="radar-warning">Potential setup only. The scanner observes and explains. It does not execute trades.</div>'
    +'</div>';
}

export function renderMarketRadar(){
  return '<section class="page-title radar-title"><div><div class="kicker">LIVE MARKET INTELLIGENCE</div><h1>Market Radar</h1><p class="sub">A multi-market command board for structure, momentum, sessions and potential trendline reversals.</p></div><div class="radar-engine"><i class="live-dot"></i><span id="radarEngineStatus">CONNECTING ENGINE</span></div></section>'
    +'<section class="radar-hero"><div><span class="kicker">TRADING HUB SCANNER</span><h2>Find where the market is actually talking.</h2><p>Radar now compares more forex pairs, gold, silver, indices and crypto using M15 structure plus H1 context. Higher scores mean more confluence, not a guaranteed trade.</p></div><div class="radar-hero-stats"><div><b id="radarWatching">0</b><span>WATCHING</span></div><div><b id="radarDeveloping">0</b><span>DEVELOPING</span></div><div><b id="radarConfirming">0</b><span>CONFIRMING</span></div><div><b id="radarBullish">0</b><span>BULLISH</span></div></div></section>'
    +'<section class="radar-grid"><div class="panel"><div class="panel-head"><div><span class="kicker">MARKET MAP</span><h2>What deserves attention</h2></div><span class="radar-refresh" id="radarUpdated">Waiting…</span></div><div class="radar-legend"><span>PAIR</span><span>PRICE / 24H</span><span>BIAS</span><span>STATE</span><span>SCORE</span></div><div class="radar-table" id="radarTable"></div></div><div class="panel" id="radarDetail"></div></section>'
    +'<section class="panel radar-fundamentals"><div class="panel-head"><div><span class="kicker">MACRO / FUNDAMENTALS</span><h2>What can move the market</h2></div><span class="radar-refresh">US EVENTS</span></div><div id="radarFundamentals" class="macro-list"><div class="macro-empty"><b>Loading macro context</b></div></div></section>'
    +'<section class="radar-method"><div class="kicker">SCANNER LOGIC · V2</div><div class="radar-steps"><span>01 M15 STRUCTURE</span><i>→</i><span>02 TRENDLINE</span><i>→</i><span>03 S/R</span><i>→</i><span>04 MOMENTUM</span><i>→</i><span>05 H1 BIAS</span><i>→</i><span>06 SESSION</span><i>→</i><b>100-POINT SETUP</b></div><p>The engine is deliberately transparent. It can say “no setup” and explain why. That creates cleaner data for the future Goldimus learning layer.</p></section>';
}

function demoData(){
  return DEMO_MARKETS.map(m=>({...m,price:m.price + Math.sin(Date.now()/60000)*0.4,updated:"Demo feed"}));
}

async function getFundamentals(){
  try{return await engineFetch("/api/market/fundamentals");}
  catch(_){return {configured:false,events:[],status:"ENGINE OFFLINE"};}
}

async function getRadar(){
  try{
    const data=await engineFetch("/api/market/radar");
    if(Array.isArray(data?.markets) && data.markets.length) return {markets:data.markets,live:true,source:data.source||"MT5"};
  }catch(_){}
  return {markets:demoData(),live:false,source:"Demo feed"};
}

function paint(result){
  latestMarkets=result.markets||[];
  const table=document.getElementById("radarTable");
  const detail=document.getElementById("radarDetail");
  if(!table||!detail) return;
  const sorted=[...latestMarkets].sort((a,b)=>(b.score||0)-(a.score||0));
  table.innerHTML=sorted.map(row).join("");
  const focus=sorted.find(m=>["CONFIRMING","DEVELOPING","WATCHING"].includes(m.state))||sorted[0];
  detail.innerHTML=renderDetail(focus);
  const counts={WATCHING:0,DEVELOPING:0,CONFIRMING:0};
  latestMarkets.forEach(m=>{if(counts[m.state]!=null)counts[m.state]++});
  document.getElementById("radarWatching").textContent=counts.WATCHING;
  document.getElementById("radarDeveloping").textContent=counts.DEVELOPING;
  document.getElementById("radarConfirming").textContent=counts.CONFIRMING;
  document.getElementById("radarBullish").textContent=latestMarkets.filter(m=>String(m.market_bias||"").startsWith("BULLISH")).length;
  document.getElementById("radarUpdated").textContent=result.live?"LIVE · "+new Date().toLocaleTimeString():"DEMO · "+new Date().toLocaleTimeString();
  const status=document.getElementById("radarEngineStatus");
  if(status) status.textContent=result.live?"LIVE MT5 ENGINE":"DEMO FEED · BACKEND NOT CONNECTED";
  table.querySelectorAll(".radar-row-btn").forEach(btn=>btn.addEventListener("click",()=>{
    const m=latestMarkets.find(x=>x.symbol===btn.dataset.symbol);
    if(m) detail.innerHTML=renderDetail(m);
  }));
}

function paintFundamentals(data){
  const el=document.getElementById("radarFundamentals");
  if(!el) return;
  if(!data.configured){
    el.innerHTML='<div class="macro-empty"><b>Macro layer ready</b><span>Connect a Trading Economics API key on the engine to bring live US economic events into the scanner.</span></div>';
    return;
  }
  const events=(data.events||[]).filter(e=>String(e.importance||"").toLowerCase()!=="low").slice(0,8);
  el.innerHTML=events.length
    ? events.map(e=>'<div class="macro-event"><span>'+esc(e.date||"")+'</span><b>'+esc(e.event||"Economic event")+'</b><em>'+esc(String(e.importance||""))+'</em></div>').join("")
    : '<div class="macro-empty"><b>No major events returned</b><span>'+esc(data.status||"LIVE")+'</span></div>';
}

export async function initMarketRadar(){
  if(refreshTimer) clearInterval(refreshTimer);
  const refresh=async()=>paint(await getRadar());
  paintFundamentals(await getFundamentals());
  await refresh();
  refreshTimer=setInterval(refresh,10000);
}
