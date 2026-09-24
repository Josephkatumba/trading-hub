// TRADeden Garden — the market radar page controller.
// Data, polling, confirmation alerts and demo/offline handling are unchanged from
// the previous radar; presentation lives in ./garden/* (view models, markup and
// the optional 3D/2D garden visual, which can fail or be disabled independently).
import "./garden/garden.css";
import {engineFetch,getEngineUrl} from "./engine.js";
import {createPoller} from "./radarPolling.mjs";
import {confirmationDisplay, renderAnalystEvidence} from "./analystPresentation.mjs";
import {setupCountSummary, visibleSetupEntries} from "./radarLayout.mjs";
import {createConfirmationAlertTracker, dispatchConfirmationAlerts, dispatchTestSound, persistedConfirmationEvents} from "./confirmationAlerts.mjs";
import {CONFIRMATION_CHIME_CONFIG, playConfirmationChime} from "./confirmationChime.mjs";
import {analystModel, archiveEntry, archiveSummary, gardenAreas, gardenCounters, marketOverviewRow, constellationLayout, setupCardModel} from "./garden/gardenModel.mjs";
import {analystPanel, archivePanel, counterTiles, emptyArea, esc, focusPanel, marketOverview, setupCard, stageLegend, strategyFilterBar, strategyLabPanel, strategyPerformanceBlock} from "./garden/gardenCards.mjs";
import {filterByStrategy, matchesStrategy, strategyFilters, strategyPerformance, strategyTag} from "./strategyModel.mjs";
import {mountGarden, prefersReducedMotion} from "./garden/gardenMount.mjs";

