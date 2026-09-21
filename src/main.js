import "./styles.css";
import { getTrades, saveTrades, resetTrades, parseCSV, calculateMetrics, getAccounts } from "./data.js";

const initialAccounts = [
  { name:"Goldimus Funded", platform:"FundedNext", balance:52140, pnl:2140, risk:1.8, status:"LIVE" },
  { name:"Personal Futures", platform:"Tradovate", balance:12480, pnl:1480, risk:0.9, status:"LIVE" },
  { name:"XAUUSD Account", platform:"MT5", balance:8460, pnl:-340, risk:2.6, status:"WATCH" }
];

let state = { view:"overview", trades:getTrades(), importOpen:false };

const nav = [
  ["overview","Overview","⌂"],["accounts","Accounts","◈"],["trades","Trades","↗"],["analytics","Analytics","◒"],["insights","AI Intelligence","✦"]
];

const money = n => (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString(undefined,{maximumFractionDigits:0});
const pct = n => Number(n || 0).toFixed(1) + "%";

function render() {
  const trades = state.trades;
  const metrics = calculateMetrics(trades);
  const accounts = getAccounts(trades).map((a,i)=>({...a,...(initialAccounts[i] || {}) ,name:a.name, pnl:a.pnl, trades:a.trades}));
  const totalPnl = metrics.pnl;
  const totalEquity = 73080 + (totalPnl - 3280);
  const content = views[state.view](trades,metrics,accounts);

  document.querySelector("#root").innerHTML = `
    <div class="app">
      <aside>
        <div class="brand"><span class="logo-mark">TH</span><div>Trading Hub<small>INTELLIGENCE PLATFORM</small></div></div>
        <div class="workspace"><span>WORKSPACE</span><b>Joseph's Portfolio</b><i>⌄</i></div>
        <nav>${nav.map(n=>`<a class="${state.view===n[0]?"active":""}" data-view="${n[0]}"><span>${n[2]}</span>${n[1]}</a>`).join("")}</nav>
        <div class="side-section"><span>DISCOVER</span><a data-view="analytics"><span>◎</span>Performance</a><a><span>♢</span>Challenges</a><a><span>◇</span>Marketplace</a></div>
        <div class="side-bottom"><a><span>⚙</span>Settings</a><div class="profile"><div class="avatar">JK</div><div><b>Joseph Katumba</b><small>Pro workspace</small></div><span>•••</span></div></div>
      </aside>
      <main>
        <div class="topline"><span><i class="live-dot"></i> DATA ENGINE ACTIVE · ${trades.length} TRADES</span><span>PORTFOLIO P&L <b>${totalPnl >= 0 ? "+" : ""}${money(totalPnl)}</b></span></div>
        ${content}
      </main>
    </div>
    ${state.importOpen ? importModal() : ""}
  `;

  bind();
}

function importModal() {
  return `
    <div class="modal-backdrop" id="modal">
      <div class="modal">
        <button class="modal-close" id="closeModal">×</button>
        <div class="kicker">DATA CONNECTION</div>
        <h2>Import your trading history</h2>
        <p class="sub">Upload a CSV exported from MT5, a broker, a prop firm, or a futures platform. Trading Hub will normalize the trades and calculate your performance.</p>
        <label class="dropzone" id="dropzone">
          <input id="csvFile" type="file" accept=".csv,text/csv" />
          <span class="upload-icon">↑</span>
          <b>Drop CSV here or click to browse</b>
          <small>CSV files · Your data stays in this browser for now</small>
        </label>
        <div id="importStatus"></div>
        <div class="import-actions"><button class="ghost" id="cancelImport">Cancel</button><button class="primary" id="importDemo">Load demo data</button></div>
      </div>
    </div>`;
}

const views = {
  overview:(trades,m,accounts)=>`
    <section class="command"><div><div class="kicker">PORTFOLIO / LIVE INTELLIGENCE</div><h1>Good evening, Joseph.</h1><p class="sub">Your trading ecosystem is synchronized. The data engine is now analyzing your execution.</p></div><div class="command-actions"><button class="ghost" id="importTop">Import trades</button><button class="primary" id="connectTop">+ Connect account</button></div></section>
    <section class="portfolio-card"><div><div class="tiny">TOTAL EQUITY</div><div class="equity">$73,080<span class="live-dot"></span></div><div class="equity-meta"><span class="up">${m.pnl>=0?"+":""}${money(m.pnl)}</span><span>${pct(m.winRate)} win rate</span><span class="muted">from ${trades.length} trades</span></div></div><div class="portfolio-spark"><svg viewBox="0 0 520 150" preserveAspectRatio="none"><path class="spark-line" d="M0 120 C40 112 55 126 92 101 S150 115 190 88 S245 98 282 70 S340 87 374 57 S425 66 465 32 S495 40 520 16"/></svg><div class="spark-labels"><span>HISTORY</span><span>NOW</span></div></div><div class="portfolio-side"><span>PROFIT FACTOR</span><strong>${m.profitFactor.toFixed(2)}</strong><div class="meter"><i style="width:${Math.min(m.profitFactor/3*100,100)}%"></i></div><small>Calculated from your trades</small></div></section>
    <section class="metric-grid"><div class="metric"><span>NET P&L</span><strong class="${m.pnl>=0?"up":"down"}">${m.pnl>=0?"+":""}${money(m.pnl)}</strong><small>Real imported data</small></div><div class="metric"><span>MAX DRAWDOWN</span><strong>${money(m.maxDrawdown)}</strong><small>Peak-to-trough P&L</small></div><div class="metric"><span>WIN RATE</span><strong>${pct(m.winRate)}</strong><small>${m.wins} wins / ${m.losses} losses</small></div><div class="metric"><span>PROFIT FACTOR</span><strong>${m.profitFactor.toFixed(2)}</strong><small>Gross profit / loss</small></div><div class="metric"><span>AVG. R</span><strong>${m.avgR>=0?"+":""}${m.avgR.toFixed(2)}R</strong><small>From imported trades</small></div></section>
    <section class="dashboard-grid"><div class="panel wide"><div class="panel-head"><div><span class="kicker">PERFORMANCE</span><h2>Equity trajectory</h2></div><div class="seg"><button class="selected">ALL</button></div></div><div class="big-chart"><div class="chart-grid"><i></i><i></i><i></i><i></i></div><svg viewBox="0 0 900 300" preserveAspectRatio="none"><path class="line2" d="M0 255 C45 242 70 260 105 226 S160 245 202 207 S260 230 305 170 S365 195 410 154 S470 174 512 123 S570 150 615 95 S670 126 714 80 S770 94 812 49 S860 64 900 28"/></svg><div class="axis"><span>START</span><span>TRADES</span><span>NOW</span></div></div></div><div class="panel intelligence"><div class="panel-head"><div><span class="kicker">AI INTELLIGENCE</span><h2>What matters now</h2></div><span class="ai-orb">✦</span></div><div class="signal"><span class="signal-icon">↑</span><div><b>Edge detected</b><p>${m.bestInstrument} is your strongest instrument by P&L.</p></div></div><div class="signal"><span class="signal-icon">◈</span><div><b>Session pattern</b><p>${m.bestSession} is currently your strongest session.</p></div></div><div class="signal"><span class="signal-icon warn">!</span><div><b>Data quality</b><p>Import more trades to make these insights statistically stronger.</p></div></div><button class="ai-button" id="openAI">Open AI Trading Analyst <span>↗</span></button></div></section>
    <section class="dashboard-grid lower"><div class="panel"><div class="panel-head"><div><span class="kicker">CONNECTED CAPITAL</span><h2>Accounts</h2></div><button class="text-btn" data-view="accounts">View all →</button></div><div class="account-list">${accounts.map(a=>`<div class="account-row"><div class="account-id"><span class="account-icon">${a.platform?.[0]||"I"}</span><div><b>${a.name}</b><small>${a.platform||"Imported"} · <em>${a.trades} trades</em></small></div></div><div class="account-value"><b>${a.balance?money(a.balance):"Data only"}</b><small class="${a.pnl>=0?"up":"down"}">${a.pnl>=0?"+":""}${money(a.pnl)}</small></div></div>`).join("")}</div></div><div class="panel"><div class="panel-head"><div><span class="kicker">EXECUTION FEED</span><h2>Recent trades</h2></div><button class="text-btn" data-view="trades">View all →</button></div><div class="trade-list">${trades.slice(0,5).map(t=>`<div class="trade-row"><div><b>${t.symbol}</b><small><span class="${t.side==="BUY"?"up":"down"}">${t.side}</span> · ${t.time} · ${t.session}</small></div><strong class="${t.pnl>=0?"up":"down"}">${t.pnl>=0?"+":""}${money(t.pnl)}</strong></div>`).join("")}</div></div></section>
  `,
  accounts:(trades,m,accounts)=>`<div class="page-title"><div><div class="kicker">CAPITAL MAP</div><h1>All accounts</h1><p class="sub">Your trading accounts and imported capital activity.</p></div><button class="primary" id="importAccounts">+ Import trades</button></div><div class="account-cards">${accounts.map(a=>`<div class="account-card"><div class="account-top"><span class="account-icon big">${a.platform?.[0]||"I"}</span><span class="status">IMPORTED</span></div><h3>${a.name}</h3><small>${a.platform||"Imported account"}</small><div class="card-balance">${a.balance?money(a.balance):"Activity linked"}</div><div class="account-bottom"><span>P&L <b class="${a.pnl>=0?"up":"down"}">${a.pnl>=0?"+":""}${money(a.pnl)}</b></span><span>Trades <b>${a.trades}</b></span></div></div>`).join("")}</div>`,
  trades:(trades,m)=>`<div class="page-title"><div><div class="kicker">EXECUTION LEDGER</div><h1>Trade history</h1><p class="sub">${trades.length} normalized executions in your workspace.</p></div><div><button class="ghost" id="importTrades">Import CSV</button> <button class="ghost" id="resetData">Reset demo</button></div></div><div class="panel table-panel"><div class="table-head"><span>SYMBOL</span><span>SIDE</span><span>SESSION</span><span>TIME</span><span>P&L</span></div>${trades.map(t=>`<div class="table-row"><b>${t.symbol}</b><span class="${t.side==="BUY"?"up":"down"}">${t.side}</span><span>${t.session}</span><span>${t.time}</span><strong class="${t.pnl>=0?"up":"down"}">${t.pnl>=0?"+":""}${money(t.pnl)}</strong></div>`).join("")}</div>`,
  analytics:(trades,m)=>`<div class="page-title"><div><div class="kicker">BEHAVIORAL ANALYTICS</div><h1>Your trading fingerprint</h1><p class="sub">Patterns calculated directly from your execution history.</p></div></div><div class="analytics-grid"><div class="panel"><span class="kicker">SESSION EDGE</span><h2>${m.bestSession}</h2><div class="score up">+${m.avgR.toFixed(2)}R</div><p class="sub">Current average R across your imported trades.</p></div><div class="panel"><span class="kicker">BEST INSTRUMENT</span><h2>${m.bestInstrument}</h2><div class="score up">${money(trades.filter(t=>t.symbol===m.bestInstrument).reduce((s,t)=>s+t.pnl,0))}</div><p class="sub">Net P&L from your strongest instrument.</p></div><div class="panel"><span class="kicker">DISCIPLINE</span><h2>Data-derived</h2><div class="score">${trades.length >= 20 ? "82 / 100" : "Building"}</div><div class="meter"><i style="width:${Math.min(trades.length/20*82,82)}%"></i></div><p class="sub">The discipline model becomes more useful as trade history grows.</p></div><div class="panel"><span class="kicker">RISK PROFILE</span><h2>Observed</h2><div class="risk-bars"><i></i><i></i><i></i><i></i><i></i></div><p class="sub">Risk behavior will be modeled from position size, R, and drawdown.</p></div></div>`,
  insights:(trades,m)=>`<div class="page-title"><div><div class="kicker">TRADING INTELLIGENCE</div><h1>AI analyst</h1><p class="sub">A continuously evolving interpretation of your trading data.</p></div></div><div class="analyst"><div class="analyst-orb">✦</div><h2>Your data has a story. We're starting to read it.</h2><p>You have ${trades.length} trades in the workspace. Your current strongest instrument is <b>${m.bestInstrument}</b>, while <b>${m.bestSession}</b> is your strongest session by net P&L. Import more history and the analyst will be able to detect deeper behavioral patterns.</p><div class="analyst-grid"><div><span>EDGE</span><b>${m.bestInstrument}</b></div><div><span>SESSION</span><b>${m.bestSession}</b></div><div><span>EXPECTANCY</span><b>${m.avgR.toFixed(2)}R average</b></div></div><button class="ai-button" id="importAI">Import more data <span>↗</span></button></div>`
};

function bind(){
  document.querySelectorAll("[data-view]").forEach(el=>el.onclick=()=>{state.view=el.dataset.view;render();});
  ["importTop","importAccounts","importTrades","importAI"].forEach(id=>{const el=document.getElementById(id);if(el)el.onclick=()=>{state.importOpen=true;render();}});
  const close=document.getElementById("closeModal"),cancel=document.getElementById("cancelImport");
  if(close) close.onclick=cancel.onclick=()=>{state.importOpen=false;render();};
  const file=document.getElementById("csvFile");
  if(file) file.onchange=async e=>{const f=e.target.files[0];if(!f)return;const status=document.getElementById("importStatus");status.innerHTML='<div class="import-loading">Reading '+f.name+'…</div>';const text=await f.text();const parsed=parseCSV(text);if(!parsed.length){status.innerHTML='<div class="import-error">No recognizable trades found. Expected columns such as Symbol, Side, Entry, Exit, Volume and P&L.</div>';return;}state.trades=[...parsed,...state.trades.filter(t=>t.__demo!==true)];saveTrades(state.trades);status.innerHTML='<div class="import-success">✓ Imported '+parsed.length+' trades successfully.</div>';setTimeout(()=>{state.importOpen=false;render();},900);};
  const demo=document.getElementById("importDemo");if(demo)demo.onclick=()=>{resetTrades();state.trades=getTrades();state.importOpen=false;render();};
  const reset=document.getElementById("resetData");if(reset)reset.onclick=()=>{resetTrades();state.trades=getTrades();render();};
  const ai=document.getElementById("openAI");if(ai)ai.onclick=()=>{state.view="insights";render();};
}

render();
