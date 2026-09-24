import {engineFetch,getEngineUrl} from "./engine.js";
import {createPoller} from "./radarPolling.mjs";
import {confirmationDisplay, freshnessLabel, renderAnalystEvidence} from "./analystPresentation.mjs";
import {currentWatchSetups, partitionConfirmations, partitionSetupEpisodes, setupCountSummary, visibleSetupEntries} from "./radarLayout.mjs";
import {createConfirmationAlertTracker, dispatchConfirmationAlerts, dispatchTestSound, persistedConfirmationEvents} from "./confirmationAlerts.mjs";
import {CONFIRMATION_CHIME_CONFIG, playConfirmationChime} from "./confirmationChime.mjs";

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

let radarPoller = null;
let latestMarkets = [];
let latestEpisodes = {current:[],confirmed:[],closed:[]};
let watchExpanded = false;
let currentConfirmedExpanded = false;
let selectedMarket = null;
let analystCache = new Map();
let confirmationAlertsEnabled = false;
let confirmationAlertTracker = null;
let alertAudioContext = null;
let nextAlertToneAt = 0;
const confirmationAlertSessionStartedAt = Date.now();
const confirmationToastTimers = new Map();
const confirmedDetailCache = new Map();
const confirmedDetailPending = new Set();
const esc = s => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const stateClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-");
const biasClass = s => String(s||"").toLowerCase().replace(/\s+/g,"-").replace(/\//g,"-");
const fmt = (n,d=4) => Number(n||0).toLocaleString(undefined,{maximumFractionDigits:d});

function actionClass(action){return String(action||"WAIT").toLowerCase().replace(/\s+/g,"-");}
function actionIcon(action){return String(action||"WAIT").toUpperCase()==="BUY"?"↗":String(action||"WAIT").toUpperCase()==="SELL"?"↘":"•";}

function scoreBars(m){
  const b=m.score_breakdown||{};
  const max={trendline:20,structure:15,support_resistance:20,price_action:10,session:5,momentum:10,higher_timeframe:10};
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
  const entry=Number(m.entry||price);
  const stop=Number(m.stop_loss);
  const target=Number(m.take_profit);
  const span=Math.max(
    Math.abs(high-low),
    Math.abs(price)*0.002,
    Number.isFinite(stop)?Math.abs(entry-stop):0,
    Number.isFinite(target)?Math.abs(target-entry):0,
    0.0001
  );
  const levels=[high,low,key,entry];
  if(Number.isFinite(stop))levels.push(stop);
  if(Number.isFinite(target))levels.push(target);
  const min=Math.min(...levels)-span*.25;
  const max=Math.max(...levels)+span*.25;
  const y=v=>Math.max(3,Math.min(97,((max-v)/(max-min))*100));
  const pos=v=>y(v).toFixed(1);
  const priceY=pos(price), highY=pos(high), lowY=pos(low), keyY=pos(key);
  const entryY=pos(entry);
  const stopY=Number.isFinite(stop)?pos(stop):null;
  const targetY=Number.isFinite(target)?pos(target):null;
  const action=String(m.action||"WAIT").toUpperCase();
  const direction=String(m.direction||"").toUpperCase();
  const state=String(m.state||"WATCHING").toUpperCase();
  const accent=action.includes("BUY")||direction==="LONG"?"buy":action.includes("SELL")||direction==="SHORT"?"sell":"wait";
  const tradePlan=["DEVELOPING","CONFIRMING"].includes(state)&&Number.isFinite(stop)&&Number.isFinite(target);
  const rr=m.rr!=null?Number(m.rr):null;
  return '<div class="live-price-map">'
    +'<div class="map-header"><div><span class="kicker">SETUP MAP</span><b>Live trade geometry · structure → risk → target</b></div><span class="map-live"><i class="live-dot"></i>LIVE</span></div>'
    +'<div class="map-canvas">'
    +'<div class="map-grid"><i></i><i></i><i></i><i></i><i></i></div>'
    +'<div class="map-zone london" style="top:'+highY+'%;height:'+Math.max(8,lowY-highY)+'%"><span>LONDON RANGE</span></div>'
    +'<div class="map-line key" style="top:'+keyY+'%"><span>KEY LEVEL · '+fmt(key,4)+'</span></div>'
    +(tradePlan?'<div class="map-line target" style="top:'+targetY+'%"><span>TAKE PROFIT · '+fmt(target,4)+'</span></div>':'')
    +(tradePlan?'<div class="map-line stop" style="top:'+stopY+'%"><span>STOP LOSS · '+fmt(stop,4)+'</span></div>':'')
    +'<div class="map-line entry '+accent+'" style="top:'+entryY+'%"><span>ENTRY · '+fmt(entry,4)+'</span></div>'
    +'<div class="map-line price '+accent+'" style="top:'+priceY+'%"><span>LIVE · '+fmt(price,4)+'</span></div>'
    +'<div class="map-node high" style="top:'+highY+'%"><span>HIGH</span></div>'
    +'<div class="map-node low" style="top:'+lowY+'%"><span>LOW</span></div>'
    +'<div class="map-axis"><span>'+fmt(max,4)+'</span><span>'+fmt((max+min)/2,4)+'</span><span>'+fmt(min,4)+'</span></div>'
    +'</div>'
    +'<div class="map-plan">'
    +'<div><span>ENTRY</span><b>'+(tradePlan?fmt(entry,4):"WAIT")+'</b></div>'
    +'<div class="risk"><span>'+(state==="DEVELOPING"?"PROVISIONAL STOP":"STOP")+'</span><b>'+(tradePlan?fmt(stop,4):"WAIT")+'</b></div>'
    +'<div class="reward"><span>'+(state==="DEVELOPING"?"PROVISIONAL TARGET":"TARGET")+'</span><b>'+(tradePlan?fmt(target,4):"WAIT")+'</b></div>'
    +'<div><span>R:R</span><b>'+(rr!=null&&Number.isFinite(rr)?rr.toFixed(2)+"R":"—")+'</b></div>'
    +'</div>'
    +'<div class="map-footer"><span><i class="dot entry"></i>Entry</span><span><i class="dot level"></i>Key level</span><span><i class="dot range"></i>London range</span><span><i class="dot danger"></i>Stop</span><span><i class="dot target"></i>Target</span></div>'
    +'</div>';
}
function lifecycle(m){
  const state=String(m.state||"WATCHING").toUpperCase();
  const stage=String(m.stage||"").toUpperCase();
  const setup=String(m.setup||"").toUpperCase();
  const action=String(m.action||"WAIT").toUpperCase();
  const text=(m.reason||"")+" "+(m.insight||"");
  const steps=[
    ["HTF BIAS",!!m.higher_timeframe_bias],
    ["PRICE ACTION",/candle|rejection|displacement|engulf|structure|price action/i.test(text)||!!m.price_action],
    ["TRENDLINE",!!m.trendline_gate||/TRENDLINE|BREAK|REVERSAL|TEST/i.test(stage+setup)],
    ["S/R",!!m.nearest_level||/support|resistance|level/i.test(text)],
    ["CONFIRM",state==="CONFIRMING"]
  ];
  return '<div class="setup-lifecycle setup-lifecycle-five">'+steps.map((s,i)=>'<div class="'+(s[1]?"done":"")+'"><span class="life-index">0'+(i+1)+'</span><b>'+s[0]+'</b><i></i></div>').join("")+'</div>';
}
function analysisLens(m){
  const setup=String(m.setup||"Trendline setup");
  const htf=m.higher_timeframe_bias||"Awaiting HTF read";
  const pa=m.price_action||m.price_action_state||"Waiting for candle/structure confirmation";
  const trend=m.trendline_state||m.trendline||m.stage||"Monitoring";
  const sr=m.sr_context||m.nearest_level_type||"Support / resistance scan";
  const crt=m.crt_context||"Context scan";
  return '<div class="analysis-lens">'
    +'<div class="analysis-lens-head"><div><span class="kicker">MULTI-LENS MARKET READ</span><h3>One market · five evidence layers</h3></div><span class="lens-badge">'+esc(setup)+'</span></div>'
    +'<div class="lens-grid">'
    +'<div class="lens-card"><span>01 · TOP-DOWN</span><b>'+esc(htf)+'</b><small>H1 / higher-timeframe context</small></div>'
    +'<div class="lens-card"><span>02 · PRICE ACTION</span><b>'+esc(pa)+'</b><small>Reaction, displacement and structure</small></div>'
    +'<div class="lens-card"><span>03 · TRENDLINE</span><b>'+esc(trend)+'</b><small>Break, test or reversal state</small></div>'
    +'<div class="lens-card"><span>04 · SUPPORT / RESISTANCE</span><b>'+esc(sr)+'</b><small>Key level interaction</small></div>'
    +'<div class="lens-card crt"><span>05 · CRT CONTEXT</span><b>'+esc(crt)+'</b><small>Range/candle context, not a standalone signal</small></div>'
    +'</div></div>';
}

function renderDetail(m, analysis=null){
  if(!m) return '<div class="radar-empty"><div class="radar-empty-orb">⌁</div><b>No active setup</b><p>The scanner is waiting for a clean directional sequence. No trade is a valid state.</p></div>';
  const london=(m.london_high!=null&&m.london_low!=null) ? '<div><span>LONDON RANGE</span><b>'+fmt(m.london_low,2)+' — '+fmt(m.london_high,2)+'</b></div>' : "";
  const key=m.nearest_level ? '<div><span>KEY LEVEL</span><b>'+fmt(m.nearest_level,4)+' · '+esc(m.nearest_level_type||"LEVEL")+'</b></div>' : "";
  const action=String(m.action||"WAIT").toUpperCase();
  const riskContext=analysis?.risk_context||{};
  const risk=(riskContext.invalidation??riskContext.stop_loss??m.stop_loss)!=null?fmt(riskContext.invalidation??riskContext.stop_loss??m.stop_loss,2):"Not calculated";
  const reward=(riskContext.take_profit??m.take_profit)!=null?fmt(riskContext.take_profit??m.take_profit,2):"Not calculated";
  const quality=analysis?.data_quality||m.data_quality||{};
  return '<div class="radar-detail">'
    +'<div class="radar-detail-top"><div><span class="kicker">'+(m.setup_id?'SETUP '+esc(m.setup_id):'DEMO / UNTRACKED SETUP')+' · '+esc(m.lifecycle_state||m.state||"UNKNOWN")+'</span><h2>'+esc(m.symbol)+'</h2><p>'+esc(m.stage||"NO SETUP")+' · '+esc(m.session||"Session unknown")+' · '+esc(m.setup||"Trendline setup")+'</p><small>Observed '+esc(m.observed_at||m.timestamp||"time unavailable")+' · Source '+esc(m.source|| (m.setup_id?"MT5":"Demo"))+' · DATA '+esc(quality.status||"QUALITY UNKNOWN")+' · '+esc(freshnessLabel(quality,m.data_freshness))+'</small></div><div class="radar-big-score"><strong>'+Number(m.score||0)+'</strong><small>/100</small></div></div>'
    +'<div class="live-command-head"><div class="live-verdict '+actionClass(action)+'"><span class="action-icon">'+actionIcon(action)+'</span><div><small>ENGINE VERDICT</small><b>'+esc(action)+'</b><em>'+esc(m.state||"WATCHING")+'</em></div></div><div class="live-thesis"><span>ONE-LINE THESIS</span><b>'+esc(m.insight||m.reason||"Waiting for more market structure.")+'</b></div></div>'
    +setupMap(m)
    +analysisLens(m)
    +'<div class="live-intel-grid"><div class="live-intel-copy"><span class="kicker">DETERMINISTIC SETUP ANALYST · NO LLM</span><p>'+esc(analysis?.summary||m.insight||m.reason||"Waiting for more market structure.")+'</p>'+(analysis?renderAnalystEvidence(analysis)+(quality.flags?.includes("FUTURE_SOURCE_TIMESTAMP")?'<div class="analyst-time-warning">Source timestamp is ahead of observation time. MT5 source-time interpretation is unverified; freshness must not be trusted.</div>':''):'<div class="ai-action-note"><span>NEXT OBSERVATION</span><b>'+esc(m.trigger||"Wait for a clean setup.")+'</b></div>')+'</div><div><span class="kicker">SETUP LIFECYCLE</span>'+lifecycle(m)+'</div></div>'
    +'<div class="radar-level-strip"><div><span>LIVE PRICE</span><b>'+fmt(m.price)+'</b></div><div><span>INVALIDATION / STOP</span><b>'+risk+'</b></div><div><span>TARGET</span><b>'+reward+'</b></div></div>'
    +'<div class="radar-checks"><div><span>BIAS</span><b>'+esc(m.market_bias||"—")+'</b></div><div><span>MOMENTUM</span><b>'+esc(m.momentum||"—")+' · RSI '+(m.rsi!=null?Number(m.rsi).toFixed(0):"—")+'</b></div><div><span>H1 BIAS</span><b>'+esc(m.higher_timeframe_bias||"—")+'</b></div><div><span>STRUCTURE</span><b>'+esc(m.structure||"—")+'</b></div><div><span>SPREAD</span><b>'+fmt(m.spread,3)+'</b></div>'+london+key+'</div>'
    +'<div class="radar-reason"><span>WHY THE ENGINE SAYS THIS</span><p>'+esc(m.reason||"No clean sequence detected.")+'</p></div>'
    +'<div class="score-breakdown"><div class="kicker">CONFLUENCE MODEL</div>'+scoreBars(m)+'</div>'
    +'<div class="radar-warning"><b>DISCIPLINE GATE</b><span>Potential setup only. Trading Hub observes and explains. Your confirmation rules remain the final gate before execution.</span></div>'
    +'</div>';
}

export function renderMarketRadar(){
  return '<div id="radarRoot" class="radar-root"><div id="radarModeBanner" class="radar-mode-banner" role="status" hidden></div><section class="page-title radar-title"><div><div class="kicker">TRADING HUB · MARKET COMMAND CENTER</div><h1>Market Radar</h1><p class="sub">One screen for top-down context, price action, trendline breaks/reversals, support/resistance and confirmation.</p></div><div class="radar-header-tools"><div class="radar-engine"><i class="live-dot"></i><span id="radarEngineStatus">CONNECTING ENGINE</span></div><div class="confirmation-alert-controls"><button type="button" id="confirmationAlertsToggle" class="alert-control" aria-pressed="false" title="Enable Alerts">🔇 Alerts OFF</button><button type="button" id="testConfirmationSound" class="alert-test-control">Test sound</button></div></div><div id="confirmationToast" class="confirmation-toast" role="status" aria-live="polite" hidden></div></section>'
    +'<section class="radar-hero"><div class="radar-hero-copy"><div class="radar-eyebrow"><span class="live-dot"></span> LIVE SCANNING NETWORK</div><h2>See the market before you touch the button.</h2><p>Trading Hub continuously ranks the instruments it can observe, explains the setup state and separates <b>watching</b> from <b>confirmation</b>. The radar combines top-down analysis, price action, trendline breaks/reversals and support/resistance into one confirmation workflow.</p><div class="radar-hero-tags"><span>H1 / H4 CONTEXT</span><span>PRICE ACTION</span><span>TRENDLINE</span><span>S/R</span><span>CRT CONTEXT</span></div></div><div class="radar-hero-stats"><div><b id="radarWatching">0</b><span>WATCHING</span></div><div><b id="radarDeveloping">0</b><span>DEVELOPING</span></div><div><b id="radarConfirming">0</b><span>CONFIRMING</span></div><div><b id="radarBullish">0</b><span>BULLISH</span></div></div></section>'
    +'<section class="radar-command-strip"><div><span class="kicker">SCANNER STATUS</span><b>MARKET COVERAGE</b><small>Forex · Gold · Indices · Crypto</small></div><div><span class="kicker">REFRESH</span><b>10 SEC</b><small>Engine snapshots update automatically</small></div><div><span class="kicker">MODEL</span><b>TRENDLINE V3</b><small>Trendline event is the strategy gate</small></div><div><span class="kicker">EXECUTION</span><b>MANUAL</b><small>No orders are sent by Trading Hub</small></div></section>'
    +'<section class="panel developing-command watch-panel"><div class="developing-head"><div><span class="kicker">MARKET RADAR · LIVE EPISODES</span><h2>CURRENT / DEVELOPING SETUPS</h2><p>Persistent setup episodes remain here as scanner evidence changes.</p></div><span id="watchCount" class="observatory-count">0 SETUPS</span></div><div id="watchingCards" class="developing-grid watch-grid lifecycle-grid"></div></section>'
    +'<section class="panel developing-command confirmed-panel"><div class="confirmed-head"><div><span class="kicker">VALIDATED BY EXISTING STRATEGY RULES</span><h2>CONFIRMED SETUPS</h2></div><div id="confirmedStatus" class="confirmed-status">0 CONFIRMED</div></div><div id="persistentConfirmedCards" class="developing-grid confirmed-grid lifecycle-grid"></div></section>'
    +'<section class="panel developing-command closed-panel"><div class="confirmed-head"><div><span class="kicker">EPISODE HISTORY</span><h2>RECENTLY CLOSED SETUPS</h2><p>Invalidated when conditions broke; expired when the episode became stale.</p></div><div id="closedStatus" class="confirmed-status">0 CLOSED</div></div><div id="recentlyClosedCards" class="developing-grid lifecycle-grid"></div></section>'
    +'<section class="panel performance-panel"><div class="developing-head"><div><span class="kicker">📊 TODAY\'S PERFORMANCE</span><h2>Daily Setup Performance</h2><p>Headline uses the 4h market outcome. Other configured horizons remain visible. Trade outcomes are excluded.</p></div></div><div id="dailyPerformance"><div class="macro-empty"><b>Loading performance</b></div></div></section>'
    +'<details class="historical-confirmations" id="historicalConfirmations"><summary><span>📚 CONFIRMATION EVENT ARCHIVE (<b id="historicalConfirmationCount">0</b>)</span><span class="historical-expand-hint">Expand</span></summary><div id="historicalConfirmationCards" class="developing-grid confirmed-grid historical-confirmation-grid"></div><div id="confirmedCards" class="confirmation-legacy-cards"></div><span id="confirmedArchiveStatus" hidden></span></details>'
    +'<section class="panel live-intelligence-stage"><div class="live-stage-head"><div><span class="kicker">PRIMARY SYSTEM VIEW</span><h2>Live Market Intelligence</h2><p>Trading Hub turns raw market data into a readable setup thesis, reaction map and confirmation state.</p></div><div class="stage-status"><i class="live-dot"></i><span id="radarUpdated">Waiting…</span></div></div><div class="radar-detail-panel" id="radarDetail"></div></section>'
    +'<section class="radar-grid"><div class="panel radar-market-panel"><div class="panel-head"><div><span class="kicker">OPPORTUNITY MATRIX</span><h2>Where attention belongs</h2></div><span class="radar-refresh">LIVE QUEUE</span></div><div class="radar-legend"><span>PAIR</span><span>PRICE / 24H</span><span>BIAS</span><span>STATE</span><span>SCORE</span></div><div class="radar-table" id="radarTable"></div></div></section>'
    +'<section class="radar-bottom-grid"><div class="panel radar-fundamentals"><div class="panel-head"><div><span class="kicker">MACRO RADAR</span><h2>Events that can change the tape</h2></div><span class="radar-refresh">US EVENTS</span></div><div id="radarFundamentals" class="macro-list"><div class="macro-empty"><b>Loading macro context</b></div></div></div><div class="panel radar-philosophy"><div class="kicker">TRADING HUB PHILOSOPHY</div><div class="philosophy-orb">✦</div><h2>Wait for the market to earn the trade.</h2><p>The radar is intentionally allowed to say <b>WAIT</b>. Every observation becomes structured data that can later train the learning layer.</p><div class="philosophy-flow"><span>OBSERVE</span><i>→</i><span>CONFIRM</span><i>→</i><span>EXECUTE</span><i>→</i><span>LEARN</span></div></div></section>'
    +'<section class="radar-method"><div class="kicker">SCANNER LOGIC · V3</div><div class="radar-steps"><span>01 HTF</span><i>→</i><span>02 PRICE ACTION</span><i>→</i><span>03 TRENDLINE</span><i>→</i><span>04 S/R</span><i>→</i><span>05 CRT</span><i>→</i><span>06 SESSION</span><i>→</i><b>100-POINT SETUP</b></div><p>Transparent by design. Breaks and reversals are both valid setup families; top-down context, price action and S/R determine whether either one earns confirmation.</p></section></div>';
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
    return {mode:data?.live&&markets.length?"LIVE":"ENGINE_NO_DATA",markets,live:!!data?.live&&markets.length>0,source:data?.source||"MT5",timestamp:data?.timestamp,mt5Status:data?.mt5_status,error:data?.error};
  }catch(_){}
  return radarDemoEnabled()?{mode:"DEMO",markets:demoData(),live:false,source:"DEMO"}:{mode:"OFFLINE",markets:[],live:false,source:"OFFLINE"};
}
async function getPerformance(){try{return await engineFetch("/api/market/performance");}catch(_){return null;}}
async function getAnalysis(m){if(!m?.setup_id)return null;const observationId=m.observation_id||"";const key=m.setup_id+":"+observationId;if(analystCache.has(key))return analystCache.get(key);try{const suffix=observationId?"?observation_id="+encodeURIComponent(observationId):"";const data=await engineFetch("/api/market/setups/"+encodeURIComponent(m.setup_id)+"/analysis"+suffix);analystCache.set(key,data);return data;}catch(_){analystCache.set(key,null);return null;}}
function miniStructure(m){
  const bias=String(m.market_bias||"").toUpperCase();
  const bearish=bias.includes("BEAR");
  const bullish=bias.includes("BULL");
  const trend=bullish?"up":bearish?"down":"flat";
  const points=bullish?"8,62 24,55 40,60 56,43 72,47 88,30 104,34 120,20":bearish?"8,20 24,27 40,19 56,37 72,31 88,48 104,42 120,60":"8,42 24,36 40,48 56,41 72,45 88,39 104,44 120,40";
  const high=m.london_high!=null?fmt(m.london_high,2):"L-H";
  const low=m.london_low!=null?fmt(m.london_low,2):"L-L";
  return '<div class="dev-chart '+trend+'">'
    +'<div class="dev-chart-grid"></div><div class="dev-range"><span>'+high+'</span><span>'+low+'</span></div>'
    +'<svg viewBox="0 0 128 80" preserveAspectRatio="none" aria-hidden="true"><polyline points="'+points+'" fill="none"/></svg>'
    +'<div class="dev-trendline"></div><i class="dev-live-marker"></i>'
    +'<span class="dev-chart-label">M15 · STRUCTURE</span></div>';
}
function triggerRead(m){
  const trigger=Number(m.trigger);
  const price=Number(m.price);
  if(Number.isFinite(trigger)&&Number.isFinite(price)&&price){
    const distance=Math.abs(trigger-price)/price*100;
    return {label:distance<0.15?"NEAR TRIGGER":distance<0.4?"APPROACHING":"DISTANT",value:distance.toFixed(2)+"% away"};
  }
  return {label:"AWAITING TRIGGER",value:"Confirmation required"};
}
function observatoryRank(m){
  const state=String(m.state||"WATCHING").toUpperCase();
  const priority=state==="CONFIRMING"?3:state==="DEVELOPING"?2:state==="WATCHING"?1:0;
  return priority*1000+Number(m.score||0);
}
function timeLabel(value){if(!value)return "Time unavailable";const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString();}
function durationLabel(seconds){if(seconds==null)return "—";const n=Math.max(0,Number(seconds)||0);if(n<60)return n+" sec";if(n<3600)return Math.floor(n/60)+" min";if(n<86400)return Math.floor(n/3600)+" hr "+Math.floor(n%3600/60)+" min";return Math.floor(n/86400)+" d "+Math.floor(n%86400/3600)+" hr";}
function lifecycleCard(m, bucket){
  const state=String(m.lifecycle_state||m.state||"DETECTED").toUpperCase();
  const direction=String(m.direction||"—").toUpperCase();
  const setup=m.setup_type||m.setup_family||m.setup||"Setup type unavailable";
  const confirmation=m.confirmation||{};
  const close=m.closed_event||{};
  const entry=m.proposed_entry??m.entry;
  const stop=m.proposed_stop_loss??m.stop_loss;
  const target=m.proposed_take_profit??m.take_profit;
  const tone=state==="INVALIDATED"?"invalidated":state==="EXPIRED"||state==="RESOLVED"?"expired":state==="CONFIRMED"||state==="ACTIVE"?"confirmed":direction==="LONG"?"buy":direction==="SHORT"?"sell":"watch";
  return '<article class="lifecycle-card '+tone+'">'
    +'<div class="lifecycle-card-head"><div><span class="lifecycle-state">'+esc(state)+'</span><h3>'+esc(m.symbol||"UNKNOWN")+' <b>'+esc(direction)+'</b></h3><p>'+esc(setup)+' · '+esc(m.timeframe||"M15")+'</p></div><div class="dev-score"><strong>'+Number(m.score||0)+'</strong><span>/100</span></div></div>'
    +'<div class="lifecycle-facts"><div><span>DETECTED</span><b>'+esc(timeLabel(m.detected_at||m.observed_at))+'</b></div><div><span>DURATION</span><b>'+esc(durationLabel(m.duration_seconds))+'</b></div>'
    +(confirmation.confirmed_at||m.confirmation_time?'<div><span>CONFIRMED</span><b>'+esc(timeLabel(confirmation.confirmed_at||m.confirmation_time))+'</b></div>':'')
    +(entry!=null?'<div><span>ENTRY ZONE</span><b>'+fmt(entry,4)+'</b></div>':'')
    +(stop!=null?'<div><span>STOP LOSS</span><b>'+fmt(stop,4)+'</b></div>':'')
    +(target!=null?'<div><span>TAKE PROFIT</span><b>'+fmt(target,4)+'</b></div>':'')
    +(bucket==="closed"?'<div class="lifecycle-reason"><span>'+esc(state)+" REASON"+'</span><b>'+esc(close.reason||close.reason_code||"Episode closed")+'</b></div>':'')
    +'</div>'
    +(bucket==="confirmed"||confirmation.confirmed_at||m.confirmation_time?'<small class="lifecycle-disclaimer">Not an entry recommendation.</small>':'')
    +'<footer><span>SETUP '+esc(m.setup_id||"untracked")+'</span><span>LAST OBSERVED '+esc(timeLabel(m.observed_at))+'</span></footer>'
    +'</article>';
}
function paintEpisodeBuckets(episodes, markets=[]){
  const partitioned=partitionSetupEpisodes([...(episodes?.current||[]),...(episodes?.confirmed||[]),...(episodes?.closed||[])]);
  let current=partitioned.current;
  if(!current.length&&!(episodes?.confirmed||[]).length&&!(episodes?.closed||[]).length){
    current=currentWatchSetups(markets).map(m=>({...m,lifecycle_state:m.state==="CONFIRMING"?(m.strategy_valid?"CONFIRMED":"CONFIRMING"):m.state==="DEVELOPING"?"DEVELOPING":"DETECTED",detected_at:m.observed_at||m.timestamp,duration_seconds:0}));
  }
  const confirmed=partitioned.confirmed;
  const closed=partitioned.closed.slice(0,20);
  const live=document.getElementById("watchingCards"),confirmedNode=document.getElementById("persistentConfirmedCards"),closedNode=document.getElementById("recentlyClosedCards");
  if(live)live.innerHTML=current.length?current.map(m=>lifecycleCard(m,"current")).join(""):'<div class="radar-empty compact-empty"><b>No current or developing setup episodes.</b><p>Monitoring remains active.</p></div>';
  if(confirmedNode)confirmedNode.innerHTML=confirmed.length?confirmed.map(m=>lifecycleCard(m,"confirmed")).join(""):'<div class="confirmed-empty"><b>No confirmed setup episodes yet.</b></div>';
  if(closedNode)closedNode.innerHTML=closed.length?closed.map(m=>lifecycleCard(m,"closed")).join(""):'<div class="confirmed-empty"><b>No recently closed setups.</b></div>';
  const count=document.getElementById("watchCount");if(count)count.textContent=current.length+" SETUPS";
  const confirmedCount=document.getElementById("confirmedStatus");if(confirmedCount)confirmedCount.textContent=confirmed.length+" CONFIRMED";
  const closedCount=document.getElementById("closedStatus");if(closedCount)closedCount.textContent=closed.length+" CLOSED";
}
function opportunityCards(markets){
  const candidates=currentWatchSetups(markets).sort((a,b)=>{
    const relevance=observatoryRank(b)-observatoryRank(a);
    if(relevance)return relevance;
    return Date.parse(b.observed_at||b.timestamp||0)-Date.parse(a.observed_at||a.timestamp||0);
  });
  if(!candidates.length)return '<div class="radar-empty compact-empty"><b>No developing setups right now.</b><p>Trading Hub is monitoring the available market data.</p></div>';
  const summary=setupCountSummary(candidates.length,watchExpanded);
  const toolbar=summary?'<div class="setup-grid-toolbar"><span>'+esc(summary)+'</span><button type="button" class="text-btn setup-view-toggle" data-expand-watch aria-expanded="'+watchExpanded+'">'+(watchExpanded?'Show less':'View all')+'</button></div>':'';
  const visible=visibleSetupEntries(candidates,watchExpanded);
  return toolbar+visible.map((m,index)=>{
      const action=String(m.action||"WAIT").toUpperCase();
      const trigger=triggerRead(m);
      const direction=String(m.direction||"").toUpperCase();
      const tone=action.includes("BUY")||direction==="LONG"?"buy":action.includes("SELL")||direction==="SHORT"?"sell":"watch";
      const entry=Number(m.entry);
      const stop=Number(m.stop_loss);
      const target=Number(m.take_profit);
      const rr=Number(m.rr);
      const state=String(m.state||"WATCHING").toUpperCase();
      const hasPlan=["DEVELOPING","CONFIRMING"].includes(state)&&Number.isFinite(entry)&&Number.isFinite(stop)&&Number.isFinite(target);
      const setupLabel=m.setup_family?String(m.setup_family).toUpperCase():String(m.setup||"SETUP").toUpperCase();
      return '<button class="developing-card '+tone+'" data-symbol="'+esc(m.symbol)+'">'
        +'<div class="dev-card-glow"></div>'
        +'<div class="dev-card-top"><div><small class="dev-rank">'+String(index+1).padStart(2,"0")+' · NEEDS MORE EVIDENCE</small><b>'+esc(m.symbol)+' · '+esc(direction||action)+'</b><small>'+esc(m.state||"WATCHING")+' · '+esc(setupLabel)+'</small></div><div class="dev-score"><strong>'+Number(m.score||0)+'</strong><span>/100</span></div></div>'
        +miniStructure(m)
        +'<div class="dev-price-row"><div><span class="dev-label">LIVE PRICE</span><div class="dev-price">'+fmt(m.price)+'</div></div><div class="dev-proximity"><span>'+trigger.label+'</span><b>'+trigger.value+'</b></div></div>'
        +(hasPlan?'<div class="dev-plan"><div><span>ENTRY</span><b>'+fmt(entry,2)+'</b></div><div class="risk"><span>SL</span><b>'+fmt(stop,2)+'</b></div><div class="reward"><span>TP</span><b>'+fmt(target,2)+'</b></div><div><span>R:R</span><b>'+(Number.isFinite(rr)?rr.toFixed(2)+'R':'—')+'</b></div></div>':'<div class="dev-plan waiting"><span>TRADE PLAN</span><b>Waiting for calculated levels</b></div>')
        +'<div class="dev-thesis">'+esc(m.insight||m.reason||"Setup developing")+'</div>'
        +'<div class="dev-expanded"><div><span>WHY IT IS WATCHED</span><b>'+esc(m.reason||m.insight||"No setup explanation yet.")+'</b></div><div><span>WAITING FOR</span><b>'+esc(m.trigger||"More scanner evidence")+'</b></div><div><span>HTF / S-R</span><b>'+esc((m.higher_timeframe_bias||"—")+" · "+(m.nearest_level_type||"S/R scan"))+'</b></div><div><span>SETUP ID · LIFECYCLE</span><b>'+esc(m.setup_id||"Untracked / demo")+' · '+esc(m.lifecycle_state||"UNKNOWN")+'</b></div><div><span>OBSERVED</span><b>'+esc(m.observed_at||m.timestamp||"Timestamp unavailable")+'</b></div></div>'
        +'<div class="dev-meta"><span>'+esc(m.market_bias||"NEUTRAL")+'</span><span>'+esc(m.stage||"STRUCTURE")+'</span><em class="'+actionClass(action)+'">'+action+'</em></div>'
        +'</button>';
    }).join("");
}

