import {engineFetch} from "./engine.js";
const DEMO_MARKETS = [
  {symbol:"XAUUSD",price:3348.20,change:0.42,state:"WATCHING",score:74,setup:"Trendline reversal",reason:"Bearish structure with repeated trendline tests. Waiting for rejection + retest.",session:"New York",updated:"Demo feed"},
  {symbol:"NAS100",price:22792.4,change:-0.31,state:"DEVELOPING",score:81,setup:"S/R retest",reason:"Price is returning to a prior reaction zone while structure remains directional.",session:"New York",updated:"Demo feed"},
  {symbol:"US500",price:6541.8,change:0.08,state:"NO SETUP",score:43,setup:"None",reason:"Structure is mixed. No clean confirmation sequence yet.",session:"New York",updated:"Demo feed"},
  {symbol:"BTCUSD",price:115820,change:1.12,state:"WATCHING",score:68,setup:"Breakout",reason:"Compression is building. Waiting for a confirmed break and retest.",session:"New York",updated:"Demo feed"},
  {symbol:"EURUSD",price:1.1742,change:-0.16,state:"CONFIRMING",score:87,setup:"Trendline reversal",reason:"Trendline rejection and structure alignment are developing together.",session:"New York",updated:"Demo feed"},
  {symbol:"GBPUSD",price:1.3518,change:0.09,state:"WATCHING",score:63,setup:"S/R retest",reason:"Approaching a marked level. Confirmation is still required.",session:"New York",updated:"Demo feed"}
];

let refreshTimer = null;
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const stateClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-");

function row(m){
  return '<div class="radar-row"><div class="radar-symbol"><b>'+esc(m.symbol)+'</b><small>'+esc(m.setup||"No setup")+'</small></div><div class="radar-price"><b>'+Number(m.price||0).toLocaleString(undefined,{maximumFractionDigits:4})+'</b><small class="'+(Number(m.change)>=0?"up":"down")+'">'+(Number(m.change)>=0?"+":"")+Number(m.change||0).toFixed(2)+'%</small></div><div><span class="radar-state '+stateClass(m.state)+'">'+esc(m.state)+'</span></div><div class="radar-score"><div class="score-ring"><span>'+Number(m.score||0)+'</span></div></div></div>';
}

function renderDetail(m){
  if(!m) return '<div class="radar-empty"><b>No active setup</b><p>The scanner is waiting for a clean sequence. That is a valid market state.</p></div>';
  const b=m.score_breakdown||{};
  const bars=["trendline","structure","support_resistance","rejection","session","volatility"].map(k=>{
    const max={trendline:20,structure:10,support_resistance:15,rejection:15,session:10,volatility:10}[k]||10;
    const label=k.replace(/_/g," ").toUpperCase();
    return '<div class="score-row"><span>'+label+'</span><i><b style="width:'+Math.min((Number(b[k]||0)/max)*100,100)+'%"></b></i><strong>'+Number(b[k]||0)+'/'+max+'</strong></div>';
  }).join("");
  const london=(m.london_high&&m.london_low)?'<div><span>LONDON RANGE</span><b>'+Number(m.london_low).toLocaleString(undefined,{maximumFractionDigits:2})+' — '+Number(m.london_high).toLocaleString(undefined,{maximumFractionDigits:2})+'</b></div>':'';
  return '<div class="radar-detail"><div class="radar-detail-top"><div><span class="kicker">ACTIVE WATCH</span><h2>'+esc(m.symbol)+'</h2><p>'+esc(m.setup||"No setup")+' · '+esc(m.session||"Session unknown")+'</p></div><div class="radar-big-score">'+Number(m.score||0)+'<small>/100</small></div></div><div class="radar-reason"><span>ENGINE REASONING</span><p>'+esc(m.reason||"Waiting for more market structure.")+'</p></div><div class="radar-checks"><div><span>STATE</span><b>'+esc(m.state)+'</b></div><div><span>PRICE</span><b>'+Number(m.price||0).toLocaleString(undefined,{maximumFractionDigits:4})+'</b></div><div><span>SPREAD</span><b>'+Number(m.spread||0).toFixed(3)+'</b></div><div><span>SESSION</span><b>'+esc(m.session||"—")+'</b></div>'+london+'</div><div class="score-breakdown"><div class="kicker">SETUP SCORE BREAKDOWN</div>'+bars+'</div><div class="radar-warning">Potential setup only. The engine does not execute trades. Confirmation, invalidation and risk rules must be defined before any trade is considered.</div></div>';
}mport {engineFetch} from "./engine.js";
const DEMO_MARKETS = [
  {symbol:"XAUUSD",price:3348.20,change:0.42,state:"WATCHING",score:74,setup:"Trendline reversal",reason:"Bearish structure with repeated trendline tests. Waiting for rejection + retest.",session:"New York",updated:"Demo feed"},
  {symbol:"NAS100",price:22792.4,change:-0.31,state:"DEVELOPING",score:81,setup:"S/R retest",reason:"Price is returning to a prior reaction zone while structure remains directional.",session:"New York",updated:"Demo feed"},
  {symbol:"US500",price:6541.8,change:0.08,state:"NO SETUP",score:43,setup:"None",reason:"Structure is mixed. No clean confirmation sequence yet.",session:"New York",updated:"Demo feed"},
  {symbol:"BTCUSD",price:115820,change:1.12,state:"WATCHING",score:68,setup:"Breakout",reason:"Compression is building. Waiting for a confirmed break and retest.",session:"New York",updated:"Demo feed"},
  {symbol:"EURUSD",price:1.1742,change:-0.16,state:"CONFIRMING",score:87,setup:"Trendline reversal",reason:"Trendline rejection and structure alignment are developing together.",session:"New York",updated:"Demo feed"},
  {symbol:"GBPUSD",price:1.3518,change:0.09,state:"WATCHING",score:63,setup:"S/R retest",reason:"Approaching a marked level. Confirmation is still required.",session:"New York",updated:"Demo feed"}
];

