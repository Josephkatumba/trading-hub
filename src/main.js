import "./styles.css";
import {getTrades,saveTrades,resetTrades,parseCSV,calculateMetrics,getAccounts,getTradeContext} from "./data.js";

const initialAccounts={
 "Goldimus Funded":{platform:"FundedNext",balance:52140,status:"LIVE"},
 "Personal Futures":{platform:"Tradovate",balance:12480,status:"LIVE"},
 "XAUUSD Account":{platform:"MT5",balance:8460,status:"WATCH"}
};
let state={view:"overview",trades:getTrades(),importOpen:false,selectedTrade:null,filters:{account:"ALL",symbol:"ALL",session:"ALL"}};

const nav=[["overview","Overview","⌂"],["accounts","Accounts","◈"],["trades","Trades","↗"],["analytics","Analytics","◒"],["insights","AI Intelligence","✦"]];
const money=n=>(n<0?"-$":"$")+Math.abs(Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});
const signed=n=>n>=0?"+"+money(n):money(n);
const pct=n=>Number(n||0).toFixed(1)+"%";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));

function filteredTrades(){
 const f=state.filters;
 return state.trades.filter(t=>(f.account==="ALL"||t.account===f.account)&&(f.symbol==="ALL"||t.symbol===f.symbol)&&(f.session==="ALL"||t.session===f.session));
}
function options(key){
 return ["ALL",...new Set(state.trades.map(t=>t[key]).filter(Boolean))];
}
function filterSelect(key,label){
 return '<label class="filter"><span>'+label+'</span><select data-filter="'+key+'">'+options(key).map(v=>'<option '+(state.filters[key]===v?"selected":"")+'>'+esc(v)+'</option>').join("")+'</select></label>';
}

function render(){
 const all=state.trades, trades=filteredTrades(), m=calculateMetrics(trades);
 const accounts=getAccounts(all).map(a=>({...a,...(initialAccounts[a.name]||{})}));
 document.querySelector("#root").innerHTML=`
 <div class="app">
  <aside>
   <div class="brand"><span class="logo-mark">TH</span><div>Trading Hub<small>INTELLIGENCE PLATFORM</small></div></div>
   <div class="workspace"><span>WORKSPACE</span><b>Joseph's Portfolio</b><i>⌄</i></div>
   <nav>${nav.map(n=>`<a class="${state.view===n[0]?"active":""}" data-view="${n[0]}"><span>${n[2]}</span>${n[1]}</a>`).join("")}</nav>
   <div class="side-section"><span>DISCOVER</span><a data-view="analytics"><span>◎</span>Performance</a><a data-view="insights"><span>✦</span>AI Analyst</a><a><span>◇</span>Marketplace <em class="soon">SOON</em></a></div>
   <div class="side-bottom"><a><span>⚙</span>Settings</a><div class="profile"><div class="avatar">JK</div><div><b>Joseph Katumba</b><small>Pro workspace</small></div><span>•••</span></div></div>
  </aside>
  <main>
   <div class="topline"><span><i class="live-dot"></i> DATA ENGINE ACTIVE · ${all.length} TRADES</span><span>FILTERED P&L <b>${signed(m.pnl)}</b></span></div>
   ${views[state.view](trades,m,accounts)}
  </main>
 </div>
 ${state.importOpen?importModal():""}${state.selectedTrade?tradeDrawer(state.selectedTrade,all):""}`;
 bind();
}

function importModal(){return `
<div class="modal-backdrop" id="modal"><div class="modal">
<button class="modal-close" id="closeModal">×</button><div class="kicker">DATA CONNECTION</div>
<h2>Connect your trading history</h2><p class="sub">Start with a CSV from MT5, a broker, prop firm or futures platform. Trading Hub normalizes the execution data inside your workspace.</p>
<label class="dropzone" id="dropzone"><input id="csvFile" type="file" accept=".csv,text/csv,.txt"/><span class="upload-icon">↑</span><b>Drop CSV here or click to browse</b><small>CSV · XLS exports can be converted to CSV · browser-local prototype</small></label>
<div id="importStatus"></div><div class="import-actions"><button class="ghost" id="cancelImport">Cancel</button><button class="primary" id="importDemo">Restore demo dataset</button></div>
</div></div>`;}