function confirmedCard(event, market, analysis, confirmationState){
  const m=market||event;
  const outcomes=event.market_outcomes||{};
  const outcome=String(event.primary_outcome||outcomes["4h"]||"PENDING").toUpperCase();
  const lifecycle=String(m.lifecycle_state||"UNKNOWN").toUpperCase();
  const outcomeText=outcome==="WIN"||outcome==="LOSS"?outcome:outcome==="PENDING"?"OUTCOME PENDING":outcome;
  const status=(confirmationState?.currentlyConfirmed?"CURRENTLY CONFIRMED":"HISTORICAL / RECENT CONFIRMATION")+" · "+outcomeText;
  const direction=String(m.direction||event.direction||"").toUpperCase();
  const action=direction==="LONG"?"BUY":direction==="SHORT"?"SELL":String(m.action||"DIRECTION UNAVAILABLE").toUpperCase();
  const evidence=(analysis?.confirmations||[]).slice(0,4).map(x=>'<span class="confirmed-evidence">✓ '+esc(x.claim||x.source_field)+' <small>'+esc(x.source_field)+': '+esc(x.source_value)+'</small></span>').join("");
  const conflicts=(analysis?.conflicts||[]).slice(0,3).map(x=>'<span class="conflict-evidence">! '+esc(x.claim||x.source_field)+' <small>'+esc(x.source_field)+': '+esc(x.source_value)+'</small></span>').join("");
  const risk=analysis?.risk_context||{};
  const value=(v,d=4)=>v==null?"—":fmt(v,d);
  return '<button class="developing-card confirmed-card '+(action==="BUY"?"buy":action==="SELL"?"sell":"watch")+'" data-setup-id="'+esc(event.setup_id)+'">'
    +'<div class="confirmed-card-top"><div><span class="confirmed-status-pill '+outcome.toLowerCase().replace(/[^a-z]/g,"")+'">'+esc(status)+'</span><h3>'+esc(m.symbol||event.symbol||"UNKNOWN")+' <b>'+esc(action)+'</b></h3><p>'+esc(event.setup_type||m.setup_family||m.setup||"Setup type unavailable")+' · '+esc(event.timeframe||m.timeframe||"Timeframe unavailable")+'</p></div><div class="dev-score"><strong>'+Number(event.score??m.score??0)+'</strong><span>/100</span></div></div>'
    +'<p class="confirmed-why">'+esc(analysis?.summary||m.insight||m.reason||"Passed the existing strategy validation gate.")+'</p>'
    +'<div class="confirmed-evidence-grid"><div><b>KEY CONFIRMATIONS</b>'+(evidence||'<span class="confirmed-evidence">Strategy validation passed <small>rule_evidence.strategy_valid: true</small></span>')+'</div><div><b>CONFLICTING EVIDENCE</b>'+(conflicts||'<span class="muted-evidence">No conflicting evidence recorded.</span>')+'</div></div>'
    +'<div class="confirmed-levels"><div><span>REFERENCE / ENTRY</span><b>'+value(risk.entry??risk.reference_price??m.entry??m.price)+'</b></div><div><span>INVALIDATION / SL</span><b>'+value(risk.invalidation??risk.stop_loss??m.stop_loss)+'</b></div><div><span>TP</span><b>'+value(risk.take_profit??m.take_profit)+'</b></div><div><span>R:R</span><b>'+value(risk.rr??m.rr,2)+'</b></div></div>'
    +'<div class="confirmed-card-foot"><span>SETUP '+esc(event.setup_id||"unavailable")+'</span><span>CURRENT STATE '+esc(confirmationState?.currentState||m.state||"UNKNOWN")+'</span><span>CURRENT LIFECYCLE '+esc(confirmationState?.currentLifecycle||lifecycle)+'</span><span>EVENT '+esc(event.confirmed_at||"timestamp unavailable")+'</span><span>FRESHNESS '+esc(freshnessLabel(m.data_quality,m.data_freshness))+'</span><span class="market-outcome-note">4h MARKET OUTCOME: '+esc(outcome)+' · Not a trade result</span></div>'
    +'</button>';
}

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

