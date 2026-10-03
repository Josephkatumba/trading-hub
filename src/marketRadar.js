// TRADeden Garden — the market radar page controller.
// Data, polling, confirmation alerts and demo/offline handling are unchanged from
// the previous radar; presentation lives in ./garden/* (view models, markup and
// the optional 3D/2D garden visual, which can fail or be disabled independently).
import "./garden/garden.css";
import "./garden/garden-observatory.css";
import "./garden/garden-command.css";
import {engineFetch,getEngineUrl} from "./engine.js";
import {createPoller} from "./radarPolling.mjs";
import {confirmationDisplay} from "./analystPresentation.mjs";
import {setupCountSummary, visibleSetupEntries} from "./radarLayout.mjs";
import {createConfirmationAlertTracker, dispatchConfirmationAlerts, dispatchTestSound, persistedConfirmationEvents} from "./confirmationAlerts.mjs";
import {CONFIRMATION_CHIME_CONFIG, playConfirmationChime} from "./confirmationChime.mjs";
import {analysisObservationId, archiveEntry, archiveSummary, gardenAreas, gardenHeaderModel, constellationLayout, researchModel, setupCardModel} from "./garden/gardenModel.mjs";
import {archivePanel, compactCard, confirmationToastHtml, emptyArea, esc, evaluationPanel, focusPanel, headerStats, headerStrategies, marketWatchAll, priorityWatch, researchPanel, setupCard, stageLegend, strategyFilterBar, strategyLabPanel, strategyPerformanceBlock} from "./garden/gardenCards.mjs";
import {filterByStrategy, matchesStrategy, strategyFilters, strategyPerformance, strategyStatus, strategyTag} from "./strategyModel.mjs";
import {mountGarden, prefersReducedMotion} from "./garden/gardenMount.mjs";
import {evidenceModel, evidencePanel, labReportPanel} from "./garden/strategyLab.mjs";
import {marketWatchGroups, priorityWatchSlots, rankMarkets, trackScanEvents} from "./garden/priorityWatch.mjs";

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
let bloomedExpanded = false;
let historyExpanded = false;
const DEVELOPING_LIMIT = 10;          // compact cards shown before "View all"
const CONFIRMED_LIMIT = 8;
const HISTORY_LIMIT = 8;
let researchOpen = false;             // Market Research drawer for the selected row
let researchReturnFocus = null;
let watchAllOpen = false;             // full Market Watch overlay ("View all")
let watchAllReturnFocus = null;
let latestRanking = [];               // every scanned market in attention order (priorityWatch.mjs)
let scanEvents = null;                // when each live strategy scan last changed while open (priorityWatch.trackScanEvents)
let shownWatchSymbols = null;         // symbols in the 4 slots last paint (null before the first paint)
const headerValues = new Map();       // data-stat -> last shown value (for change transitions)
let archiveFilter = "all";
let strategyFilter = "all";           // "all" or a strategy_id; applies to setups, archive and performance
let latestRegistry = null;            // engine strategy registry (null: offline, trendline assumed)
let labReport = null;                 // /api/market/strategy-lab, fetched only while the Lab is open
let labSelected = "support_resistance";
let labFetchedAt = 0;
let evalReport = null;                // /api/market/evaluation, fetched with the Lab
let evalSelected = "trend_momentum";
const similarCache = new Map();       // setup_id -> {data, state, at}: /api/market/setups/{id}/similar
const SIMILAR_REFRESH_MS = 120000;
const LAB_REFRESH_MS = 60000;
let latestOutcomes = [];
let latestArchive = [];
let selectedKey = null;
let analystCache = new Map();
let latestCards = new Map();          // key -> {row, card}
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
    +'<header class="gd-topbar gd-observatory gd-command-head"><div class="gd-brand"><span class="gd-brand-mark" aria-hidden="true"><i></i></span><div><b>TRAD<span>eden</span></b><small>Market Garden</small></div></div>'
    +'<div class="gd-hmid"><div class="gd-header-live" id="gardenHeaderStrategies"></div></div>'
    +'<div class="gd-hright"><div id="gardenHeaderStats"></div>'
    +'<div class="gd-top-tools"><div class="gd-engine"><i class="gd-status-dot" aria-hidden="true"></i><span id="radarEngineStatus">Connecting engine</span></div><span class="gd-updated" id="radarUpdated">Waiting…</span>'
    +'<div class="confirmation-alert-controls" id="gardenAlerts"><button type="button" id="confirmationAlertsToggle" class="alert-control" aria-pressed="false" title="Enable Alerts">🔇 Alerts OFF</button><button type="button" id="testConfirmationSound" class="alert-test-control">Test sound</button></div></div>'
    +'</div>'
    +'<div id="confirmationToast" class="confirmation-toast" role="status" aria-live="polite" hidden></div></header>'
    +'<section class="gd-command" aria-label="Garden and market watch">'
    +'<section class="gd-world" id="gardenWorld" aria-label="The TRADeden Garden">'
    +'<div class="gd-world-stage"><div class="gd-stage" id="gardenStage"></div><div class="gd-stage-overlay" id="gardenOverlay" hidden></div><div class="gd-focus" id="gardenFocus" role="region" aria-label="Selected market" aria-live="polite" hidden></div>'
    +'<div class="gd-legend">'+stageLegend()+'</div><small class="gd-stage-mode" id="gardenModeNote"></small></div>'
    +'<div class="gd-world-caption"><span class="gd-eyebrow" id="radarEyebrow">The TRADeden Garden</span>'
    +'<p class="gd-hero-note" id="gardenHeroNote">Every node is a real setup from a live strategy and its lifecycle. Execution stays manual — TRADeden never places orders.</p></div></section>'
    +'<section class="gd-panel gd-watch" id="gardenMarkets" aria-label="TRADeden priority watch"><header class="gd-panel-head"><div><h2>TRADeden priority watch</h2><p id="watchSubtitle">Markets demanding attention</p></div><span class="gd-count" id="marketCount"></span></header>'
    +'<div id="radarTable" class="gd-watch-list gd-pw-list" aria-live="polite"></div>'
    +'<footer class="gd-pw-foot"><span id="watchScanned"></span><button type="button" class="gd-link" id="watchViewAll" data-watch-action="all" aria-haspopup="dialog">View all →</button></footer></section>'
    +'</section>'
    +'<div class="gd-strategy-bar" id="strategyFilterBar"></div>'
    +'<div class="gd-main">'
    +area("growing","🌱","Developing","Evidence still accumulating. Select a card for its market research.")
    +area("bloomed","🟢","Confirmed","Passed their strategy's confirmation rules. A confirmation is a historical event: its plan never changes.")
    +'<section class="gd-area gd-area-history" id="area-history"><header class="gd-area-head"><div><h2><span aria-hidden="true">📚</span> Recently closed</h2><p>What happened to the setups TRADeden surfaced. Only confirmed setups can hit a target or stop.</p></div><span class="gd-count" id="historyCount"></span></header><div id="historyCards" class="gd-archive"></div></section>'
    +'</div>'
    +'<div class="gd-research-backdrop" id="gardenResearchBackdrop" data-research-action="close" hidden></div>'
    +'<section class="gd-research" id="gardenResearch" role="dialog" aria-modal="true" aria-labelledby="gardenResearchTitle" tabindex="-1" hidden></section>'
    +'<div class="gd-research-backdrop" id="gardenWatchAllBackdrop" data-watch-action="close" hidden></div>'
    +'<section class="gd-research gd-watch-all" id="gardenWatchAll" role="dialog" aria-modal="true" aria-labelledby="gardenWatchAllTitle" tabindex="-1" hidden></section>'
    +'<section class="gd-panel performance-panel" id="gardenPerformance"><header class="gd-panel-head"><div><h2>📊 Today\'s setup performance</h2><p>Headline uses the 4h market outcome. Other configured horizons remain visible. Trade outcomes are excluded.</p></div></header><div id="dailyPerformance"><div class="macro-empty"><b>Loading performance</b></div></div></section>'
    +'<details class="gd-panel gd-strategy-lab" id="strategyLab"><summary><span>🧪 Strategy Lab</span><span class="historical-expand-hint">Expand</span></summary><p>Registered strategies and their status. Live strategies (Trendline, S/R, Trend/Momentum) each produce their own Garden setups, notifications and outcomes and are measured separately here. Live does not mean proven profitable. Shadow-mode (research) strategies, if any, are reviewed here only and never become Garden setups or alerts.</p><div id="strategyLabBody"></div><div id="strategyLabReport"></div><div id="strategyLabEvidence" aria-live="polite"></div>'
    +'<section class="gd-lab-evaluation"><h4>Historical evaluation · verified outcomes by condition</h4><p class="gd-note">The foundation of TRADeden\'s evaluation layer: what has happened to confirmed setups sharing a recorded condition. Deterministic, per strategy, verified outcomes only. It never creates or changes a setup.</p><div id="strategyLabEvaluation"></div></section></details>'
    +'<details class="gd-panel historical-confirmations" id="historicalConfirmations"><summary><span>📚 Confirmation event archive · today (<b id="historicalConfirmationCount">0</b>)</span><span class="historical-expand-hint">Expand</span></summary><p class="gd-archive-status" id="confirmedArchiveStatus"></p><div id="historicalConfirmationCards" class="gd-grid"></div></details>'
    +'<section class="gd-panel radar-fundamentals"><header class="gd-panel-head"><h2>Macro events that can change the tape</h2><span class="gd-count">US events</span></header><div id="radarFundamentals" class="macro-list"><div class="macro-empty"><b>Loading macro context</b></div></div></section>'
    +'<footer class="gd-method"><p><b>How TRADeden watches:</b> three independent LIVE strategies — Trendline, Support &amp; Resistance and Trend / Momentum — each evaluate every market on MT5 closed bars with deterministic rules. Each keeps its own setups, lifecycle, confirmations and outcomes; one strategy never suppresses or rewrites another\'s setup. A confirmed setup is a historical event: its confirmed plan never changes.</p><p>TRADeden is decision support, not an auto-trading platform. Not an entry recommendation.</p></footer>'
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
// A confirmed setup is explained from its confirmation snapshot, never from a later observation.
const analysisKey=row=>row?.setup_id?row.setup_id+":"+(analysisObservationId(row)||""):null;
// One request per analysis: concurrent callers share the in-flight promise.
// (Caching only on completion let every repaint re-request pending analyses.)
const analysisInFlight=new Map();
function getAnalysis(m){
  if(!m?.setup_id)return Promise.resolve(null);
  const observationId=analysisObservationId(m)||"";const key=m.setup_id+":"+observationId;
  if(analystCache.has(key))return Promise.resolve(analystCache.get(key));
  if(analysisInFlight.has(key))return analysisInFlight.get(key);
  const suffix=observationId?"?observation_id="+encodeURIComponent(observationId):"";
  const request=engineFetch("/api/market/setups/"+encodeURIComponent(m.setup_id)+"/analysis"+suffix)
    .then(data=>{analystCache.set(key,data);return data;},()=>{analystCache.set(key,null);return null;})
    .finally(()=>analysisInFlight.delete(key));
  analysisInFlight.set(key,request);
  return request;
}
async function getSetupEpisodes(){try{return await engineFetch("/api/market/setup-episodes?bucket=all&limit=40&per_strategy=true");}catch(_){return null;}}
async function getOutcomes(){try{const data=await engineFetch("/api/market/outcomes");return Array.isArray(data?.outcomes)?data.outcomes:null;}catch(_){return null;}}

