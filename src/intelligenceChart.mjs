import {engineFetch} from "./engine.js";
import {TV_SYMBOLS,INTERVALS,widgetConfig,candlesForChart,planLines} from "./chartModel.mjs";
import {identityState} from "./userJournal.mjs";
import {candleTime,qualifiedSignals,researchEvents,researchGroups} from "./intelligencePresentation.mjs";
let chart=null,controller=null,generation=0,timer=null;
const esc=value=>String(value??"Unavailable").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const select=(id,label,values)=>`<label>${label}<select id="${id}"><option value="">All</option>${values.map(x=>`<option>${esc(x)}</option>`).join("")}</select></label>`;
export function renderMarkets(){
 const symbols=identityState.entitlements?.symbols||Object.keys(TV_SYMBOLS);
 return `<section class="markets-workspace"><div class="kicker">MARKET INTELLIGENCE</div><h1>Intelligence Chart</h1><p>Price first. Qualified opportunities and historical research in separate views.</p>
 <div class="chart-controls"><label>Instrument<select id="chartSymbol">${symbols.map(s=>`<option>${esc(s)}</option>`).join("")}</select></label><label>Timeframe<select id="chartTimeframe">${Object.keys(INTERVALS).map(s=>`<option ${s==="M15"?"selected":""}>${s}</option>`).join("")}</select></label><label>Intelligence mode<select id="chartMode"><option value="overview">Market Overview</option><option value="signals">Qualified Signals</option><option value="research">Research Intelligence</option></select></label><button id="refreshChart" class="ghost">Refresh</button></div>
 <div id="intelligenceSummary" class="intelligence-summary" aria-live="polite"></div>
 <div id="researchFilters" class="chart-controls" hidden>${select("researchStrategy","Strategy",[])}${select("researchKind","Observation type",["Observation","Confirmation","Hypothetical outcome","Expired"])}${select("researchHorizon","Evaluation horizon",["15m","1h","4h","24h"])}${select("researchOutcome","Hypothetical outcome",["WIN","LOSS","NO_HIT","AMBIGUOUS"])}<label>From (UTC)<input id="researchFrom" type="date"></label><label>Through (UTC)<input id="researchTo" type="date"></label><label>Visible candle groups<select id="researchLimit"><option>20</option><option>50</option><option>100</option><option>200</option></select></label></div>
 <div class="chart-controls chart-tools"><label><input id="chartMarkers" type="checkbox" checked> Show mode markers</label><label><input id="chartRange" type="checkbox"> Candle-window high / low</label><button id="chartZoomIn" class="ghost" title="Zoom into the visible time range">Zoom +</button><button id="chartZoomOut" class="ghost" title="Zoom out of the visible time range">Zoom −</button><button id="resetChart" class="ghost">Reset chart</button><label id="planControl" hidden>Research plan (hypothetical)<select id="chartPlan"><option value="">No overlay</option></select></label></div>
 <p id="chartStatus" role="status">Loading broker candles…</p><div id="intelligenceChart" class="chart-canvas" aria-label="TRADEden broker candle chart"></div><p id="chartActivity" class="chart-caption"></p><p class="chart-caption">Drag to pan · scroll or pinch to zoom · crosshair shows price and UTC time. Research events are anchored to their originating observation candle; evaluation dates appear in details. <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">Charts by TradingView Lightweight Charts™</a></p>
 <section id="chartDetails" class="intelligence-details" aria-live="polite"><h3>Inspect intelligence</h3><p>Select a marker or a record below to see its source details.</p></section><div id="chartRecords" class="intelligence-records"></div>
 <details class="intelligence-definitions"><summary>Understand the data</summary><p><b>Observation:</b> a persisted scanner snapshot of a potential setup. <b>Confirmation:</b> an immutable confirmation event, with its original recorded plan. Historical confirmation alone does not establish current qualification.</p><p><b>Hypothetical outcome:</b> target versus invalidation evaluation over a specified horizon. WIN means target first, LOSS means invalidation first, NO_HIT means neither within the horizon. AMBIGUOUS means both barriers were touched in the same candle, so their order is unknown. Missing labels and conflicting records are not verified performance.</p><p><b>Qualified signal:</b> a LIVE strategy plan returned by the existing current-opportunities qualification gate. <b>Verified trade outcome:</b> separate execution verification records; these are not supplied by the chart research endpoint. No research label is an executed trade.</p></details>
 <h2>TradingView market reference</h2><p>Comparable instruments; broker prices and sessions may differ.</p><button id="loadTradingView" class="ghost">Load official TradingView chart</button><div id="tradingViewChart" class="chart-canvas"></div></section>`;
}
export function stopMarkets(){generation++;controller?.abort();controller=null;chart?.remove();chart=null;clearInterval(timer);timer=null;}
export async function initMarkets(){
 stopMarkets();const root=document.getElementById("intelligenceChart");if(!root)return;
 const token=generation,$=id=>document.getElementById(id);
 const {createChart,CandlestickSeries,createSeriesMarkers}=await import("lightweight-charts");
 if(token!==generation||!root.isConnected)return;
 chart=createChart(root,{autoSize:true,layout:{background:{color:"#10231f"},textColor:"#c4d8cf",attributionLogo:true},grid:{vertLines:{color:"#213c33"},horzLines:{color:"#213c33"}},timeScale:{timeVisible:true},rightPriceScale:{scaleMargins:{top:.16,bottom:.12}}});
 const series=chart.addSeries(CandlestickSeries,{upColor:"#78dba9",downColor:"#e98683",borderVisible:false,wickUpColor:"#78dba9",wickDownColor:"#e98683"});
 const markers=createSeriesMarkers(series,[]);
 let candles=[],episodes=[],outcomes=[],signals=[],groups=[],lines=[],requestNumber=0,widgetLoaded=false,lastSelection="",data=null,opportunitiesAvailable=false;
 const selection=()=>({symbol:$("chartSymbol").value,timeframe:$("chartTimeframe").value,mode:$("chartMode").value});
 function overlay(){
  for(const l of lines)series.removePriceLine(l);lines=[];
  const levels=selection().mode==="research"?planLines(episodes.find(e=>e.setup_id===$("chartPlan").value)).map(l=>({...l,title:`Hypothetical ${l.title}`})):[];
  if($("chartRange").checked&&candles.length)levels.push({price:Math.max(...candles.map(c=>c.high)),title:"Window high",color:"#819b94",lineStyle:2},{price:Math.min(...candles.map(c=>c.low)),title:"Window low",color:"#819b94",lineStyle:2});
  lines=levels.map(l=>series.createPriceLine(l));
 }
 function details(rows){
  $("chartDetails").innerHTML=`<h3>${selection().mode==="research"?"Research · never an executed trade":"Qualified signal"}</h3>`+rows.map(r=>{
   const p=r.confirmed_plan||r;
   return `<article><b>${esc(r.kind||r.direction)} · ${esc(r.strategy_id)}</b><dl>${Object.entries({Instrument:r.symbol,Timeframe:r.timeframe,"Source timestamp (UTC)":r.stamp||r.source_timestamp,"Observation ID":r.observation_id,"Setup ID":r.setup_id,"Lifecycle status":r.lifecycle_state||r.state,"Entry":p.entry??p.proposed_entry,"Stop-loss":p.stop_loss??p.proposed_stop_loss,"Take-profit":p.take_profit??p.proposed_take_profit,"Risk / reward":p.rr,"Hypothetical label":r.label,"Evaluation horizon":r.horizon,"Evaluation end (UTC)":r.horizon_end,"Timestamp quality":r.timestamp_quality,"Label definition":r.label_definition,"Outcome reason":r.label_reason,"Verified trade outcome":null}).map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></article>`;
  }).join("");
 }
 function paint(){
  const {symbol,timeframe,mode}=selection();$("researchFilters").hidden=mode!=="research";$("planControl").hidden=mode!=="research";
  const events=researchEvents(episodes,outcomes);
  const result=researchGroups(candles,events,{timeframe,strategy:$("researchStrategy").value,kind:$("researchKind").value,horizon:$("researchHorizon").value,outcome:$("researchOutcome").value,from:$("researchFrom").value,to:$("researchTo").value,limit:$("researchLimit").value});
  groups=mode==="research"?result.groups:[];
  let plotted=[];
  if(mode==="research")plotted=result.markers;
  if(mode==="signals"){
   const map=new Map();
   for(const s of signals){const time=candleTime(candles,s.source_timestamp,timeframe);if(time===null)continue;const key=`${time}|${s.direction}`;if(!map.has(key))map.set(key,{time,rows:[]});map.get(key).rows.push(s);}
   groups=[...map.values()].map(g=>[g.time,g.rows]);
   plotted=groups.map(([time,rows],i)=>({id:`s${i}`,time,position:rows[0].direction==="LONG"?"belowBar":"aboveBar",shape:rows[0].direction==="LONG"?"arrowUp":"arrowDown",color:rows[0].direction==="LONG"?"#78dba9":"#e98683",text:`${rows[0].direction==="LONG"?"BUY":"SELL"}${rows.length>1?` ×${rows.length}`:""}`})).sort((a,b)=>a.time-b.time);
  }
  markers.setMarkers($("chartMarkers").checked?plotted:[]);overlay();
  const last=candles.at(-1);
  $("intelligenceSummary").innerHTML=Object.entries({Instrument:symbol,Timeframe:timeframe,"Last candle price":last?.close,"Market structure":"Unavailable","Momentum":"Unavailable","Market session":"Unavailable","Qualified signals":opportunitiesAvailable?signals.length?`${signals.length} current qualified plan(s)`:"None":"Unavailable","Research activity":mode==="research"?`${episodes.length} episodes · ${outcomes.length} evaluations in loaded window`:"Open Research Intelligence to inspect","Latest candle (UTC)":last?new Date(last.time*1000).toISOString():null,"Chart fetched (UTC)":data?.timestamp}).map(([k,v])=>`<div><small>${esc(k)}</small><strong>${esc(v)}</strong></div>`).join("");
  $("chartActivity").textContent=mode==="research"?`${result.groups.length} / ${result.total} matching candle groups · ${result.omitted} events omitted for missing or out-of-window timestamps. ${data?.research_window||"Bounded research window."} Hypothetical evaluations are not trading performance.`:mode==="signals"?`${opportunitiesAvailable?signals.length+" current qualified plans":"Qualification feed unavailable"}. ${groups.reduce((n,g)=>n+g[1].length,0)} plans aligned to visible candles. Historical confirmations are research. Verified trade outcomes unavailable.`:"Market Overview · research markers hidden. Last candle close is not a live bid/ask quote. Structure, momentum and session assessments are unavailable from this feed. Window high/low are descriptive extrema, not inferred support/resistance.";
  $("chartRecords").replaceChildren();
  for(const [time,rows] of groups){const button=document.createElement("button");button.className="ghost";button.textContent=`${new Date(time*1000).toISOString()} · ${rows.length} ${mode==="research"?"research record(s)":"qualified plan(s)"}`;button.onclick=()=>details(rows);$("chartRecords").append(button);}
 }
 chart.subscribeClick(param=>{const id=param.hoveredObjectId;if(id!==undefined){const index=String(id).startsWith("s")?Number(String(id).slice(1)):groups.findIndex(g=>String(g[0])===String(id));if(groups[index])details(groups[index][1]);}else if(param.time){const rows=groups.filter(g=>g[0]===param.time).flatMap(g=>g[1]);if(rows.length)details(rows);}});
 function widget(){
  const host=$("tradingViewChart");host.replaceChildren();const wrap=document.createElement("div");wrap.className="tradingview-widget-container";wrap.style.height="100%";const inner=document.createElement("div");inner.className="tradingview-widget-container__widget";inner.style.height="100%";wrap.append(inner);
  const script=document.createElement("script");script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";script.async=true;const {symbol,timeframe}=selection();script.textContent=JSON.stringify(widgetConfig(symbol,timeframe));wrap.append(script);host.append(wrap);widgetLoaded=true;$("loadTradingView").textContent="Reload TradingView chart";
 }
 async function load(){
  controller?.abort();controller=new AbortController();const number=++requestNumber;
  const {symbol,timeframe,mode}=selection();$("chartStatus").textContent="Loading broker candles…";
  // Clear stale intelligence immediately when changing markets/modes.
  episodes=[];outcomes=[];signals=[];opportunitiesAvailable=false;data=null;markers.setMarkers([]);$("chartDetails").textContent="Select a record to inspect its source details.";
  if(lastSelection!==`${symbol}|${timeframe}`){candles=[];series.setData([]);}paint();
  try{
   const [chartResult,signalResult]=await Promise.allSettled([engineFetch(`/api/market/chart?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&research=${mode==="research"}`,{signal:controller.signal}),engineFetch("/api/market/opportunities",{signal:controller.signal})]);
   if(token!==generation||number!==requestNumber)return;
   if(chartResult.status!=="fulfilled")throw chartResult.reason;
   data=chartResult.value;candles=candlesForChart(data.candles);if(!candles.length)throw new Error("No verified candles available");series.setData(candles);
   const precision=Number.isInteger(data.digits)?data.digits:2;series.applyOptions({priceFormat:{type:"price",precision,minMove:data.tick_size||10**(-precision)}});
   episodes=(data.episodes||[]).filter(e=>(!e.symbol||e.symbol===symbol)&&(!e.timeframe||e.timeframe===timeframe));outcomes=data.outcomes||[];
   opportunitiesAvailable=signalResult.status==="fulfilled"&&Array.isArray(signalResult.value.opportunities);
   signals=qualifiedSignals(opportunitiesAvailable?signalResult.value.opportunities:[],symbol,timeframe);
   const plan=$("chartPlan"),previous=plan.value;plan.replaceChildren(new Option("No overlay",""));for(const e of episodes)plan.add(new Option(`${e.strategy_id} · ${e.direction||"watch"} · hypothetical plan`,e.setup_id));plan.value=previous;
   const strategy=$("researchStrategy"),old=strategy.value;strategy.replaceChildren(new Option("All",""));for(const s of new Set(episodes.map(e=>e.strategy_id).filter(Boolean)))strategy.add(new Option(s,s));strategy.value=old;
   paint();const key=`${symbol}|${timeframe}`;if(lastSelection!==key){chart.timeScale().fitContent();lastSelection=key;}
   $("chartStatus").textContent=`${symbol} · ${timeframe} · ${candles.length} broker candles · verified UTC`;
  }catch(error){if(error.name!=="AbortError"&&token===generation&&number===requestNumber){candles=[];episodes=[];outcomes=[];signals=[];data=null;series.setData([]);paint();$("chartStatus").textContent="Broker chart unavailable. Check sign-in and the market feed; no candles are fabricated.";}}
 }
 for(const id of ["chartSymbol","chartTimeframe","chartMode"])$(id).onchange=()=>{load();if(widgetLoaded&&id!=="chartMode")widget();};
 for(const id of ["chartPlan","chartMarkers","chartRange","researchStrategy","researchKind","researchHorizon","researchOutcome","researchFrom","researchTo","researchLimit"])$(id).onchange=paint;
 for(const [id,factor] of [["chartZoomIn",.7],["chartZoomOut",1.4]])$(id).onclick=()=>{const r=chart.timeScale().getVisibleLogicalRange();if(r){const mid=(r.from+r.to)/2,half=(r.to-r.from)*factor/2;chart.timeScale().setVisibleLogicalRange({from:mid-half,to:mid+half});}};
 $("resetChart").onclick=()=>{chart.timeScale().fitContent();series.priceScale().applyOptions({autoScale:true});};
 $("refreshChart").onclick=load;$("loadTradingView").onclick=widget;
 await load();if(token===generation&&root.isConnected)timer=setInterval(load,60000);
}