function paintConfirmed(markets, performance){
  const container=document.getElementById("confirmedCards"),status=document.getElementById("confirmedArchiveStatus");
  const historicalContainer=document.getElementById("historicalConfirmationCards");
  const historicalCount=document.getElementById("historicalConfirmationCount");
  if(!container||!status||!historicalContainer||!historicalCount)return;
  const entries=confirmedEntries(markets,performance);
  for(const market of markets){const id=market.setup_id;if(market.strategy_valid===true&&id&&!confirmedDetailCache.has(id)&&!confirmedDetailPending.has(id)){confirmedDetailPending.add(id);engineFetch("/api/market/setups/"+encodeURIComponent(id)).then(detail=>{confirmedDetailCache.set(id,detail);}).catch(()=>{confirmedDetailCache.set(id,null);}).finally(()=>{confirmedDetailPending.delete(id);if(container.isConnected)paintConfirmed(markets,performance);});}}
  for(const {event} of entries){const id=event.setup_id;if(id&&!confirmedDetailCache.has(id)&&!confirmedDetailPending.has(id)){confirmedDetailPending.add(id);engineFetch("/api/market/setups/"+encodeURIComponent(id)).then(detail=>{confirmedDetailCache.set(id,detail);}).catch(()=>{confirmedDetailCache.set(id,null);}).finally(()=>{confirmedDetailPending.delete(id);if(container.isConnected)paintConfirmed(markets,performance);});}}
  const pending=entries.filter(({event})=>String(event.primary_outcome||event.market_outcomes?.["4h"]||"").toUpperCase()==="PENDING").length;
  const active=entries.filter(({market})=>String(market?.lifecycle_state||"").toUpperCase()==="ACTIVE").length;
  const {current,historical}=partitionConfirmations(entries);
  status.textContent=current.length+" CURRENT · "+active+" ACTIVE · "+pending+" OUTCOME PENDING";
  historicalCount.textContent=String(historical.length);
  container.classList.toggle("has-one",current.length===1);container.classList.toggle("is-empty",current.length===0);
  const cards=items=>items.map(({event,market,display})=>confirmedCard(event,market,analystCache.get(event.setup_id+":"+(event.observation_id||"")),display)).join("");
  const countSummary=setupCountSummary(current.length,currentConfirmedExpanded);
  const toolbar=countSummary?'<div class="setup-grid-toolbar"><span>'+esc(countSummary)+'</span><button type="button" class="text-btn setup-view-toggle" data-expand-confirmed aria-expanded="'+currentConfirmedExpanded+'">'+(currentConfirmedExpanded?'Show less':'View all')+'</button></div>':'';
  const shown=visibleSetupEntries(current,currentConfirmedExpanded);
  container.innerHTML=toolbar+(shown.length?cards(shown):'<div class="confirmed-empty"><b>No setups currently confirmed</b></div>');
  historicalContainer.innerHTML=historical.length?cards(historical):'<div class="historical-empty">No historical or recent confirmations.</div>';
  for(const {event} of entries){const key=event.setup_id+":"+(event.observation_id||"");if(event.observation_id&&!analystCache.has(key))getAnalysis({setup_id:event.setup_id,observation_id:event.observation_id}).then(analysis=>{if(!analysis)return;analystCache.set(key,analysis);if(container.isConnected)paintConfirmed(markets,performance);});}
  container.onclick=event=>{
    if(event.target.closest("[data-expand-confirmed]")){currentConfirmedExpanded=!currentConfirmedExpanded;paintConfirmed(markets,performance);return;}
    const card=event.target.closest(".confirmed-card"),market=card&&markets.find(m=>m.setup_id===card.dataset.setupId),detail=document.getElementById("radarDetail");if(market&&detail)selectMarket(market,detail);
  };
  historicalContainer.onclick=event=>{const card=event.target.closest(".confirmed-card"),market=card&&markets.find(m=>m.setup_id===card.dataset.setupId),detail=document.getElementById("radarDetail");if(market&&detail)selectMarket(market,detail);};
}