// ----- cards ------------------------------------------------------------------
function cardFor(row,bucket){
  const card=setupCardModel(row,{bucket,analysis:analystCache.get(analysisKey(row))||null,tracked:tracked.has(row?.setup_id),simulated:radarMode==="DEMO"});
  if(card.key)latestCards.set(card.key,{row,card});
  return card;
}
function paintAreas(areas){
  const trackedFirst=(a,b)=>Number(b.tracked)-Number(a.tracked);
  const growing=areas.growing.map(row=>cardFor(row,"growing")).sort(trackedFirst);
  const bloomed=areas.bloomed.map(row=>cardFor(row,"bloomed")).sort(trackedFirst);
  const archive=paintArchive(areas.history);
  const history=areas.history.map((row,index)=>({...cardFor(row,"history"),outcome:archive[index]?.kind||null}));
  const offline=radarMode==="OFFLINE";
  const node=id=>document.getElementById(id);
  const toolbar=(total,expanded,key,limit)=>{const summary=setupCountSummary(total,expanded,limit);return summary?'<div class="gd-toolbar"><span>'+esc(summary)+'</span><button type="button" class="gd-link" data-toggle="'+key+'" aria-expanded="'+expanded+'">'+(expanded?"Show less":"View all "+total)+'</button></div>':"";};
  if(strategyFilter!=="all"&&strategyStatus(strategyFilter,latestRegistry)==="SHADOW"){
    const tag=strategyTag(strategyFilter).tag;
    const text=tag+" runs in shadow mode: its setups are reviewed in the Strategy Lab and never appear in the Garden.";
    for(const id of ["growingCards","bloomedCards"])if(node(id))node(id).innerHTML=emptyArea("Shadow strategy",text);
    for(const [id,text] of [["growingCount","0 developing"],["bloomedCount","0 confirmed"],["historyCount",history.length+" recently closed"]])if(node(id))node(id).textContent=text;
    return {growing:[],bloomed:[],history};
  }
  const developing=growing.filter(card=>!card.watching),seeds=growing.filter(card=>card.watching);
  const seedStrip=seeds.length?'<div class="gd-seeds" aria-label="Watching"><span class="gd-seeds-label">Watching · '+seeds.length+'</span>'+seeds.slice(0,24).map(card=>setupCard(card,{compact:true,selected:card.key===selectedKey})).join("")+(seeds.length>24?'<span class="gd-na">+'+(seeds.length-24)+' more</span>':'')+'</div>':"";
  if(node("growingCards"))node("growingCards").innerHTML=growing.length
    ?toolbar(developing.length,growingExpanded,"growing",DEVELOPING_LIMIT)+visibleSetupEntries(developing,growingExpanded,DEVELOPING_LIMIT).map(card=>compactCard(card,{selected:card.key===selectedKey})).join("")+seedStrip
    :emptyArea(offline?"The garden is not being watched":"Nothing developing right now",offline?"Engine offline — no setups are being evaluated.":"The engine is scanning; no setup is currently developing. No setup is a valid state.");
  if(node("bloomedCards"))node("bloomedCards").innerHTML=bloomed.length
    ?toolbar(bloomed.length,bloomedExpanded,"bloomed",CONFIRMED_LIMIT)+visibleSetupEntries(bloomed,bloomedExpanded,CONFIRMED_LIMIT).map(card=>compactCard(card,{selected:card.key===selectedKey,variant:"confirmed"})).join("")
    :emptyArea("No confirmed setups",offline?"Engine offline.":"No setup currently passes the confirmation rules.");
  if(node("growingCount"))node("growingCount").textContent=developing.length+" developing"+(seeds.length?" · "+seeds.length+" watching":"");
  if(node("bloomedCount"))node("bloomedCount").textContent=bloomed.length+" confirmed";
  if(node("historyCount"))node("historyCount").textContent=history.length+" recently closed";
  return {growing,bloomed,history};
}