function tradeDrawer(t,trades){
 const c=getTradeContext(t,trades),similar=trades.filter(x=>x.id!==t.id&&x.symbol===t.symbol).slice(0,3);
 const checks=[["Matched preferred session",c.sessionPnl>=0],["Matched strongest instrument",t.symbol===calculateMetrics(trades).bestInstrument],["Risk within observed range",(Number(t.risk)||0)<=c.avgRisk*1.25]];
 return `
 <div class="drawer-backdrop" id="drawer"><section class="trade-drawer">
  <button class="modal-close" id="closeDrawer">×</button><div class="kicker">TRADE INTELLIGENCE · ${esc(t.id||"EXECUTION")}</div>
  <div class="drawer-hero"><div><span class="direction ${t.side==="BUY"?"buy":"sell"}">${t.side}</span><h2>${esc(t.symbol)}</h2><small>${esc(t.time)} · ${esc(t.session)} · ${esc(t.account)}</small></div><strong class="${t.pnl>=0?"up":"down"}">${signed(t.pnl)}</strong></div>
  <div class="trade-facts"><div><span>ENTRY</span><b>${t.entry||"—"}</b></div><div><span>EXIT</span><b>${t.exit||"—"}</b></div><div><span>R MULTIPLE</span><b>${t.r>=0?"+":""}${Number(t.r||0).toFixed(2)}R</b></div><div><span>RISK</span><b>${money(t.risk||0)}</b></div></div>
  <div class="drawer-section"><div class="kicker">YOUR HISTORY · ${esc(t.symbol)}</div><div class="history-strip"><div><b>${c.symbolTrades}</b><span>TRADES</span></div><div><b>${pct(c.symbolWinRate)}</b><span>WIN RATE</span></div><div><b>+${c.symbolAvgR.toFixed(2)}R</b><span>AVG R</span></div></div></div>
  <div class="drawer-section"><div class="kicker">WHY THIS TRADE MATTERED</div><div class="check-list">${checks.map(x=>`<div><i class="${x[1]?"good":"warn"}">${x[1]?"✓":"!"}</i><span>${x[0]}</span></div>`).join("")}</div></div>
  <div class="drawer-section"><div class="kicker">SIMILAR TRADES</div><div class="similar-list">${similar.length?similar.map(x=>`<button data-trade="${esc(x.id)}"><span>${x.symbol} · ${x.side}</span><b class="${x.pnl>=0?"up":"down"}">${signed(x.pnl)}</b></button>`).join(""):"<p class='sub'>More history will unlock comparable setups.</p>"}</div></div>
  <button class="ai-button drawer-ai" id="askTrade">Ask Trading Hub <span>↗</span></button>
 </section></div>`;}