let refreshTimer = null;
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const stateClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-");

function row(m){
  return '<div class="radar-row"><div class="radar-symbol"><b>'+esc(m.symbol)+'</b><small>'+esc(m.setup||"No setup")+'</small></div><div class="radar-price"><b>'+Number(m.price||0).toLocaleString(undefined,{maximumFractionDigits:4})+'</b><small class="'+(Number(m.change)>=0?"up":"down")+'">'+(Number(m.change)>=0?"+":"")+Number(m.change||0).toFixed(2)+'%</small></div><div><span class="radar-state '+stateClass(m.state)+'">'+esc(m.state)+'</span></div><div class="radar-score"><div class="score-ring"><span>'+Number(m.score||0)+'</span></div></div></div>';
}

function renderDetail(m){
  if(!m) return '<div class="radar-empty"><b>No active setup</b><p>The scanner is waiting for a clean sequence. That is a valid market state.</p></div>';
  return '<div class="radar-detail"><div class="radar-detail-top"><div><span class="kicker">ACTIVE WATCH</span><h2>'+esc(m.symbol)+'</h2><p>'+esc(m.setup||"No setup")+' · '+esc(m.session||"Session unknown")+'</p></div><div class="radar-big-score">'+Number(m.score||0)+'<small>/100</small></div></div><div class="radar-reason"><span>ENGINE REASONING</span><p>'+esc(m.reason||"Waiting for more market structure.")+'</p></div><div class="radar-checks"><div><span>STATE</span><b>'+esc(m.state)+'</b></div><div><span>PRICE</span><b>'+Number(m.price||0).toLocaleString(undefined,{maximumFractionDigits:4})+'</b></div><div><span>SESSION</span><b>'+esc(m.session||"—")+'</b></div></div><div class="radar-warning">⚠ Potential setup only. Confirmation, invalidation and risk rules must be defined before any trade is considered.</div></div>';
}

export function renderMarketRadar(){
  return '<section class="page-title radar-title"><div><div class="kicker">LIVE MARKET INTELLIGENCE</div><h1>Market Radar</h1><p class="sub">Scan multiple instruments and surface potential setups before you open every chart yourself.</p></div><div class="radar-engine"><i class="live-dot"></i><span id="radarEngineStatus">CONNECTING ENGINE</span></div></section><section class="radar-hero"><div><span class="kicker">TRADING HUB SCANNER</span><h2>Find the market worth looking at.</h2><p>Trendline structure, support/resistance, session context and volatility will eventually feed one transparent setup score.</p></div><div class="radar-hero-stats"><div><b id="radarWatching">0</b><span>WATCHING</span></div><div><b id="radarDeveloping">0</b><span>DEVELOPING</span></div><div><b id="radarConfirming">0</b><span>CONFIRMING</span></div></div></section><section class="radar-grid"><div class="panel"><div class="panel-head"><div><span class="kicker">MARKET QUEUE</span><h2>What deserves attention</h2></div><span class="radar-refresh" id="radarUpdated">Waiting…</span></div><div class="radar-table" id="radarTable"></div></div><div class="panel" id="radarDetail"></div></section><section class="radar-method"><div class="kicker">SCANNER LOGIC · V1</div><div class="radar-steps"><span>01 Structure</span><i>→</i><span>02 Trendline</span><i>→</i><span>03 S/R</span><i>→</i><span>04 Session</span><i>→</i><span>05 Confirmation</span><i>→</i><b>Potential setup</b></div><p>V1 is intentionally rule-based. The AI layer can learn from your journal after the scanner proves that its detections match the strategy.</p></section>';
}

function demoData(){
  const now = new Date();
  return DEMO_MARKETS.map((m,i)=>({...m, price:m.price + Math.sin(now.getTime()/60000+i)*0.8, updated:"Demo feed"}));
}

async function getRadar(){
  try{
    const data=await engineFetch("/api/market/radar");
    if(Array.isArray(data?.markets) && data.markets.length) return {markets:data.markets,live:true,source:data.source||"MT5"};
  }catch(_){}
  return {markets:demoData(),live:false,source:"Demo feed"};
}

function paint(result){
  const table=document.getElementById("radarTable");
  const detail=document.getElementById("radarDetail");
  if(!table||!detail) return;
  table.innerHTML=result.markets.map(row).join("");
  const focus=result.markets.filter(m=>["CONFIRMING","DEVELOPING","WATCHING"].includes(m.state)).sort((a,b)=>(b.score||0)-(a.score||0))[0];
  detail.innerHTML=renderDetail(focus);
  const counts={WATCHING:0,DEVELOPING:0,CONFIRMING:0};
  result.markets.forEach(m=>{if(counts[m.state]!=null)counts[m.state]++});
  document.getElementById("radarWatching").textContent=counts.WATCHING;
  document.getElementById("radarDeveloping").textContent=counts.DEVELOPING;
  document.getElementById("radarConfirming").textContent=counts.CONFIRMING;
  document.getElementById("radarUpdated").textContent=result.live?"LIVE · "+new Date().toLocaleTimeString():"DEMO · "+new Date().toLocaleTimeString();
  const status=document.getElementById("radarEngineStatus");
  if(status) status.textContent=result.live?"LIVE MT5 ENGINE":"DEMO FEED · BACKEND NOT CONNECTED";
}

export async function initMarketRadar(){
  if(refreshTimer) clearInterval(refreshTimer);
  const refresh=async()=>paint(await getRadar());
  await refresh();
  refreshTimer=setInterval(refresh,10000);
}