// The archive: closed episodes and what happened to them (verified outcomes only).
function confirmationSnapshot(row){
  const id=row?.setup_id,observation=row?.confirmation?.observation_id;
  const plan=row?.confirmed_plan;
  // The backend's confirmed plan IS the confirmation snapshot's levels: no extra request needed.
  if(plan&&plan.observation_id===observation)return {observation_id:plan.observation_id,proposed_entry:plan.entry,proposed_stop_loss:plan.stop_loss,
    proposed_take_profit:plan.take_profit,reference_price:plan.reference_price,invalidation_price:plan.invalidation_price};
  return (confirmedDetailCache.get(id)?.snapshots||[]).find(snapshot=>snapshot.observation_id===observation)||null;
}
function paintArchive(rows){
  const entries=rows.map(row=>archiveEntry(row,latestOutcomes,confirmationSnapshot(row)));
  // R needs the confirmation snapshot's planned levels: load it only for verified hits.
  for(const [index,entry] of entries.entries())if((entry.kind==="target"||entry.kind==="stop")&&!confirmationSnapshot(rows[index]))fetchConfirmedDetail(entry.key,()=>repaintCards());
  latestArchive=entries;
  const node=document.getElementById("historyCards");
  if(node)node.innerHTML=entries.length?archivePanel(entries,archiveSummary(entries),{filter:archiveFilter,selectedKey,expanded:historyExpanded,limit:HISTORY_LIMIT})
    :emptyArea("No closed setups yet","Closed, expired and invalidated setups will rest here with what happened to them.");
  return entries;
}