function paint(result){
  latestMarkets=result.markets||[];
  latestEpisodes=result.episodes||latestEpisodes;
  processConfirmationEvents(result.performance);
  const table=document.getElementById("radarTable"),detail=document.getElementById("radarDetail"),watchCards=document.getElementById("watchingCards"),confirmedCards=document.getElementById("confirmedCards");
  if(!table||!detail)return;
  const mode=result.mode||"LIVE";
  paintMode(mode,result);
  const sorted=[...latestMarkets].sort((a,b)=>(b.score||0)-(a.score||0));
  table.innerHTML=sorted.length?sorted.map(row).join(""):'<div class="empty-state">'+(mode==="OFFLINE"?"Engine offline — no market data is shown.":"The engine returned no markets.")+'</div>';
  paintEpisodeBuckets(latestEpisodes,latestMarkets);
  paintConfirmed(latestMarkets,result.performance);
  const current=detail.dataset.symbol;
  const focus=sorted.find(m=>m.symbol===current)||sorted.find(m=>["CONFIRMING","DEVELOPING","WATCHING"].includes(m.state))||sorted[0];
  detail.innerHTML=!focus&&mode!=="LIVE"?offlineDetail(mode):renderDetail(focus,selectedMarket?.setup_id===focus?.setup_id?selectedMarket.analysis:null);
  detail.dataset.symbol=focus?.symbol||"";
  selectedMarket=focus?{...focus,analysis:selectedMarket?.setup_id===focus.setup_id?selectedMarket.analysis:null}:null;
  if(focus?.setup_id&&!selectedMarket?.analysis)getAnalysis(focus).then(analysis=>{if(analysis&&selectedMarket?.setup_id===focus.setup_id){selectedMarket={...focus,analysis};detail.innerHTML=renderDetail(focus,analysis);}});
  const counts={WATCHING:0,DEVELOPING:0,CONFIRMING:0};
  latestMarkets.forEach(m=>{if(counts[m.state]!=null)counts[m.state]++});
  document.getElementById("radarWatching").textContent=counts.WATCHING;
  document.getElementById("radarDeveloping").textContent=counts.DEVELOPING;
  document.getElementById("radarConfirming").textContent=counts.CONFIRMING;
  document.getElementById("radarBullish").textContent=latestMarkets.filter(m=>String(m.market_bias||"").startsWith("BULLISH")).length;
  const now=new Date().toLocaleTimeString();
  document.getElementById("radarUpdated").textContent={LIVE:"LIVE · "+now,ENGINE_NO_DATA:"NO MARKET DATA · "+now,OFFLINE:"OFFLINE · checked "+now,DEMO:"SIMULATED · NOT MARKET DATA"}[mode];
  const status=document.getElementById("radarEngineStatus");if(status)status.textContent={LIVE:"LIVE MT5 ENGINE",ENGINE_NO_DATA:"ENGINE ONLINE · MT5 "+String(result.mt5Status||"NO DATA"),OFFLINE:"ENGINE OFFLINE",DEMO:"DEMO MODE · ENGINE OFFLINE"}[mode];
  table.querySelectorAll(".radar-row-btn").forEach(btn=>btn.addEventListener("click",()=>{const m=latestMarkets.find(x=>x.symbol===btn.dataset.symbol);if(m)selectMarket(m,detail);}));
  paintPerformance(result.performance);
}
function paintMode(mode,result){
  const root=document.getElementById("radarRoot"),banner=document.getElementById("radarModeBanner");
  if(root){root.classList.toggle("is-simulated",mode==="DEMO");root.classList.toggle("is-offline",mode==="OFFLINE"||mode==="ENGINE_NO_DATA");}
  if(!banner)return;
  if(mode==="LIVE"){banner.hidden=true;banner.innerHTML="";return;}
  banner.hidden=false;banner.dataset.mode=mode;
  banner.innerHTML=mode==="DEMO"
    ?'<b>DEMO MODE</b><b>ENGINE OFFLINE</b><b>SIMULATED SETUPS</b><span>Everything below is fixed sample data for UI development. Prices, scores and setups are not current market information. Disable with localStorage th_radar_demo=0.</span>'
    :mode==="OFFLINE"
    ?'<b>ENGINE OFFLINE</b><span>No market data. Start the engine with backend/start_engine.bat (expected at '+esc(getEngineUrl())+'). Retrying every 10 seconds.</span>'
    :'<b>ENGINE ONLINE</b><b>NO MARKET DATA</b><span>MT5 status: '+esc(result.mt5Status||"UNKNOWN")+(result.error?' · '+esc(result.error):'')+'. Check that MetaTrader 5 is open and logged in.</span>';
}
function offlineDetail(mode){return '<div class="radar-empty"><div class="radar-empty-orb">⌁</div><b>'+(mode==="OFFLINE"?"Engine offline":"No market data")+'</b><p>'+(mode==="OFFLINE"?"The scanner is not running, so no setups are being evaluated. Nothing on this page reflects the current market.":"The engine is reachable but MT5 returned no markets.")+'</p></div>';}
function selectMarket(m,detail){selectedMarket={...m,analysis:null};detail.innerHTML=renderDetail(m);detail.dataset.symbol=m.symbol;getAnalysis(m).then(analysis=>{if(analysis&&selectedMarket?.setup_id===m.setup_id){selectedMarket={...m,analysis};detail.innerHTML=renderDetail(m,analysis);}});}
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
    container.insertAdjacentHTML("beforeend",'<article class="confirmation-toast-card" data-confirmation-toast="'+esc(setupId)+'"><b>🔔 NEW CONFIRMED SETUP</b><strong>'+esc(event.symbol||"Symbol unavailable")+' · '+esc(direction)+'</strong><span>'+esc(setupType)+'</span><span>Score · '+esc(score)+'</span><small>Confirmation time · '+esc(time)+'</small><small class="confirmation-toast-note">Not an entry recommendation.</small></article>');
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
  if(toggle)toggle.onclick=async()=>{
    if(confirmationAlertsEnabled){confirmationAlertsEnabled=false;}
    else if(await unlockAlertAudio()){confirmationAlertsEnabled=true;}
    toggle.textContent=confirmationAlertsEnabled?"🔊 Alerts ON":"🔇 Alerts OFF";
    toggle.setAttribute("aria-pressed",String(confirmationAlertsEnabled));
    toggle.setAttribute("aria-label",confirmationAlertsEnabled?"Disable Alerts":"Enable Alerts");
    toggle.title=confirmationAlertsEnabled?"Disable confirmation sound alerts":"Enable Alerts";
  };
  if(test)test.onclick=()=>{dispatchTestSound(()=>playConfirmationTone());};
}
function paintPerformance(data){const el=document.getElementById("dailyPerformance");if(!el)return;if(!data){el.innerHTML='<div class="macro-empty"><b>Performance unavailable</b><span>Backend performance endpoint did not respond.</span></div>';return;}const daily=data.daily?.[0]||data.summary||{};const horizons=daily.by_horizon||{};const rows=["15m","1h","4h","24h"].map(h=>{const x=horizons[h]||{};return '<tr><th>'+h+'</th><td>'+Number(x.win||0)+'</td><td>'+Number(x.loss||0)+'</td><td>'+Number(x.pending||0)+'</td><td>'+Number(x.no_hit||0)+'</td><td>'+Number(x.ambiguous||0)+'</td></tr>';}).join("");const h4=horizons["4h"]||{};const wins=Number(h4.win||0),losses=Number(h4.loss||0),denominator=Number(h4.win_rate_denominator??wins+losses);const rate=h4.win_rate;el.innerHTML='<div class="performance-headline"><b>'+wins+'W / '+losses+'L</b><span>4h win rate '+(rate==null?"—":Number(rate).toFixed(1)+"%")+' · denominator '+denominator+' (wins + losses)</span></div><div class="performance-table-wrap"><table class="performance-table"><thead><tr><th>HORIZON</th><th>W</th><th>L</th><th>PENDING</th><th>NO HIT</th><th>AMBIGUOUS</th></tr></thead><tbody>'+rows+'</tbody></table></div><small>Timezone: '+esc(data.timezone||daily.reporting_timezone||"Africa/Nairobi")+' · MarketOutcome records only. NO_HIT and AMBIGUOUS are excluded from win-rate denominator.</small>';}
function paintFundamentals(data){
  const el=document.getElementById("radarFundamentals");if(!el)return;
  if(!data.configured){el.innerHTML='<div class="macro-empty"><b>Macro layer ready</b><span>Connect a Trading Economics API key on the engine to bring live US economic events into the scanner.</span></div>';return;}
  const events=(data.events||[]).filter(e=>String(e.importance||"").toLowerCase()!=="low").slice(0,8);
  el.innerHTML=events.length?events.map(e=>'<div class="macro-event"><span>'+esc(e.date||"")+'</span><b>'+esc(e.event||"Economic event")+'</b><em>'+esc(String(e.importance||""))+'</em></div>').join(""):'<div class="macro-empty"><b>No major events returned</b><span>'+esc(data.status||"LIVE")+'</span></div>';
}
async function getSetupEpisodes(){try{return await engineFetch("/api/market/setup-episodes?bucket=all&limit=100");}catch(_){return null;}}
const EMPTY_EPISODES={current:[],confirmed:[],closed:[]};
async function refreshRadar(isCurrent){
  const [radar,performance,episodes]=await Promise.all([getRadar(),getPerformance(),getSetupEpisodes()]);
  if(!isCurrent())return;
  // Engine offline or demo: never show previously fetched engine episodes as if current.
  paint({...radar,performance,episodes:radar.mode==="LIVE"||radar.mode==="ENGINE_NO_DATA"?(episodes||latestEpisodes):EMPTY_EPISODES});
}
export async function initMarketRadar(){
  bindConfirmationAlertControls();initializeConfirmationAlertTracker();
  if(!radarPoller)radarPoller=createPoller({task:refreshRadar,intervalMs:10000});
  const poll=radarPoller.start();
  paintFundamentals(await getFundamentals());
  await poll;
}
export function stopMarketRadar(){radarPoller?.stop();}