const DEMO_MARKETS = [
  {symbol:"XAUUSD",price:3348.2,change_pct:0.42,state:"WATCHING",score:74,setup:"Trendline setup",reason:"Trendline is being monitored for a break or rejection, with support/resistance as confirmation.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"BEARISH",structure:"Lower highs + lower lows",stage:"TRENDLINE TEST",insight:"Bearish structure is active. Confirmation is still required.",rsi:44,action:"WAIT",trigger:"Wait for a confirmed trendline break/retest or a clean rejection at S/R."},
  {symbol:"EURUSD",price:1.1742,change_pct:-0.16,state:"WATCHING",score:71,setup:"Trendline setup",reason:"Resistance is being tested for a trendline break or rejection.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"BEARISH",structure:"Lower highs + lower lows",stage:"TRENDLINE TEST",insight:"Bearish structure with momentum alignment.",rsi:46,action:"WAIT",trigger:"Watch the resistance interaction and wait for price-action confirmation."},
  {symbol:"GBPUSD",price:1.3518,change_pct:0.09,state:"WATCHING",score:68,setup:"Trendline setup",reason:"Approaching a key reaction zone where a break or reversal may develop.",session:"New York",market_bias:"RANGE / NEUTRAL",momentum:"NEUTRAL",higher_timeframe_bias:"NEUTRAL",structure:"Mixed / range",stage:"STRUCTURE BIAS",insight:"Mixed structure. Wait for cleaner directional evidence.",rsi:51,action:"WAIT",trigger:"Wait for top-down structure and a clear price-action sequence."},
  {symbol:"USDJPY",price:147.42,change_pct:0.18,state:"DEVELOPING",score:66,setup:"Trendline setup",reason:"Ascending support is being tested while momentum leans bullish.",session:"New York",market_bias:"BULLISH",momentum:"BULLISH",higher_timeframe_bias:"BULLISH",structure:"Higher lows",stage:"TRENDLINE TEST",insight:"Bullish structure is developing around support.",rsi:57,action:"WAIT",trigger:"Wait for a confirmed support rejection and trendline continuation."},
  {symbol:"NAS100",price:22418.0,change_pct:0.35,state:"DEVELOPING",score:64,setup:"Trendline setup",reason:"Price is approaching a trendline reaction zone with bullish structure.",session:"New York",market_bias:"BULLISH",momentum:"BULLISH",higher_timeframe_bias:"BULLISH",structure:"Higher highs + higher lows",stage:"TRENDLINE TEST",insight:"Bullish structure is developing, but confirmation is still required.",rsi:59,action:"WAIT",trigger:"Wait for a clean break/retest or rejection confirmation."},
  {symbol:"US500",price:6398.5,change_pct:0.21,state:"WATCHING",score:62,setup:"Trendline setup",reason:"Index structure is constructive but the next trendline interaction needs confirmation.",session:"New York",market_bias:"BULLISH",momentum:"NEUTRAL",higher_timeframe_bias:"BULLISH",structure:"Higher lows",stage:"STRUCTURE BIAS",insight:"Constructive context without a confirmed trigger.",rsi:54,action:"WAIT",trigger:"Wait for trendline and support/resistance alignment."},
  {symbol:"BTCUSD",price:112840.0,change_pct:-0.48,state:"WATCHING",score:59,setup:"Trendline setup",reason:"Price is consolidating beneath resistance while trendline structure develops.",session:"New York",market_bias:"BEARISH",momentum:"BEARISH",higher_timeframe_bias:"RANGE / NEUTRAL",structure:"Lower highs",stage:"TRENDLINE TEST",insight:"Resistance remains the key decision area.",rsi:47,action:"WAIT",trigger:"Wait for a confirmed break or rejection before considering direction."},
  {symbol:"ETHUSD",price:4218.0,change_pct:-0.31,state:"WATCHING",score:57,setup:"Trendline setup",reason:"Ethereum is testing a short-term resistance structure.",session:"New York",market_bias:"BEARISH",momentum:"NEUTRAL",higher_timeframe_bias:"BEARISH",structure:"Lower highs",stage:"TRENDLINE TEST",insight:"Bearish context is present, but confirmation is missing.",rsi:49,action:"WAIT",trigger:"Wait for price action to confirm the trendline reaction."},
  {symbol:"XAGUSD",price:39.18,change_pct:0.27,state:"DEVELOPING",score:55,setup:"Trendline setup",reason:"Silver is approaching support with a potential reversal structure.",session:"New York",market_bias:"BULLISH",momentum:"BULLISH",higher_timeframe_bias:"BULLISH",structure:"Higher lows",stage:"REVERSAL WATCH",insight:"Potential bullish reversal context is forming.",rsi:56,action:"WAIT",trigger:"Wait for a confirmed rejection and S/R alignment."},
  {symbol:"GBPJPY",price:199.62,change_pct:0.14,state:"WATCHING",score:53,setup:"Trendline setup",reason:"Cross-pair structure is mixed and needs a cleaner trendline event.",session:"New York",market_bias:"RANGE / NEUTRAL",momentum:"NEUTRAL",higher_timeframe_bias:"BULLISH",structure:"Mixed / range",stage:"STRUCTURE BIAS",insight:"Mixed conditions make patience important.",rsi:52,action:"WAIT",trigger:"Wait for a clear trendline break/reversal with S/R confirmation."}
];

const TRACKED_KEY="tradeden.trackedSetups";
let radarPoller = null;
let pendingAnchor = null;
let radarMode = "LIVE";
let latestResult = null;
let latestMarkets = [];
let latestEpisodes = {current:[],confirmed:[],closed:[]};
let growingExpanded = false;
let historyExpanded = false;
let archiveFilter = "all";
let strategyFilter = "all";           // "all" or a strategy_id; applies to setups, archive and performance
let latestRegistry = null;            // engine strategy registry (null: offline, trendline assumed)
let latestOutcomes = [];
let latestArchive = [];
let selectedKey = null;
let analystCache = new Map();
let latestCards = new Map();          // key -> {row, card}
const expandedEvidence = new Set();
let garden = null;                    // mounted garden visual controller
let gardenMountToken = 0;
let confirmationAlertsEnabled = false;
let confirmationAlertTracker = null;
let alertAudioContext = null;
let nextAlertToneAt = 0;
const confirmationAlertSessionStartedAt = Date.now();
const confirmationToastTimers = new Map();
const confirmedDetailCache = new Map();
const confirmedDetailPending = new Set();

function readTracked(){try{const v=JSON.parse(localStorage.getItem(TRACKED_KEY)||"[]");return new Set(Array.isArray(v)?v:[]);}catch(_){return new Set();}}
function writeTracked(set){try{localStorage.setItem(TRACKED_KEY,JSON.stringify([...set].slice(-200)));}catch(_){}}
let tracked = readTracked();

export function renderMarketRadar(){
  return '<div id="radarRoot" class="radar-root garden-root">'
    +'<div id="radarModeBanner" class="radar-mode-banner" role="status" hidden></div>'
    +'<header class="gd-topbar"><div class="gd-brand"><span class="gd-brand-mark" aria-hidden="true">🌿</span><div><b>TRAD<span>eden</span></b><small>Market intelligence garden</small></div></div>'
    +'<div class="gd-top-tools"><div class="gd-engine"><i class="gd-status-dot" aria-hidden="true"></i><span id="radarEngineStatus">Connecting engine</span></div><span class="gd-updated" id="radarUpdated">Waiting…</span>'
    +'<div class="confirmation-alert-controls" id="gardenAlerts"><button type="button" id="confirmationAlertsToggle" class="alert-control" aria-pressed="false" title="Enable Alerts">🔇 Alerts OFF</button><button type="button" id="testConfirmationSound" class="alert-test-control">Test sound</button></div></div>'
    +'<div id="confirmationToast" class="confirmation-toast" role="status" aria-live="polite" hidden></div></header>'
    +'<section class="gd-world" id="gardenWorld" aria-label="The TRADeden Garden">'
    +'<div class="gd-world-stage"><div class="gd-stage" id="gardenStage"></div><div class="gd-stage-overlay" id="gardenOverlay" hidden></div><div class="gd-focus" id="gardenFocus" role="region" aria-label="Selected setup" aria-live="polite" hidden></div>'
    +'<div class="gd-legend">'+stageLegend()+'</div><small class="gd-stage-mode" id="gardenModeNote"></small></div>'
    +'<div class="gd-world-copy"><span class="gd-eyebrow" id="radarEyebrow">🌿 The TRADeden Garden</span>'
    +'<h1>The market is always moving.<br><span>TRADeden is always watching.</span></h1>'
    +'<p>TRADeden continuously watches the markets for developing structures, confirmations and invalidations so you don\'t have to stare at charts all day.</p>'
    +'<div class="gd-counters" id="gardenCounters">'+counterTiles(null)+'</div>'
    +'<p class="gd-hero-note" id="gardenHeroNote">Every orb is a real setup from the existing strategy and lifecycle. Execution stays manual — TRADeden never places orders.</p></div></section>'
    +'<div class="gd-strategy-bar" id="strategyFilterBar"></div>'
    +'<div class="gd-layout"><div class="gd-main">'
    +area("growing","🌱","Growing Garden","Current and developing setups. Evidence is still accumulating.")
    +area("bloomed","🌸","Bloomed Setups","Confirmed by the existing strategy rules, including setups now being tracked as active.")
    +'<section class="gd-area gd-area-history" id="area-history"><header class="gd-area-head"><div><h2><span aria-hidden="true">🍂</span> Garden Archive</h2><p>What happened to the setups TRADeden surfaced. Only confirmed setups can hit a target or stop; the rest failed or went stale before confirmation.</p></div><span class="gd-count" id="historyCount"></span></header><div id="historyCards" class="gd-archive"></div></section>'
    +'</div><div class="gd-side"><section class="gd-analyst" id="gardenAnalyst" aria-live="polite">'+analystPanel(null)+'</section>'
    +'<section class="gd-panel gd-markets" id="gardenMarkets"><header class="gd-panel-head"><h2>Markets TRADeden watches</h2><span class="gd-count" id="marketCount"></span></header><div id="radarTable" class="gd-market-list"></div></section></div></div>'
    +'<section class="gd-panel performance-panel" id="gardenPerformance"><header class="gd-panel-head"><div><h2>📊 Today\'s setup performance</h2><p>Headline uses the 4h market outcome. Other configured horizons remain visible. Trade outcomes are excluded.</p></div></header><div id="dailyPerformance"><div class="macro-empty"><b>Loading performance</b></div></div></section>'
    +'<details class="gd-panel gd-strategy-lab" id="strategyLab"><summary><span>🧪 Strategy Lab</span><span class="historical-expand-hint">Expand</span></summary><p>Registered strategies and their status. Only live strategies produce Garden setups; shadow-mode results are for review here and never appear in the Garden.</p><div id="strategyLabBody"></div></details>'
    +'<details class="gd-panel historical-confirmations" id="historicalConfirmations"><summary><span>📚 Confirmation event archive · today (<b id="historicalConfirmationCount">0</b>)</span><span class="historical-expand-hint">Expand</span></summary><p class="gd-archive-status" id="confirmedArchiveStatus"></p><div id="historicalConfirmationCards" class="gd-grid"></div></details>'
    +'<section class="gd-panel radar-fundamentals"><header class="gd-panel-head"><h2>Macro events that can change the tape</h2><span class="gd-count">US events</span></header><div id="radarFundamentals" class="macro-list"><div class="macro-empty"><b>Loading macro context</b></div></div></section>'
    +'<footer class="gd-method"><p><b>How TRADeden watches:</b> H1 context → price action → trendline → support/resistance → CRT → session → a transparent 100-point setup score. Breaks and reversals are both valid setup families; the trendline event is the strategy gate.</p><p>TRADeden is decision support, not an auto-trading platform. Not an entry recommendation.</p></footer>'
    +'</div>';
}
function area(key,icon,title,text){
  return '<section class="gd-area gd-area-'+key+'" id="area-'+key+'"><header class="gd-area-head"><div><h2><span aria-hidden="true">'+icon+'</span> '+title+'</h2><p>'+text+'</p></div><span class="gd-count" id="'+key+'Count"></span></header><div class="gd-grid" id="'+key+'Cards"></div></section>';
}

// Demo fixtures are for UI development only and are OFF by default. Enable with
// VITE_RADAR_DEMO=1 at build time or localStorage th_radar_demo=1 in the browser.
export function radarDemoEnabled(){
  try{if(import.meta.env?.VITE_RADAR_DEMO==="1")return true;}catch(_){}
  try{return localStorage.getItem("th_radar_demo")==="1";}catch(_){return false;}
}
function demoData(){return DEMO_MARKETS.map(m=>({...m,simulated:true,source:"DEMO",updated:"Simulated fixture"}));}
async function getFundamentals(){try{return await engineFetch("/api/market/fundamentals");}catch(_){return {configured:false,events:[],status:"ENGINE OFFLINE"};}}
// mode: LIVE | ENGINE_NO_DATA (engine reachable, MT5 returned nothing) | OFFLINE | DEMO.
// A reachable engine is never replaced by demo data.
async function getRadar(){
  try{
    const data=await engineFetch("/api/market/radar"),markets=Array.isArray(data?.markets)?data.markets:[];
    return {mode:data?.live&&markets.length?"LIVE":"ENGINE_NO_DATA",markets,live:!!data?.live&&markets.length>0,source:data?.source||"MT5",timestamp:data?.timestamp,mt5Status:data?.mt5_status,error:data?.error,registry:Array.isArray(data?.strategy_registry)?data.strategy_registry:null};
  }catch(_){}
  return radarDemoEnabled()?{mode:"DEMO",markets:demoData(),live:false,source:"DEMO"}:{mode:"OFFLINE",markets:[],live:false,source:"OFFLINE"};
}
async function getPerformance(){try{return await engineFetch("/api/market/performance");}catch(_){return null;}}
const analysisKey=row=>row?.setup_id?row.setup_id+":"+(row.observation_id||""):null;
// One request per analysis: concurrent callers share the in-flight promise.
// (Caching only on completion let every repaint re-request pending analyses.)
const analysisInFlight=new Map();
function getAnalysis(m){
  if(!m?.setup_id)return Promise.resolve(null);
  const observationId=m.observation_id||"";const key=m.setup_id+":"+observationId;
  if(analystCache.has(key))return Promise.resolve(analystCache.get(key));
  if(analysisInFlight.has(key))return analysisInFlight.get(key);
  const suffix=observationId?"?observation_id="+encodeURIComponent(observationId):"";
  const request=engineFetch("/api/market/setups/"+encodeURIComponent(m.setup_id)+"/analysis"+suffix)
    .then(data=>{analystCache.set(key,data);return data;},()=>{analystCache.set(key,null);return null;})
    .finally(()=>analysisInFlight.delete(key));
  analysisInFlight.set(key,request);
  return request;
}
async function getSetupEpisodes(){try{return await engineFetch("/api/market/setup-episodes?bucket=all&limit=100");}catch(_){return null;}}
async function getOutcomes(){try{const data=await engineFetch("/api/market/outcomes");return Array.isArray(data?.outcomes)?data.outcomes:null;}catch(_){return null;}}

// ----- cards ------------------------------------------------------------------
function cardFor(row,bucket){
  const card=setupCardModel(row,{bucket,analysis:analystCache.get(analysisKey(row))||null,tracked:tracked.has(row?.setup_id),simulated:radarMode==="DEMO"});
  if(card.key)latestCards.set(card.key,{row,card});
  return card;
}
function cardHtml(card,extraFoot=""){
  const expanded=expandedEvidence.has(card.key);
  const row=latestCards.get(card.key)?.row;
  const key=analysisKey(row);
  const analysis=key?analystCache.get(key):undefined;
  return setupCard(card,{selected:card.key===selectedKey,expanded,evidenceHtml:analysis?renderAnalystEvidence(analysis):null,evidenceState:expanded&&key&&analysis===undefined?"loading":"idle",extraFoot});
}
function paintAreas(areas){
  const trackedFirst=(a,b)=>Number(b.tracked)-Number(a.tracked);
  const growing=areas.growing.map(row=>cardFor(row,"growing")).sort(trackedFirst);
  const bloomed=areas.bloomed.map(row=>cardFor(row,"bloomed")).sort(trackedFirst);
  const archive=paintArchive(areas.history);
  const history=areas.history.map((row,index)=>({...cardFor(row,"history"),outcome:archive[index]?.kind||null}));
  const offline=radarMode==="OFFLINE";
  const node=id=>document.getElementById(id);
  const toolbar=(total,expanded,key)=>{const summary=total>6?setupCountSummary(total,expanded):null;return summary?'<div class="gd-toolbar"><span>'+esc(summary)+'</span><button type="button" class="gd-link" data-toggle="'+key+'" aria-expanded="'+expanded+'">'+(expanded?"Show less":"View all")+'</button></div>':"";};
  if(node("growingCards"))node("growingCards").innerHTML=growing.length
    ?toolbar(growing.length,growingExpanded,"growing")+visibleSetupEntries(growing,growingExpanded).map(card=>cardHtml(card)).join("")
    :emptyArea(offline?"The garden is not being watched":"Nothing growing right now",offline?"Engine offline — no setups are being evaluated.":"The engine is scanning; no setup is currently developing. No setup is a valid state.");
  if(node("bloomedCards"))node("bloomedCards").innerHTML=bloomed.length?bloomed.map(card=>cardHtml(card)).join(""):emptyArea("No bloomed setups",offline?"Engine offline.":"No setup currently passes the confirmation rules.");
  const count=(id,n,word)=>{if(node(id))node(id).textContent=n+" "+word;};
  count("growingCount",growing.length,"growing");count("bloomedCount",bloomed.length,"bloomed");count("historyCount",history.length,"latest closed");
  return {growing,bloomed,history};
}

// The archive: closed episodes and what happened to them (verified outcomes only).
function confirmationSnapshot(row){
  const id=row?.setup_id,observation=row?.confirmation?.observation_id;
  return (confirmedDetailCache.get(id)?.snapshots||[]).find(snapshot=>snapshot.observation_id===observation)||null;
}
function paintArchive(rows){
  const entries=rows.map(row=>archiveEntry(row,latestOutcomes,confirmationSnapshot(row)));
  // R needs the confirmation snapshot's planned levels: load it only for verified hits.
  for(const [index,entry] of entries.entries())if((entry.kind==="target"||entry.kind==="stop")&&!confirmationSnapshot(rows[index]))fetchConfirmedDetail(entry.key,()=>repaintCards());
  latestArchive=entries;
  const node=document.getElementById("historyCards");
  if(node)node.innerHTML=entries.length?archivePanel(entries,archiveSummary(entries),{filter:archiveFilter,selectedKey,expanded:historyExpanded})
    :emptyArea("No closed setups yet","Closed, expired and invalidated setups will rest here with what happened to them.");
  return entries;
}

function defaultSelection(cards){
  return (cards.bloomed[0]||cards.growing[0]||null)?.key||null;
}
function selectedRow(){
  if(!selectedKey)return null;
  const entry=latestCards.get(selectedKey);
  if(entry)return entry.row;
  return latestMarkets.find(m=>m.setup_id===selectedKey||"mkt-"+m.symbol===selectedKey)||null;
}
function paintAnalyst(){
  const node=document.getElementById("gardenAnalyst");if(!node)return;
  if(radarMode==="OFFLINE"&&!selectedRow()){node.innerHTML=offlineDetail(radarMode);return;}
  const row=selectedRow();
  const key=analysisKey(row);
  const analysis=key?analystCache.get(key):null;
  const archive=row?latestArchive.find(entry=>entry.key&&entry.key===row.setup_id)||null:null;
  node.innerHTML=analystPanel(row?analystModel(row,analysis||null,archive):null,{loading:Boolean(key)&&analysis===undefined,simulated:radarMode==="DEMO"});
  if(key&&analysis===undefined)getAnalysis(row).then(()=>{if(selectedKey&&analysisKey(selectedRow())===key){paintAnalyst();repaintCards();}});
}
function paintFocus(){
  const node=document.getElementById("gardenFocus");if(!node)return;
  const row=selectedRow();
  const key=analysisKey(row);
  const card=row?setupCardModel(row,{analysis:key?analystCache.get(key)||null:null,simulated:radarMode==="DEMO"}):null;
  node.hidden=!card;
  node.innerHTML=card?focusPanel(card):"";
}
function pinLabel(){
  const row=selectedRow();if(!row)return "";
  const card=setupCardModel(row);
  return '<b>'+esc(card.symbol)+'</b><span>'+card.stageIcon+' '+esc(card.stageLabel)+(card.direction?' · '+card.direction:'')+'</span>';
}
function paintGarden(cards){
  if(!garden)return;
  const plants=constellationLayout([...cards.bloomed,...cards.growing,...cards.history],selectedKey);
  garden.update(plants);
  garden.select(selectedKey,pinLabel());
  const overlay=document.getElementById("gardenOverlay");
  if(overlay){
    const [title,text]=gardenCaption(plants);
    overlay.hidden=!title;overlay.dataset.mode=radarMode;
    overlay.innerHTML=title?'<b>'+esc(title)+'</b>'+(text?'<span>'+esc(text)+'</span>':''):"";
  }
}
// Honest captions: the environment is ambient; only real setups are orbs.
function gardenCaption(orbs){
  if(radarMode==="OFFLINE")return ["The garden is resting.","Engine offline — nothing here reflects the current market."];
  if(radarMode==="DEMO")return ["Simulated garden.","Demo fixtures, not market data."];
  if(radarMode==="ENGINE_NO_DATA")return ["The engine is online.","MT5 returned no markets, so nothing is being watched."];
  const live=orbs.filter(orb=>orb.stage!=="history");
  if(!live.length)return ["The garden is watching.","Nothing is developing right now. TRADeden keeps scanning "+latestMarkets.length+" markets."];
  if(!live.some(orb=>orb.stage==="bloomed"||orb.stage==="active"))return ["Nothing has bloomed yet.","TRADeden is waiting for confirmation."];
  return [null,null];
}
let lastCards={growing:[],bloomed:[],history:[]};
function visibleAreas(){
  const areas=gardenAreas(latestEpisodes,latestMarkets,{registry:latestRegistry});
  return {growing:filterByStrategy(areas.growing,strategyFilter),bloomed:filterByStrategy(areas.bloomed,strategyFilter),history:filterByStrategy(areas.history,strategyFilter)};
}
function paintStrategyControls(){
  const filters=strategyFilters(latestRegistry);
  if(!filters.some(filter=>filter.key===strategyFilter&&filter.selectable))strategyFilter="all";
  const bar=document.getElementById("strategyFilterBar");if(bar)bar.innerHTML=strategyFilterBar(filters,strategyFilter);
  const lab=document.getElementById("strategyLabBody");if(lab)lab.innerHTML=strategyLabPanel(latestRegistry);
}
function repaintCards(){
  if(!latestResult)return;
  latestCards=new Map();
  lastCards=paintAreas(visibleAreas());
  paintGarden(lastCards);
}
function select(key,{scrollTo=null}={}){
  selectedKey=key;
  for(const node of document.querySelectorAll(".gd-card"))node.classList.toggle("is-selected",node.dataset.key===key);
  for(const node of document.querySelectorAll(".gd-card"))node.setAttribute("aria-selected",String(node.dataset.key===key));
  for(const node of document.querySelectorAll("[data-archive-key]"))node.classList.toggle("is-selected",node.dataset.archiveKey===key);
  paintAnalyst();
  paintFocus();
  garden?.select(key,pinLabel());
  const target=scrollTo&&document.getElementById(scrollTo);
  if(target)target.scrollIntoView({behavior:prefersReducedMotion()?"auto":"smooth",block:"start"});
}
function bindGardenInteractions(){
  const root=document.getElementById("radarRoot");if(!root)return;
  root.onclick=event=>{
    const focusAction=event.target.closest("[data-focus-action]")?.dataset.focusAction;
    if(focusAction==="view-analysis"){document.getElementById("gardenAnalyst")?.scrollIntoView({behavior:prefersReducedMotion()?"auto":"smooth",block:"start"});return;}
    if(focusAction==="view-setup"){
      const target=[...document.querySelectorAll(".gd-card[data-key],[data-archive-key]")].find(node=>(node.dataset.key||node.dataset.archiveKey)===selectedKey);
      if(target){target.scrollIntoView({behavior:prefersReducedMotion()?"auto":"smooth",block:"center"});target.classList.remove("is-flash");void target.offsetWidth;target.classList.add("is-flash");}
      return;
    }
    const toggle=event.target.closest("[data-toggle]");
    if(toggle){if(toggle.dataset.toggle==="growing")growingExpanded=!growingExpanded;else historyExpanded=!historyExpanded;repaintCards();return;}
    const strategyButton=event.target.closest("[data-strategy-filter]");
    if(strategyButton){strategyFilter=strategyButton.dataset.strategyFilter;historyExpanded=false;growingExpanded=false;paintStrategyControls();repaintCards();if(latestResult){paintConfirmed(latestMarkets,latestResult.performance);paintPerformance(latestResult.performance);}return;}
    const filterButton=event.target.closest("[data-archive-filter]");
    if(filterButton){archiveFilter=filterButton.dataset.archiveFilter;historyExpanded=false;repaintCards();return;}
    const archiveRow=event.target.closest("[data-archive-key]");
    if(archiveRow){select(archiveRow.dataset.archiveKey,{scrollTo:window.innerWidth<1100?"gardenAnalyst":null});return;}
    const marketRow=event.target.closest(".gd-market-row");
    if(marketRow){const m=latestMarkets.find(x=>x.symbol===marketRow.dataset.symbol);if(m){const live=[...lastCards.bloomed,...lastCards.growing].find(c=>c.symbol===m.symbol);select(live?live.key:(m.setup_id||"mkt-"+m.symbol),{scrollTo:window.innerWidth<1100?"gardenAnalyst":null});}return;}
    const card=event.target.closest(".gd-card");if(!card)return;
    const key=card.dataset.key,action=event.target.closest("[data-action]")?.dataset.action;
    if(action==="view-evidence"){
      if(expandedEvidence.has(key))expandedEvidence.delete(key);else{expandedEvidence.add(key);const row=latestCards.get(key)?.row;if(row&&!analystCache.has(analysisKey(row)))getAnalysis(row).then(()=>repaintCards());}
      repaintCards();return;
    }
    if(action==="track"){const id=card.dataset.setupId;if(id){if(tracked.has(id))tracked.delete(id);else tracked.add(id);writeTracked(tracked);repaintCards();}return;}
    if(action==="view-analysis"){select(key,{scrollTo:"gardenAnalyst"});return;}
    if(action==="view-setup"){select(key,{scrollTo:"gardenStage"});return;}
    select(key);
  };
  root.onkeydown=event=>{const card=event.target.closest?.(".gd-card");if(card&&event.target===card&&(event.key==="Enter"||event.key===" ")){event.preventDefault();select(card.dataset.key);}};
}

// ----- confirmation archive (today's confirmation events) -----------------------
function confirmedEntries(markets, performance){
  const day=performance?.daily?.[0]||performance?.summary;
  const persisted=Array.isArray(day?.setups)?day.setups:[];
  const records=new Map(persisted.filter(e=>e.setup_id).map(e=>[e.setup_id,e]));
  for(const market of markets){const detail=confirmedDetailCache.get(market.setup_id);if(market.strategy_valid===true&&market.setup_id&&!records.has(market.setup_id)&&detail){const event=(detail.confirmation_events||[]).find(row=>row.setup_id===market.setup_id);if(event)records.set(market.setup_id,event);}}
  return [...records.values()].map(raw=>{
    const detail=confirmedDetailCache.get(raw.setup_id);
    const savedEvent=detail&&(detail.confirmation_events||[]).find(row=>row.setup_id===raw.setup_id);
    const event=savedEvent?{...raw,...savedEvent}:raw;
    const snapshots=detail?.snapshots||[];
    const confirmedSnapshot=snapshots.find(row=>row.observation_id===event.observation_id)||{};
    const latestSnapshot=[...snapshots].sort((a,b)=>String(a.observed_at||"").localeCompare(String(b.observed_at||""))).at(-1)||{};
    const detailOutcome=(detail?.market_outcomes||[]).find(row=>row.observation_id===event.observation_id&&row.horizon==="4h");
    const primary=event.primary_outcome||event.market_outcomes?.["4h"]||detailOutcome?.label||"PENDING";
    const currentMarket=markets.find(m=>m.setup_id===raw.setup_id)||null;
    const market=currentMarket||latestSnapshot;
    const display=confirmationDisplay(event,currentMarket,latestSnapshot);
    return {event:{...confirmedSnapshot,...event,market_outcomes:event.market_outcomes||{"4h":detailOutcome?.label||"PENDING"},primary_outcome:primary},market,display};
  }).sort((a,b)=>String(b.event.confirmed_at||"").localeCompare(String(a.event.confirmed_at||"")));
}
function fetchConfirmedDetail(id,onDone){
  if(!id||confirmedDetailCache.has(id)||confirmedDetailPending.has(id))return;
  confirmedDetailPending.add(id);
  engineFetch("/api/market/setups/"+encodeURIComponent(id)).then(detail=>{confirmedDetailCache.set(id,detail);}).catch(()=>{confirmedDetailCache.set(id,null);}).finally(()=>{confirmedDetailPending.delete(id);onDone();});
}
function paintConfirmed(markets, performance){
  const container=document.getElementById("historicalConfirmationCards"),status=document.getElementById("confirmedArchiveStatus"),count=document.getElementById("historicalConfirmationCount");
  if(!container||!status||!count)return;
  const repaint=()=>{if(container.isConnected)paintConfirmed(markets,performance);};
  for(const market of markets)if(market.strategy_valid===true)fetchConfirmedDetail(market.setup_id,repaint);
  const entries=confirmedEntries(markets,performance).filter(({event})=>matchesStrategy(event,strategyFilter));
  for(const {event} of entries)fetchConfirmedDetail(event.setup_id,repaint);
  const pending=entries.filter(({event})=>String(event.primary_outcome||event.market_outcomes?.["4h"]||"").toUpperCase()==="PENDING").length;
  const current=entries.filter(({display})=>display.currentlyConfirmed).length;
  status.textContent=current+" currently confirmed · "+pending+" 4h outcome pending · "+entries.length+" confirmation events today";
  count.textContent=String(entries.length);
  container.innerHTML=entries.length?entries.map(({event,market,display})=>{
    const row={...market,...event,lifecycle_state:display.currentLifecycle!=="UNKNOWN"?display.currentLifecycle:(event.lifecycle_state||"CONFIRMED"),confirmation:{confirmed_at:event.confirmed_at}};
    const outcome=String(event.primary_outcome||"PENDING").toUpperCase();
    const card=setupCardModel(row,{bucket:"archive",analysis:analystCache.get(analysisKey(event))||null,simulated:radarMode==="DEMO"});
    return setupCard({...card,key:"archive-"+(event.setup_id||"")},{extraFoot:'<small class="gd-outcome">4h market outcome: <b>'+esc(outcome==="PENDING"?"Pending":outcome)+'</b> · '+esc(display.label.toLowerCase())+' · not a trade result</small>'});
  }).join(""):'<div class="gd-empty"><b>No confirmation events today.</b></div>';
  for(const {event} of entries){const key=analysisKey(event);if(event.observation_id&&!analystCache.has(key)&&!analysisInFlight.has(key))getAnalysis(event).then(analysis=>{if(analysis)repaint();});}
}

// ----- paint ------------------------------------------------------------------
function paint(result){
  latestResult=result;
  latestMarkets=result.markets||[];
  latestEpisodes=result.episodes||latestEpisodes;
  latestRegistry=result.registry||null;
  processConfirmationEvents(result.performance);
  const table=document.getElementById("radarTable");
  if(!table)return;
  const mode=result.mode||"LIVE";
  radarMode=mode;
  paintMode(mode,result);
  const counters=document.getElementById("gardenCounters");
  if(counters)counters.innerHTML=counterTiles(gardenCounters({markets:latestMarkets,episodes:latestEpisodes,mode,registry:latestRegistry}));
  paintStrategyControls();
  const sorted=[...latestMarkets].sort((a,b)=>(b.score||0)-(a.score||0));
  table.innerHTML=sorted.length?marketOverview(sorted.map(market=>marketOverviewRow(market,latestRegistry))):emptyArea(mode==="OFFLINE"?"Engine offline":"No market data",mode==="OFFLINE"?"No market data is shown while the engine is offline.":"The engine returned no markets.");
  const marketCount=document.getElementById("marketCount");if(marketCount)marketCount.textContent=sorted.length?sorted.length+" instruments":"";
  latestCards=new Map();
  lastCards=paintAreas(visibleAreas());
  if(!selectedKey||!selectedRow())selectedKey=defaultSelection(lastCards);
  for(const node of document.querySelectorAll(".gd-card"))node.classList.toggle("is-selected",node.dataset.key===selectedKey);
  paintGarden(lastCards);
  paintAnalyst();
  paintFocus();
  paintConfirmed(latestMarkets,result.performance);
  const now=new Date().toLocaleTimeString();
  document.getElementById("radarUpdated").textContent={LIVE:"Updated "+now,ENGINE_NO_DATA:"No market data · "+now,OFFLINE:"Offline · checked "+now,DEMO:"Simulated · not market data"}[mode];
  const status=document.getElementById("radarEngineStatus");if(status)status.textContent={LIVE:"Live MT5 engine",ENGINE_NO_DATA:"Engine online · MT5 "+String(result.mt5Status||"no data"),OFFLINE:"Engine offline",DEMO:"Demo mode · engine offline"}[mode];
  paintPerformance(result.performance);
  if(pendingAnchor)setTimeout(applyPendingAnchor,0);
}
function paintMode(mode,result){
  const root=document.getElementById("radarRoot"),banner=document.getElementById("radarModeBanner");
  if(root){root.classList.toggle("is-simulated",mode==="DEMO");root.classList.toggle("is-offline",mode==="OFFLINE"||mode==="ENGINE_NO_DATA");root.dataset.mode=mode;}
  const note=document.getElementById("gardenHeroNote");
  if(note)note.textContent=mode==="DEMO"?"Demo mode: every orb here is a simulated fixture, not a real setup and not market data."
    :"Every orb is a real setup from the existing strategy and lifecycle. Execution stays manual — TRADeden never places orders.";
  const eyebrow=document.getElementById("radarEyebrow");
  if(eyebrow)eyebrow.textContent={LIVE:"🌿 The TRADeden Garden · live",ENGINE_NO_DATA:"🌿 The TRADeden Garden · engine online, no market data",OFFLINE:"🌿 The TRADeden Garden · scanner offline",DEMO:"🌿 The TRADeden Garden · simulated, not scanning"}[mode];
  if(!banner)return;
  if(mode==="LIVE"){banner.hidden=true;banner.innerHTML="";return;}
  banner.hidden=false;banner.dataset.mode=mode;
  banner.innerHTML=mode==="DEMO"
    ?'<b>DEMO MODE</b><b>ENGINE OFFLINE</b><b>SIMULATED SETUPS</b><span>Everything below is fixed sample data for UI development. Prices, scores and setups are not current market information. Disable with localStorage th_radar_demo=0.</span>'
    :mode==="OFFLINE"
    ?'<b>ENGINE OFFLINE</b><span>No market data. Start the engine with backend/start_engine.bat (expected at '+esc(getEngineUrl())+'). Retrying every 10 seconds.</span>'
    :'<b>ENGINE ONLINE</b><b>NO MARKET DATA</b><span>MT5 status: '+esc(result.mt5Status||"UNKNOWN")+(result.error?' · '+esc(result.error):'')+'. Check that MetaTrader 5 is open and logged in.</span>';
}
function offlineDetail(mode){return '<div class="gd-analyst-empty"><span aria-hidden="true">⌁</span><b>'+(mode==="OFFLINE"?"Engine offline":"No market data")+'</b><p>'+(mode==="OFFLINE"?"The scanner is not running, so no setups are being evaluated. Nothing on this page reflects the current market.":"The engine is reachable but MT5 returned no markets.")+'</p></div>';}

// ----- confirmation alerts (unchanged behaviour) -------------------------------
function readSeenConfirmationIds(){
  try{const parsed=JSON.parse(localStorage.getItem("tradingHub.confirmationAlerts.seenSetupIds")||"[]");return Array.isArray(parsed)?parsed:[];}catch(_){return [];}
}
function persistSeenConfirmationIds(ids){
  try{localStorage.setItem("tradingHub.confirmationAlerts.seenSetupIds",JSON.stringify(ids.slice(-1000)));}catch(_){}
}
function initializeConfirmationAlertTracker(){
  if(!confirmationAlertTracker)confirmationAlertTracker=createConfirmationAlertTracker({
    initialSetupIds:readSeenConfirmationIds(),startedAt:confirmationAlertSessionStartedAt,onSeenChange:persistSeenConfirmationIds,
  });
}
function processConfirmationEvents(performance){
  initializeConfirmationAlertTracker();
  const events=confirmationAlertTracker.observe(persistedConfirmationEvents(performance));
  dispatchConfirmationAlerts(events,{soundEnabled:confirmationAlertsEnabled,playSound:playConfirmationTone,showNotification:showConfirmationToast});
}
function showConfirmationToast(event){
  const container=document.getElementById("confirmationToast");if(!container)return;
  const setupId=String(event.setup_id||"unknown");
  if(container.querySelector('[data-confirmation-toast="'+esc(setupId)+'"]'))return;
  const direction=event.direction||"Unavailable";
  const setupType=event.setup_type||event.trendline_event||event.setup_family||event.setup||"Unavailable";
  const score=event.score==null?"Unavailable":String(event.score);
  const time=event.confirmed_at?(Number.isNaN(Date.parse(event.confirmed_at))?String(event.confirmed_at):new Date(event.confirmed_at).toLocaleString()):"Unavailable";
  container.hidden=false;
  container.insertAdjacentHTML("beforeend",'<article class="confirmation-toast-card" data-confirmation-toast="'+esc(setupId)+'"><b>🌸 NEW CONFIRMED SETUP</b><strong>'+esc(event.symbol||"Symbol unavailable")+' · '+esc(direction)+'</strong><span>'+esc(setupType)+'</span><span>Score · '+esc(score)+'</span><small>Confirmation time · '+esc(time)+'</small><small class="confirmation-toast-note">Not an entry recommendation.</small></article>');
  const card=container.querySelector('[data-confirmation-toast="'+esc(setupId)+'"]');
  const timer=setTimeout(()=>{card?.remove();confirmationToastTimers.delete(setupId);if(!container.children.length)container.hidden=true;},9000);
  confirmationToastTimers.set(setupId,timer);
}
function getAlertAudioContext(){
  const AudioContextClass=globalThis.AudioContext||globalThis.webkitAudioContext;
  if(!AudioContextClass)return null;
  if(!alertAudioContext)alertAudioContext=new AudioContextClass();
  return alertAudioContext;
}
async function unlockAlertAudio(){
  try{const context=getAlertAudioContext();if(!context)return false;if(context.state==="suspended")await context.resume();return context.state==="running";}catch(_){return false;}
}
async function playConfirmationTone(){
  try{
    const context=getAlertAudioContext();if(!context)return false;
    if(context.state==="suspended")await context.resume();
    if(context.state!=="running")return false;
    const start=Math.max(context.currentTime,nextAlertToneAt);
    nextAlertToneAt=start+CONFIRMATION_CHIME_CONFIG.durationSeconds+0.12;
    return playConfirmationChime(context,start);
  }catch(_){return false;}
}
function bindConfirmationAlertControls(){
  const toggle=document.getElementById("confirmationAlertsToggle"),test=document.getElementById("testConfirmationSound");
  const label=()=>{
    toggle.textContent=confirmationAlertsEnabled?"🔊 Alerts ON":"🔇 Alerts OFF";
    toggle.setAttribute("aria-pressed",String(confirmationAlertsEnabled));
    toggle.setAttribute("aria-label",confirmationAlertsEnabled?"Disable Alerts":"Enable Alerts");
    toggle.title=confirmationAlertsEnabled?"Disable confirmation sound alerts":"Enable Alerts";
  };
  if(toggle){label();toggle.onclick=async()=>{
    if(confirmationAlertsEnabled){confirmationAlertsEnabled=false;}
    else if(await unlockAlertAudio()){confirmationAlertsEnabled=true;}
    label();
  };}
  if(test)test.onclick=()=>{dispatchTestSound(()=>playConfirmationTone());};
}
function paintPerformance(data){const el=document.getElementById("dailyPerformance");if(!el)return;if(!data){el.innerHTML='<div class="macro-empty"><b>Performance unavailable</b><span>Backend performance endpoint did not respond.</span></div>';return;}if(strategyFilter!=="all"){el.innerHTML=strategyPerformanceBlock(strategyPerformance(data,strategyFilter),strategyTag(strategyFilter));return;}const daily=data.daily?.[0]||data.summary||{};const horizons=daily.by_horizon||{};const rows=["15m","1h","4h","24h"].map(h=>{const x=horizons[h]||{};return '<tr><th>'+h+'</th><td>'+Number(x.win||0)+'</td><td>'+Number(x.loss||0)+'</td><td>'+Number(x.pending||0)+'</td><td>'+Number(x.no_hit||0)+'</td><td>'+Number(x.ambiguous||0)+'</td></tr>';}).join("");const h4=horizons["4h"]||{};const wins=Number(h4.win||0),losses=Number(h4.loss||0),denominator=Number(h4.win_rate_denominator??wins+losses);const rate=h4.win_rate;el.innerHTML='<div class="performance-headline"><b>'+wins+'W / '+losses+'L</b><span>4h win rate '+(rate==null?"—":Number(rate).toFixed(1)+"%")+' · denominator '+denominator+' (wins + losses)</span></div><div class="performance-table-wrap"><table class="performance-table"><thead><tr><th>HORIZON</th><th>W</th><th>L</th><th>PENDING</th><th>NO HIT</th><th>AMBIGUOUS</th></tr></thead><tbody>'+rows+'</tbody></table></div><small>Timezone: '+esc(data.timezone||daily.reporting_timezone||"Africa/Nairobi")+' · MarketOutcome records only. NO_HIT and AMBIGUOUS are excluded from win-rate denominator.</small>';}
function paintFundamentals(data){
  const el=document.getElementById("radarFundamentals");if(!el)return;
  if(!data.configured){el.innerHTML='<div class="macro-empty"><b>Macro layer ready</b><span>Connect a Trading Economics API key on the engine to bring live US economic events into the scanner.</span></div>';return;}
  const events=(data.events||[]).filter(e=>String(e.importance||"").toLowerCase()!=="low").slice(0,8);
  el.innerHTML=events.length?events.map(e=>'<div class="macro-event"><span>'+esc(e.date||"")+'</span><b>'+esc(e.event||"Economic event")+'</b><em>'+esc(String(e.importance||""))+'</em></div>').join(""):'<div class="macro-empty"><b>No major events returned</b><span>'+esc(data.status||"LIVE")+'</span></div>';
}

// ----- lifecycle ------------------------------------------------------------------
const EMPTY_EPISODES={current:[],confirmed:[],closed:[]};
async function refreshRadar(isCurrent){
  const [radar,performance,episodes,outcomes]=await Promise.all([getRadar(),getPerformance(),getSetupEpisodes(),getOutcomes()]);
  if(!isCurrent())return;
  latestOutcomes=radar.mode==="LIVE"||radar.mode==="ENGINE_NO_DATA"?(outcomes||latestOutcomes):[];
  // Engine offline or demo: never show previously fetched engine episodes as if current.
  paint({...radar,performance,episodes:radar.mode==="LIVE"||radar.mode==="ENGINE_NO_DATA"?(episodes||latestEpisodes):EMPTY_EPISODES});
}
function disposeGarden(){gardenMountToken++;garden?.dispose();garden=null;}
async function mountGardenVisual(){
  disposeGarden();
  const stage=document.getElementById("gardenStage");if(!stage)return;
  const token=gardenMountToken;
  const controller=await mountGarden(stage,{onSelect:key=>select(key)});
  if(token!==gardenMountToken||!stage.isConnected){controller.dispose();return;}
  garden=controller;
  const note=document.getElementById("gardenModeNote");
  if(note)note.textContent=(controller.kind==="webgl"?"3D garden":"2D garden · "+controller.reason)+(controller.reducedMotion||prefersReducedMotion()?" · reduced motion":"");
  stage.dataset.renderer=controller.kind;
  if(latestResult)paintGarden(lastCards);
}
export async function initMarketRadar(){
  bindConfirmationAlertControls();initializeConfirmationAlertTracker();bindGardenInteractions();
  const visual=mountGardenVisual();
  if(!radarPoller)radarPoller=createPoller({task:refreshRadar,intervalMs:10000});
  const poll=radarPoller.start();
  paintFundamentals(await getFundamentals());
  await Promise.all([poll,visual]);
}
/** Scroll to a Garden section once live content has painted (its height depends on data). */
export function scrollToGardenSection(id){
  pendingAnchor=id;
  if(latestResult&&document.getElementById("growingCards")?.childElementCount)applyPendingAnchor();
}
function applyPendingAnchor(){
  const target=pendingAnchor&&document.getElementById(pendingAnchor);
  pendingAnchor=null;
  if(target)target.scrollIntoView({block:"start"});
}
export function stopMarketRadar(){radarPoller?.stop();disposeGarden();}