function selectedRow(){
  if(!selectedKey)return null;
  const entry=latestCards.get(selectedKey);
  if(entry)return entry.row;
  return latestMarkets.find(m=>m.setup_id===selectedKey||"mkt-"+m.symbol===selectedKey)||null;
}
// ----- Market Research drawer ---------------------------------------------------
function paintResearch(){
  const panel=document.getElementById("gardenResearch"),backdrop=document.getElementById("gardenResearchBackdrop");if(!panel)return;
  const row=researchOpen?selectedRow():null;
  panel.hidden=!row;if(backdrop)backdrop.hidden=!row;
  syncOverlayLock();
  if(!row){panel.innerHTML="";return;}
  const key=analysisKey(row);
  const analysis=key?analystCache.get(key):null;
  const archive=latestArchive.find(entry=>entry.key&&entry.key===row.setup_id)||null;
  const similar=row.setup_id?similarCache.get(row.setup_id):null;
  const scroll=panel.scrollTop;          // repaints every scan must not jump the reader back to the top
  panel.innerHTML=researchPanel(researchModel(row,{analysis:analysis||null,archive,simulated:radarMode==="DEMO",market:latestMarkets.find(m=>m.symbol===row.symbol)||null}),
    {loading:Boolean(key)&&analysis===undefined,similar:similar?.data||null,similarState:similar?.state||"loading",tracked:tracked.has(row.setup_id)});
  panel.scrollTop=scroll;
  if(key&&analysis===undefined)getAnalysis(row).then(()=>{if(analysisKey(selectedRow())===key){paintResearch();paintFocus();}});
  if(row.setup_id&&radarMode!=="DEMO"&&radarMode!=="OFFLINE")fetchSimilar(row.setup_id);
}
function openResearch(key){
  if(!key)return;
  if(!researchOpen)researchReturnFocus=document.activeElement;
  select(key);
  if(!selectedRow())return;
  researchOpen=true;
  paintResearch();
  document.getElementById("gardenResearch")?.focus({preventScroll:true});
}
function closeResearch(){
  if(!researchOpen)return;
  researchOpen=false;
  paintResearch();
  const back=researchReturnFocus;researchReturnFocus=null;
  if(back?.isConnected)back.focus({preventScroll:true});
}
// Historical evidence for the selected setup: fetched on selection only, cached, refreshed rarely.
function fetchSimilar(setupId){
  const cached=similarCache.get(setupId);
  if(cached&&(cached.state==="loading"||Date.now()-cached.at<SIMILAR_REFRESH_MS))return;
  similarCache.set(setupId,{data:cached?.data||null,state:cached?.data?"ready":"loading",at:Date.now()});
  engineFetch("/api/market/setups/"+encodeURIComponent(setupId)+"/similar")
    .then(data=>similarCache.set(setupId,{data,state:"ready",at:Date.now()}),()=>similarCache.set(setupId,{data:null,state:"error",at:Date.now()}))
    .finally(()=>{if(researchOpen&&selectedRow()?.setup_id===setupId)paintResearch();});
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
  const lab=document.getElementById("strategyLabBody");if(lab)lab.innerHTML=strategyLabPanel(latestRegistry,{markets:latestMarkets,performance:latestResult?.performance||null});
}
// ----- Strategy Lab measurements (on demand, never part of the scan) ----------
function paintLab(){
  const node=document.getElementById("strategyLabReport");if(node)node.innerHTML=labReportPanel(labReport,{selected:labSelected});
  const evaluation=document.getElementById("strategyLabEvaluation");if(evaluation)evaluation.innerHTML=evaluationPanel(evalReport,{selected:evalSelected});
}
async function refreshLab(force=false){
  const panel=document.getElementById("strategyLab");
  if(!panel?.open||(!force&&Date.now()-labFetchedAt<LAB_REFRESH_MS))return;
  labFetchedAt=Date.now();
  const [lab,evaluation]=await Promise.all([engineFetch("/api/market/strategy-lab").catch(()=>null),engineFetch("/api/market/evaluation").catch(()=>null)]);
  labReport=lab;evalReport=evaluation;
  paintLab();
}
async function inspectLabSetup(setupId){
  const node=document.getElementById("strategyLabEvidence");if(!node)return;
  node.innerHTML='<p class="gd-na">Loading recorded evidence…</p>';
  try{node.innerHTML=evidencePanel(evidenceModel(await engineFetch("/api/market/setups/"+encodeURIComponent(setupId))));}
  catch(_){node.innerHTML='<p class="gd-na">Evidence unavailable (engine offline).</p>';}
}
function repaintCards(){
  if(!latestResult)return;
  latestCards=new Map();
  lastCards=paintAreas(visibleAreas());
  paintGarden(lastCards);
}
function markSelection(){
  const key=selectedKey,symbol=selectedRow()?.symbol||null;
  for(const node of document.querySelectorAll("#radarRoot .gd-card,#radarRoot .gd-mini,#radarRoot .gd-seed"))node.classList.toggle("is-selected",Boolean(key)&&node.dataset.key===key);
  for(const node of document.querySelectorAll("#radarRoot .gd-card"))node.setAttribute("aria-selected",String(Boolean(key)&&node.dataset.key===key));
  for(const node of document.querySelectorAll("[data-archive-key]"))node.classList.toggle("is-selected",Boolean(key)&&node.dataset.archiveKey===key);
  for(const node of document.querySelectorAll("#radarRoot .gd-pw-row")){const on=Boolean(symbol)&&node.dataset.symbol===symbol;node.classList.toggle("is-selected",on);node.setAttribute("aria-pressed",String(on));}
}
function select(key,{scrollTo=null}={}){
  selectedKey=key||null;
  markSelection();
  paintFocus();
  if(researchOpen)paintResearch();
  garden?.select(selectedKey,pinLabel());
  const target=scrollTo&&document.getElementById(scrollTo);
  if(target)target.scrollIntoView({behavior:prefersReducedMotion()?"auto":"smooth",block:"start"});
}
const stackedLayout=()=>window.innerWidth<1100;
// A market row selects the setup that gives the market its priority (its lead), else
// the market's most advanced live setup, else the market itself.
function selectMarket(symbol,leadKey,{scrollTo=null}={}){
  const m=latestMarkets.find(x=>x.symbol===symbol);if(!m)return;
  const live=[...lastCards.bloomed,...lastCards.growing].find(c=>c.symbol===symbol);
  const key=leadKey&&latestCards.has(leadKey)?leadKey:live?live.key:(m.setup_id||"mkt-"+m.symbol);
  select(key,{scrollTo});
}
function syncOverlayLock(){document.body.classList.toggle("gd-research-open",researchOpen||watchAllOpen);}