const views={
overview:(trades,m,accounts)=>`
<section class="command"><div><div class="kicker">PORTFOLIO / LIVE INTELLIGENCE</div><h1>Good evening, Joseph.</h1><p class="sub">Your trading account is becoming the journal. Trading Hub is turning executions into intelligence.</p></div><div class="command-actions"><button class="ghost" id="importTop">Import trades</button><button class="primary" id="connectTop">+ Connect account</button></div></section>
<section class="portfolio-card"><div><div class="tiny">FILTERED EQUITY P&L</div><div class="equity">${signed(m.pnl)}<span class="live-dot"></span></div><div class="equity-meta"><span class="up">${pct(m.winRate)} win rate</span><span>${m.profitFactor.toFixed(2)} profit factor</span><span class="muted">${trades.length} trades</span></div></div><div class="portfolio-spark">${spark(m.equityCurve)}<div class="spark-labels"><span>START</span><span>NOW</span></div></div><div class="portfolio-side"><span>MAX DRAWDOWN</span><strong>${money(m.maxDrawdown)}</strong><div class="meter"><i style="width:${Math.min((m.maxDrawdown/2000)*100,100)}%"></i></div><small>Peak-to-trough P&L</small></div></section>
<section class="metric-grid"><div class="metric"><span>NET P&L</span><strong class="${m.pnl>=0?"up":"down"}">${signed(m.pnl)}</strong><small>Current filter</small></div><div class="metric"><span>MAX DRAWDOWN</span><strong>${money(m.maxDrawdown)}</strong><small>Peak-to-trough</small></div><div class="metric"><span>WIN RATE</span><strong>${pct(m.winRate)}</strong><small>${m.wins} wins / ${m.losses} losses</small></div><div class="metric"><span>PROFIT FACTOR</span><strong>${m.profitFactor.toFixed(2)}</strong><small>Gross profit / loss</small></div><div class="metric"><span>AVG. R</span><strong>${m.avgR>=0?"+":""}${m.avgR.toFixed(2)}R</strong><small>Observed execution</small></div></section>
<section class="dashboard-grid"><div class="panel wide"><div class="panel-head"><div><span class="kicker">PERFORMANCE</span><h2>Equity trajectory</h2></div><button class="text-btn" data-view="trades">Inspect trades →</button></div><div class="big-chart">${bigChart(m.equityCurve)}</div></div>
<div class="panel intelligence"><div class="panel-head"><div><span class="kicker">AI INTELLIGENCE</span><h2>What matters now</h2></div><span class="ai-orb">✦</span></div><div class="signal"><span class="signal-icon">↑</span><div><b>Edge detected</b><p>${m.bestInstrument} is your strongest instrument by net P&L.</p></div></div><div class="signal"><span class="signal-icon">◈</span><div><b>Session pattern</b><p>${m.bestSession} is currently your strongest session.</p></div></div><div class="signal"><span class="signal-icon warn">!</span><div><b>Sample size</b><p>${trades.length<20?"Import more history before trusting a pattern.":"The dataset is large enough for richer behavioral analysis."}</p></div></div><button class="ai-button" id="openAI">Open AI Trading Analyst <span>↗</span></button></div></section>
<section class="dashboard-grid lower"><div class="panel"><div class="panel-head"><div><span class="kicker">CONNECTED CAPITAL</span><h2>Accounts</h2></div><button class="text-btn" data-view="accounts">View all →</button></div><div class="account-list">${accounts.map(a=>`<div class="account-row"><div class="account-id"><span class="account-icon">${(a.platform||"I")[0]}</span><div><b>${esc(a.name)}</b><small>${esc(a.platform||"Imported")} · <em>${a.trades} trades</em></small></div></div><div class="account-value"><b>${a.balance?money(a.balance):"Data only"}</b><small class="${a.pnl>=0?"up":"down"}">${signed(a.pnl)}</small></div></div>`).join("")}</div></div>
<div class="panel"><div class="panel-head"><div><span class="kicker">EXECUTION FEED</span><h2>Recent trades</h2></div><button class="text-btn" data-view="trades">View all →</button></div><div class="trade-list">${trades.slice(0,5).map(t=>`<button class="trade-row clickable" data-trade="${esc(t.id)}"><div><b>${esc(t.symbol)}</b><small><span class="${t.side==="BUY"?"up":"down"}">${t.side}</span> · ${esc(t.time)} · ${esc(t.session)}</small></div><strong class="${t.pnl>=0?"up":"down"}">${signed(t.pnl)}</strong></button>`).join("")}</div></div></section>`,
accounts:(trades,m,accounts)=>`<div class="page-title"><div><div class="kicker">CAPITAL MAP</div><h1>All accounts</h1><p class="sub">One portfolio view across your trading activity.</p></div><button class="primary" id="importAccounts">+ Import trades</button></div><div class="account-cards">${accounts.map(a=>`<div class="account-card"><div class="account-top"><span class="account-icon big">${(a.platform||"I")[0]}</span><span class="status">${a.status||"IMPORTED"}</span></div><h3>${esc(a.name)}</h3><small>${esc(a.platform||"Imported account")}</small><div class="card-balance">${a.balance?money(a.balance):"Activity linked"}</div><div class="account-bottom"><span>P&L <b class="${a.pnl>=0?"up":"down"}">${signed(a.pnl)}</b></span><span>Trades <b>${a.trades}</b></span></div></div>`).join("")}</div>`,
trades:(trades,m)=>`<div class="page-title"><div><div class="kicker">EXECUTION LEDGER</div><h1>Trade intelligence</h1><p class="sub">${trades.length} executions · click a trade to inspect the context behind it.</p></div><div><button class="ghost" id="importTrades">Import CSV</button></div></div><div class="filter-bar">${filterSelect("account","ACCOUNT")}${filterSelect("symbol","SYMBOL")}${filterSelect("session","SESSION")}<button class="ghost" id="clearFilters">Clear</button></div><div class="panel table-panel"><div class="table-head"><span>SYMBOL</span><span>SIDE</span><span>SESSION</span><span>TIME</span><span>P&L</span></div>${trades.map(t=>`<button class="table-row clickable" data-trade="${esc(t.id)}"><b>${esc(t.symbol)}</b><span class="${t.side==="BUY"?"up":"down"}">${t.side}</span><span>${esc(t.session)}</span><span>${esc(t.time)}</span><strong class="${t.pnl>=0?"up":"down"}">${signed(t.pnl)}</strong></button>`).join("")||"<div class='empty-state'>No trades match these filters.</div>"}</div>`,
analytics:(trades,m)=>`<div class="page-title"><div><div class="kicker">BEHAVIORAL ANALYTICS</div><h1>Your trading fingerprint</h1><p class="sub">Patterns calculated directly from execution history, not assumptions.</p></div></div><div class="analytics-grid"><div class="panel"><span class="kicker">SESSION EDGE</span><h2>${esc(m.bestSession)}</h2><div class="score up">${m.bestSession==="—"?"—":signed(trades.filter(t=>t.session===m.bestSession).reduce((s,t)=>s+t.pnl,0))}</div><p class="sub">Net P&L in your strongest session.</p></div><div class="panel"><span class="kicker">BEST INSTRUMENT</span><h2>${esc(m.bestInstrument)}</h2><div class="score up">${m.bestInstrument==="—"?"—":signed(trades.filter(t=>t.symbol===m.bestInstrument).reduce((s,t)=>s+t.pnl,0))}</div><p class="sub">Net P&L from your strongest instrument.</p></div><div class="panel"><span class="kicker">CONSISTENCY</span><h2>${trades.length>=20?"Model ready":"Building model"}</h2><div class="score">${trades.length>=20?"82 / 100":Math.round(Math.min(trades.length/20*82,81))+"%"}</div><div class="meter"><i style="width:${Math.min(trades.length/20*82,82)}%"></i></div><p class="sub">Confidence rises as more executions arrive.</p></div><div class="panel"><span class="kicker">RISK PROFILE</span><h2>${m.avgR>=0?"Positive expectancy":"Negative expectancy"}</h2><div class="score">${m.avgR>=0?"+":""}${m.avgR.toFixed(2)}R</div><p class="sub">Average R across the selected trade set.</p></div></div>`,
insights:(trades,m)=>`<div class="page-title"><div><div class="kicker">TRADING INTELLIGENCE</div><h1>AI analyst</h1><p class="sub">The first layer of a coach built from your actual execution history.</p></div></div><div class="analyst"><div class="analyst-orb">✦</div><h2>Your data has a story. Trading Hub is learning its vocabulary.</h2><p>Across <b>${trades.length} trades</b>, your strongest observed instrument is <b>${esc(m.bestInstrument)}</b> and your strongest session is <b>${esc(m.bestSession)}</b>. The next layer will compare setups, risk, timing and outcomes to explain <i>why</i> those patterns occur.</p><div class="analyst-grid"><div><span>EDGE</span><b>${esc(m.bestInstrument)}</b></div><div><span>SESSION</span><b>${esc(m.bestSession)}</b></div><div><span>EXPECTANCY</span><b>${m.avgR>=0?"+":""}${m.avgR.toFixed(2)}R</b></div></div><button class="ai-button" id="importAI">Import more data <span>↗</span></button></div>`
};