// ----- Priority Watch (4 slots) and the full Market Watch -------------------------
function paintPriorityWatch(mode){
  const table=document.getElementById("radarTable");if(!table)return;
  const areas=gardenAreas(latestEpisodes,latestMarkets,{registry:latestRegistry});
  const episodes=[...(latestEpisodes.current||[]),...(latestEpisodes.confirmed||[]),...(latestEpisodes.closed||[])];
  // Scan changes are only dated from live data; offline/demo never creates attention events.
  if(mode==="LIVE")scanEvents=trackScanEvents(scanEvents,latestMarkets,latestRegistry);
  try{latestRanking=rankMarkets(latestMarkets,[...areas.bloomed,...areas.growing],latestRegistry,{episodes,scanEvents:mode==="LIVE"?scanEvents:null});}
  catch(error){console.warn("TRADeden: priority ranking failed; showing markets in scan order",error);latestRanking=rankMarkets(latestMarkets,[],null);}
  const slots=priorityWatchSlots(latestRanking);
  const shown=[...slots.priority,...(slots.core?[slots.core]:[])].map(entry=>entry.symbol);
  const entering=new Set(shownWatchSymbols?shown.filter(symbol=>!shownWatchSymbols.has(symbol)):[]);
  shownWatchSymbols=new Set(shown);
  const total=latestMarkets.length;
  table.innerHTML=total?priorityWatch(slots,{selectedSymbol:selectedRow()?.symbol||null,entering})
    :emptyArea(mode==="OFFLINE"?"Engine offline":"No market data",mode==="OFFLINE"?"No market data is shown while the engine is offline.":"The engine returned no markets.");
  const text=(id,value)=>{const node=document.getElementById(id);if(node)node.textContent=value;};
  text("watchSubtitle",total?shown.length+" markets demanding attention":"Markets demanding attention");
  text("marketCount",total?total+" scanned":"");
  text("watchScanned",total?total+" scanned":"");
  const all=document.getElementById("watchViewAll");if(all){all.hidden=!total;all.textContent="View all "+total+" →";}
  if(watchAllOpen)paintWatchAll();
}
function paintWatchAll(){
  const panel=document.getElementById("gardenWatchAll"),backdrop=document.getElementById("gardenWatchAllBackdrop");if(!panel)return;
  panel.hidden=!watchAllOpen;if(backdrop)backdrop.hidden=!watchAllOpen;
  syncOverlayLock();
  if(!watchAllOpen){panel.innerHTML="";return;}
  const scroll=panel.scrollTop;
  panel.innerHTML=marketWatchAll(marketWatchGroups(latestRanking),{total:latestMarkets.length,selectedSymbol:selectedRow()?.symbol||null});
  panel.scrollTop=scroll;
}
function openWatchAll(){
  if(researchOpen)closeResearch();
  watchAllReturnFocus=document.activeElement;
  watchAllOpen=true;
  paintWatchAll();
  document.getElementById("gardenWatchAll")?.focus({preventScroll:true});
}
function closeWatchAll({restoreFocus=true}={}){
  if(!watchAllOpen)return;
  watchAllOpen=false;
  paintWatchAll();
  const back=watchAllReturnFocus;watchAllReturnFocus=null;
  if(restoreFocus&&back?.isConnected)back.focus({preventScroll:true});
}
function bindGardenInteractions(){
  const root=document.getElementById("radarRoot");if(!root)return;
  root.onclick=event=>{
    const watchAction=event.target.closest("[data-watch-action]")?.dataset.watchAction;
    if(watchAction==="all"){openWatchAll();return;}
    if(watchAction==="close"){closeWatchAll();return;}
    const researchAction=event.target.closest("[data-research-action]")?.dataset.researchAction;
    if(researchAction==="close"){closeResearch();return;}
    if(researchAction==="track"){const id=selectedRow()?.setup_id;if(id){if(tracked.has(id))tracked.delete(id);else tracked.add(id);writeTracked(tracked);repaintCards();paintResearch();}return;}
    if(event.target.closest("#gardenResearch"))return;      // reading inside the drawer never changes the selection
    const focusAction=event.target.closest("[data-focus-action]")?.dataset.focusAction;
    if(focusAction==="research"||focusAction==="view-analysis"){openResearch(selectedKey);return;}
    if(focusAction==="close"){select(null);return;}
    if(focusAction==="view-setup"){
      const target=[...document.querySelectorAll(".gd-mini[data-key],.gd-seed[data-key],[data-archive-key]")].find(node=>(node.dataset.key||node.dataset.archiveKey)===selectedKey);
      if(target){target.scrollIntoView({behavior:prefersReducedMotion()?"auto":"smooth",block:"center"});target.classList.remove("is-flash");void target.offsetWidth;target.classList.add("is-flash");}
      return;
    }
    const toggle=event.target.closest("[data-toggle]");
    if(toggle){const which=toggle.dataset.toggle;if(which==="growing")growingExpanded=!growingExpanded;else if(which==="bloomed")bloomedExpanded=!bloomedExpanded;else historyExpanded=!historyExpanded;repaintCards();return;}
    const mini=event.target.closest(".gd-mini");
    if(mini){openResearch(mini.dataset.key);return;}
    const evalTab=event.target.closest("[data-eval-strategy]");
    if(evalTab){evalSelected=evalTab.dataset.evalStrategy;paintLab();return;}
    const seed=event.target.closest("[data-seed]");
    if(seed){select(seed.dataset.key);return;}
    const labTab=event.target.closest("[data-lab-strategy]");
    if(labTab){labSelected=labTab.dataset.labStrategy;paintLab();return;}
    const labInspect=event.target.closest("[data-lab-inspect]");
    if(labInspect){inspectLabSetup(labInspect.dataset.labInspect);return;}
    const strategyButton=event.target.closest("[data-strategy-filter]");
    if(strategyButton){strategyFilter=strategyButton.dataset.strategyFilter;historyExpanded=false;growingExpanded=false;bloomedExpanded=false;paintStrategyControls();repaintCards();if(latestResult){paintConfirmed(latestMarkets,latestResult.performance);paintPerformance(latestResult.performance);}return;}
    const filterButton=event.target.closest("[data-archive-filter]");
    if(filterButton){archiveFilter=filterButton.dataset.archiveFilter;historyExpanded=false;repaintCards();return;}
    const archiveRow=event.target.closest("[data-archive-key]");
    if(archiveRow){openResearch(archiveRow.dataset.archiveKey);return;}
    // Market Watch: focus the market's most advanced live setup in the Garden (or the bare market).
    const marketRow=event.target.closest(".gd-market-row");
    if(marketRow){
      const fromFullView=Boolean(marketRow.closest("#gardenWatchAll"));
      if(fromFullView)closeWatchAll({restoreFocus:false});
      selectMarket(marketRow.dataset.symbol,marketRow.dataset.key,{scrollTo:stackedLayout()||fromFullView?"gardenWorld":null});
      return;
    }
    const card=event.target.closest(".gd-card");if(!card)return;
    // Full setup cards remain in the confirmation event archive ("archive-<setup_id>").
    const key=card.dataset.key,action=event.target.closest("[data-action]")?.dataset.action;
    const setupKey=card.dataset.setupId||key;
    if(action==="track"){const id=card.dataset.setupId;if(id){if(tracked.has(id))tracked.delete(id);else tracked.add(id);writeTracked(tracked);repaintCards();}return;}
    if(action==="view-setup"){select(setupKey,{scrollTo:"gardenWorld"});return;}
    openResearch(setupKey);
  };
  const lab=document.getElementById("strategyLab");if(lab)lab.ontoggle=()=>{if(lab.open)refreshLab(true);};
  root.onkeydown=event=>{
    if(event.key==="Escape"&&researchOpen){event.preventDefault();closeResearch();return;}
    if(event.key==="Escape"&&watchAllOpen){event.preventDefault();closeWatchAll();return;}
    const card=event.target.closest?.(".gd-card,.gd-mini");
    if(card&&event.target===card&&(event.key==="Enter"||event.key===" ")){event.preventDefault();openResearch(card.classList.contains("gd-mini")?card.dataset.key:(card.dataset.setupId||card.dataset.key));}
  };
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
  if(!document.getElementById("radarTable"))return;
  const mode=result.mode||"LIVE";
  radarMode=mode;
  paintMode(mode,result);
  paintHeader(gardenHeaderModel({markets:latestMarkets,episodes:latestEpisodes,mode,registry:latestRegistry,lastScan:result.timestamp||null}));
  paintStrategyControls();
  latestCards=new Map();
  lastCards=paintAreas(visibleAreas());
  // Nothing is auto-selected: the overlay appears only once the trader picks a market or node.
  if(selectedKey&&!selectedRow()){selectedKey=null;researchOpen=false;}
  paintPriorityWatch(mode);
  markSelection();
  paintGarden(lastCards);
  paintFocus();
  paintResearch();
  paintConfirmed(latestMarkets,result.performance);
  const now=new Date().toLocaleTimeString();
  document.getElementById("radarUpdated").textContent={LIVE:"Updated "+now,ENGINE_NO_DATA:"No market data · "+now,OFFLINE:"Offline · checked "+now,DEMO:"Simulated · not market data"}[mode];
  const status=document.getElementById("radarEngineStatus");if(status)status.textContent={LIVE:"Live MT5 engine",ENGINE_NO_DATA:"Engine online · MT5 "+String(result.mt5Status||"no data"),OFFLINE:"Engine offline",DEMO:"Demo mode · engine offline"}[mode];
  paintPerformance(result.performance);
  refreshLab();
  if(pendingAnchor)setTimeout(applyPendingAnchor,0);
}
// Header numbers: repainted each scan; a value that changed gets a brief transition.
function paintHeader(model){
  const strategies=document.getElementById("gardenHeaderStrategies"),stats=document.getElementById("gardenHeaderStats");
  if(strategies)strategies.innerHTML=headerStrategies(model);
  if(stats)stats.innerHTML=headerStats(model);
  for(const node of document.querySelectorAll("#radarRoot .gd-command-head [data-stat]")){
    const key=node.dataset.stat,value=node.textContent;
    if(headerValues.has(key)&&headerValues.get(key)!==value)node.classList.add("is-changed");
    headerValues.set(key,value);
  }
}
function paintMode(mode,result){
  const root=document.getElementById("radarRoot"),banner=document.getElementById("radarModeBanner");
  if(root){root.classList.toggle("is-simulated",mode==="DEMO");root.classList.toggle("is-offline",mode==="OFFLINE"||mode==="ENGINE_NO_DATA");root.dataset.mode=mode;}
  const note=document.getElementById("gardenHeroNote");
  if(note)note.textContent=mode==="DEMO"?"Demo mode: every node here is a simulated fixture, not a real setup and not market data."
    :"Every node is a real setup from a live strategy and its lifecycle. Execution stays manual — TRADeden never places orders.";
  const eyebrow=document.getElementById("radarEyebrow");
  if(eyebrow)eyebrow.textContent={LIVE:"The TRADeden Garden · live",ENGINE_NO_DATA:"The TRADeden Garden · engine online, no market data",OFFLINE:"The TRADeden Garden · scanner offline",DEMO:"The TRADeden Garden · simulated, not scanning"}[mode];
  if(!banner)return;
  if(mode==="LIVE"){banner.hidden=true;banner.innerHTML="";return;}
  banner.hidden=false;banner.dataset.mode=mode;
  banner.innerHTML=mode==="DEMO"
    ?'<b>DEMO MODE</b><b>ENGINE OFFLINE</b><b>SIMULATED SETUPS</b><span>Everything below is fixed sample data for UI development. Prices, scores and setups are not current market information. Disable with localStorage th_radar_demo=0.</span>'
    :mode==="OFFLINE"
    ?'<b>ENGINE OFFLINE</b><span>No market data. Start the engine with backend/start_engine.bat (expected at '+esc(getEngineUrl())+'). Retrying every 10 seconds.</span>'
    :'<b>ENGINE ONLINE</b><b>NO MARKET DATA</b><span>MT5 status: '+esc(result.mt5Status||"UNKNOWN")+(result.error?' · '+esc(result.error):'')+'. Check that MetaTrader 5 is open and logged in.</span>';
}

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
  container.hidden=false;
  container.insertAdjacentHTML("beforeend",confirmationToastHtml(event));
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
function paintPerformance(data){const el=document.getElementById("dailyPerformance");if(!el)return;if(!data){el.innerHTML='<div class="macro-empty"><b>Performance unavailable</b><span>Backend performance endpoint did not respond.</span></div>';return;}if(strategyFilter!=="all"){el.innerHTML=strategyPerformanceBlock(strategyPerformance(data,strategyFilter),strategyTag(strategyFilter),{shadow:strategyStatus(strategyFilter,latestRegistry)==="SHADOW"});return;}const daily=data.daily?.[0]||data.summary||{};const horizons=daily.by_horizon||{};const rows=["15m","1h","4h","24h"].map(h=>{const x=horizons[h]||{};return '<tr><th>'+h+'</th><td>'+Number(x.win||0)+'</td><td>'+Number(x.loss||0)+'</td><td>'+Number(x.pending||0)+'</td><td>'+Number(x.no_hit||0)+'</td><td>'+Number(x.ambiguous||0)+'</td></tr>';}).join("");const h4=horizons["4h"]||{};const wins=Number(h4.win||0),losses=Number(h4.loss||0),denominator=Number(h4.win_rate_denominator??wins+losses);const rate=h4.win_rate;el.innerHTML='<div class="performance-headline"><b>'+wins+'W / '+losses+'L</b><span><b class="gd-combined">ALL LIVE STRATEGIES COMBINED</b> Select a strategy for its own results · 4h win rate '+(rate==null?"—":Number(rate).toFixed(1)+"%")+' · denominator '+denominator+' (wins + losses)</span></div><div class="performance-table-wrap"><table class="performance-table"><thead><tr><th>HORIZON</th><th>W</th><th>L</th><th>PENDING</th><th>NO HIT</th><th>AMBIGUOUS</th></tr></thead><tbody>'+rows+'</tbody></table></div><small>Timezone: '+esc(data.timezone||daily.reporting_timezone||"Africa/Nairobi")+' · MarketOutcome records only. NO_HIT and AMBIGUOUS are excluded from win-rate denominator.</small>';}
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
export function stopMarketRadar(){radarPoller?.stop();disposeGarden();researchOpen=false;watchAllOpen=false;shownWatchSymbols=null;scanEvents=null;document.body.classList.remove("gd-research-open");}