function spark(points){return '<svg viewBox="0 0 520 150" preserveAspectRatio="none"><path class="spark-line" d="'+linePath(points,520,130,12)+'"/></svg>';}
function bigChart(points){return '<div class="chart-grid"><i></i><i></i><i></i><i></i></div><svg viewBox="0 0 900 300" preserveAspectRatio="none"><path class="line2" d="'+linePath(points,900,270,15)+'"/></svg><div class="axis"><span>START</span><span>EXECUTIONS</span><span>NOW</span></div>';}
function linePath(points,w,h,pad){
 if(!points?.length)return `M0 ${h/2} L${w} ${h/2}`;
 const vals=points.map(x=>x.equity),min=Math.min(0,...vals),max=Math.max(1,...vals),range=max-min||1;
 return points.map((x,i)=>{const px=pad+(i/(Math.max(points.length-1,1)))*(w-pad*2),py=h-pad-((x.equity-min)/range)*(h-pad*2);return (i?"L":"M")+px.toFixed(1)+" "+py.toFixed(1);}).join(" ");
}

function openImport(){state.importOpen=true;render();}
function bind(){
 document.querySelectorAll("[data-view]").forEach(el=>el.onclick=()=>{state.view=el.dataset.view;state.selectedTrade=null;render();});
 document.querySelectorAll("[data-trade]").forEach(el=>el.onclick=()=>{state.selectedTrade=state.trades.find(t=>String(t.id)===String(el.dataset.trade))||null;render();});
 ["importTop","importAccounts","importTrades","importAI","connectTop"].forEach(id=>{const el=document.getElementById(id);if(el)el.onclick=openImport;});
 document.querySelectorAll("[data-filter]").forEach(el=>el.onchange=()=>{state.filters[el.dataset.filter]=el.value;render();});
 const clear=document.getElementById("clearFilters");if(clear)clear.onclick=()=>{state.filters={account:"ALL",symbol:"ALL",session:"ALL"};render();};
 const close=document.getElementById("closeModal"),cancel=document.getElementById("cancelImport");if(close)close.onclick=cancel.onclick=()=>{state.importOpen=false;render();};
 const closeD=document.getElementById("closeDrawer"),back=document.getElementById("drawer");if(closeD)closeD.onclick=()=>{state.selectedTrade=null;render();};if(back)back.onclick=e=>{if(e.target===back){state.selectedTrade=null;render();}};
 const file=document.getElementById("csvFile");
 const drop=document.getElementById("dropzone");
 if(drop){drop.ondragover=e=>{e.preventDefault();drop.classList.add("dragging")};drop.ondragleave=()=>drop.classList.remove("dragging");drop.ondrop=e=>{e.preventDefault();drop.classList.remove("dragging");const f=e.dataTransfer.files[0];if(f)handleFile(f);}}
 if(file)file.onchange=e=>{if(e.target.files[0])handleFile(e.target.files[0]);};
 const demo=document.getElementById("importDemo");if(demo)demo.onclick=()=>{resetTrades();state.trades=getTrades();state.importOpen=false;render();};
 const ask=document.getElementById("askTrade");if(ask)ask.onclick=()=>{state.selectedTrade=null;state.view="insights";render();};
}
async function handleFile(file){
 const status=document.getElementById("importStatus");if(status)status.innerHTML='<div class="import-loading">Reading '+esc(file.name)+'…</div>';
 const parsed=parseCSV(await file.text());
 if(!parsed.length){if(status)status.innerHTML='<div class="import-error">No recognizable executions found. Try a CSV with Symbol, Side, Entry, Exit, Volume or P&L columns.</div>';return;}
 const existing=state.trades.filter(t=>!String(t.id||"").startsWith("TH-"));
 state.trades=[...parsed,...existing];saveTrades(state.trades);
 if(status)status.innerHTML='<div class="import-success">✓ Imported '+parsed.length+' trades. Intelligence updated.</div>';
 setTimeout(()=>{state.importOpen=false;render();},700);
}
render();
