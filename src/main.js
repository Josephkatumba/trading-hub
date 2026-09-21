import "./styles.css";

const accounts = [
  { name: "Goldimus Funded", platform: "FundedNext", balance: 52140, pnl: 2140, risk: 1.8, status: "LIVE" },
  { name: "Personal Futures", platform: "Tradovate", balance: 12480, pnl: 1480, risk: 0.9, status: "LIVE" },
  { name: "XAUUSD Account", platform: "MT5", balance: 8460, pnl: -340, risk: 2.6, status: "WATCH" }
];

const trades = [
  ["XAUUSD", "BUY", 620, "14:32", "New York"],
  ["NAS100", "SELL", 410, "11:08", "London"],
  ["XAUUSD", "SELL", -185, "16:41", "New York"],
  ["BTCUSD", "BUY", 295, "10:14", "London"],
  ["US500", "SELL", -90, "13:22", "London"]
];

const nav = [
  ["overview", "Overview", "⌂"],
  ["accounts", "Accounts", "◈"],
  ["trades", "Trades", "↗"],
  ["analytics", "Analytics", "◒"],
  ["insights", "AI Intelligence", "✦"]
];

function money(n) {
  return (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString();
}

function render(view = "overview") {
  const content = {
    overview: `
      <section class="command">
        <div>
          <div class="kicker">PORTFOLIO / LIVE INTELLIGENCE</div>
          <h1>Good evening, Joseph.</h1>
          <p class="sub">Your trading ecosystem is synchronized. Here is what the market is telling you.</p>
        </div>
        <div class="command-actions"><button class="ghost">Export report</button><button class="primary" id="connect">+ Connect account</button></div>
      </section>

      <section class="portfolio-card">
        <div class="portfolio-main">
          <div class="tiny">TOTAL EQUITY</div>
          <div class="equity">$73,080<span class="live-dot"></span></div>
          <div class="equity-meta"><span class="up">+$3,280</span><span>+5.72%</span><span class="muted">this period</span></div>
        </div>
        <div class="portfolio-spark">
          <svg viewBox="0 0 520 150" preserveAspectRatio="none">
            <defs><linearGradient id="fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-opacity=".22"/><stop offset="1" stop-opacity="0"/></linearGradient></defs>
            <path class="spark-fill" d="M0 120 C40 112 55 126 92 101 S150 115 190 88 S245 98 282 70 S340 87 374 57 S425 66 465 32 S495 40 520 16 L520 150 L0 150 Z"/>
            <path class="spark-line" d="M0 120 C40 112 55 126 92 101 S150 115 190 88 S245 98 282 70 S340 87 374 57 S425 66 465 32 S495 40 520 16"/>
          </svg>
          <div class="spark-labels"><span>30D AGO</span><span>NOW</span></div>
        </div>
        <div class="portfolio-side"><span>RISK UTILIZATION</span><strong>31%</strong><div class="meter"><i style="width:31%"></i></div><small>Healthy exposure</small></div>
      </section>

      <section class="metric-grid">
        <div class="metric"><span>NET P&L</span><strong class="up">+$3,280</strong><small>Across 3 accounts</small></div>
        <div class="metric"><span>MAX DRAWDOWN</span><strong>2.14%</strong><small>↓ 0.8% vs prior period</small></div>
        <div class="metric"><span>WIN RATE</span><strong>68.4%</strong><small>34 wins / 16 losses</small></div>
        <div class="metric"><span>PROFIT FACTOR</span><strong>2.31</strong><small>Strong consistency</small></div>
        <div class="metric"><span>AVG. R</span><strong>+0.84R</strong><small>Last 50 trades</small></div>
      </section>

      <section class="dashboard-grid">
        <div class="panel wide">
          <div class="panel-head"><div><span class="kicker">PERFORMANCE</span><h2>Equity trajectory</h2></div><div class="seg"><button class="selected">30D</button><button>90D</button><button>ALL</button></div></div>
          <div class="big-chart">
            <div class="chart-grid"><i></i><i></i><i></i><i></i></div>
            <svg viewBox="0 0 900 300" preserveAspectRatio="none">
              <defs><linearGradient id="area2" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-opacity=".18"/><stop offset="1" stop-opacity="0"/></linearGradient></defs>
              <path class="area2" d="M0 255 C45 242 70 260 105 226 S160 245 202 207 S260 230 305 170 S365 195 410 154 S470 174 512 123 S570 150 615 95 S670 126 714 80 S770 94 812 49 S860 64 900 28 L900 300 L0 300 Z"/>
              <path class="line2" d="M0 255 C45 242 70 260 105 226 S160 245 202 207 S260 230 305 170 S365 195 410 154 S470 174 512 123 S570 150 615 95 S670 126 714 80 S770 94 812 49 S860 64 900 28"/>
            </svg>
            <div class="axis"><span>SEP 01</span><span>SEP 08</span><span>SEP 15</span><span>SEP 21</span></div>
          </div>
        </div>

        <div class="panel intelligence">
          <div class="panel-head"><div><span class="kicker">AI INTELLIGENCE</span><h2>What matters now</h2></div><span class="ai-orb">✦</span></div>
          <div class="signal"><span class="signal-icon">↑</span><div><b>Edge detected</b><p>XAUUSD is your strongest instrument this period.</p></div></div>
          <div class="signal"><span class="signal-icon warn">!</span><div><b>Risk drift</b><p>Position sizing rose after two consecutive wins.</p></div></div>
          <div class="signal"><span class="signal-icon">◈</span><div><b>Session pattern</b><p>New York trades are producing 1.7× your London expectancy.</p></div></div>
          <button class="ai-button">Open AI Trading Analyst <span>↗</span></button>
        </div>
      </section>

      <section class="dashboard-grid lower">
        <div class="panel">
          <div class="panel-head"><div><span class="kicker">CONNECTED CAPITAL</span><h2>Accounts</h2></div><button class="text-btn" data-view="accounts">View all →</button></div>
          <div class="account-list">${accounts.map(a => `
            <div class="account-row"><div class="account-id"><span class="account-icon">${a.platform === "MT5" ? "M" : a.platform === "Tradovate" ? "T" : "F"}</span><div><b>${a.name}</b><small>${a.platform} · <em>${a.status}</em></small></div></div><div class="account-value"><b>${money(a.balance)}</b><small class="${a.pnl >= 0 ? "up":"down"}">${a.pnl >= 0 ? "+" : ""}${money(a.pnl)}</small></div></div>`).join("")}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><span class="kicker">EXECUTION FEED</span><h2>Recent trades</h2></div><button class="text-btn" data-view="trades">View all →</button></div>
          <div class="trade-list">${trades.slice(0,4).map(t => `
            <div class="trade-row"><div><b>${t[0]}</b><small><span class="${t[1]==="BUY"?"up":"down"}">${t[1]}</span> · ${t[3]} · ${t[4]}</small></div><strong class="${t[2]>=0?"up":"down"}">${t[2]>=0?"+":""}${money(t[2])}</strong></div>`).join("")}</div>
        </div>
      </section>
    `,
    accounts: `<div class="page-title"><div><div class="kicker">CAPITAL MAP</div><h1>All accounts</h1><p class="sub">Every account, one unified view.</p></div><button class="primary">+ Connect account</button></div><div class="account-cards">${accounts.map(a=>`<div class="account-card"><div class="account-top"><span class="account-icon big">${a.platform[0]}</span><span class="status">${a.status}</span></div><h3>${a.name}</h3><small>${a.platform}</small><div class="card-balance">${money(a.balance)}</div><div class="account-bottom"><span>P&L <b class="${a.pnl>=0?"up":"down"}">${a.pnl>=0?"+":""}${money(a.pnl)}</b></span><span>Risk <b>${a.risk}%</b></span></div></div>`).join("")}</div>`,
    trades: `<div class="page-title"><div><div class="kicker">EXECUTION LEDGER</div><h1>Trade history</h1><p class="sub">A complete record of your execution.</p></div><button class="ghost">Export CSV</button></div><div class="panel table-panel"><div class="table-head"><span>SYMBOL</span><span>SIDE</span><span>SESSION</span><span>TIME</span><span>P&L</span></div>${trades.map(t=>`<div class="table-row"><b>${t[0]}</b><span class="${t[1]==="BUY"?"up":"down"}">${t[1]}</span><span>${t[4]}</span><span>${t[3]}</span><strong class="${t[2]>=0?"up":"down"}">${t[2]>=0?"+":""}${money(t[2])}</strong></div>`).join("")}</div>`,
    analytics: `<div class="page-title"><div><div class="kicker">BEHAVIORAL ANALYTICS</div><h1>Your trading fingerprint</h1><p class="sub">Patterns extracted from your execution data.</p></div></div><div class="analytics-grid"><div class="panel"><span class="kicker">SESSION EDGE</span><h2>New York</h2><div class="score">+1.42R</div><p class="sub">Average expectancy across your recent New York trades.</p></div><div class="panel"><span class="kicker">BEST INSTRUMENT</span><h2>XAUUSD</h2><div class="score up">+$435</div><p class="sub">Average winning trade over the current period.</p></div><div class="panel"><span class="kicker">DISCIPLINE</span><h2>82 / 100</h2><div class="meter"><i style="width:82%"></i></div><p class="sub">Your execution is becoming more consistent.</p></div><div class="panel"><span class="kicker">RISK PROFILE</span><h2>Moderate</h2><div class="risk-bars"><i></i><i></i><i></i><i></i><i></i></div><p class="sub">31% of your defined risk capacity is currently utilized.</p></div></div>`,
    insights: `<div class="page-title"><div><div class="kicker">TRADING INTELLIGENCE</div><h1>AI analyst</h1><p class="sub">A continuously evolving interpretation of your trading data.</p></div></div><div class="analyst"><div class="analyst-orb">✦</div><h2>Your trading is becoming more selective.</h2><p>Across 50 recent trades, your strongest recurring pattern is a preference for XAUUSD setups during the New York session. Your profitability has improved while drawdown has remained controlled.</p><div class="analyst-grid"><div><span>EDGE</span><b>New York + XAUUSD</b></div><div><span>WATCH</span><b>Post-win sizing</b></div><div><span>OPPORTUNITY</span><b>Reduce low-conviction entries</b></div></div><button class="ai-button">Ask anything about my trading ↗</button></div>`
  };

  document.querySelector("#root").innerHTML = `
    <div class="app">
      <aside>
        <div class="brand"><span class="logo-mark">TH</span><div>Trading Hub<small>INTELLIGENCE PLATFORM</small></div></div>
        <div class="workspace"><span>WORKSPACE</span><b>Joseph's Portfolio</b><i>⌄</i></div>
        <nav>${nav.map(n=>`<a class="${view===n[0]?"active":""}" data-view="${n[0]}"><span>${n[2]}</span>${n[1]}</a>`).join("")}</nav>
        <div class="side-section"><span>DISCOVER</span><a data-view="analytics"><span>◎</span>Performance</a><a><span>♢</span>Challenges</a><a><span>◇</span>Marketplace</a></div>
        <div class="side-bottom"><a><span>⚙</span>Settings</a><div class="profile"><div class="avatar">JK</div><div><b>Joseph Katumba</b><small>Pro workspace</small></div><span>•••</span></div></div>
      </aside>
      <main>
        <div class="topline"><span><i class="live-dot"></i> DATA SYNCED 22:59 EAT</span><span>MARKET STATUS <b>OPEN</b></span></div>
        ${content[view]}
      </main>
    </div>`;

  document.querySelectorAll("[data-view]").forEach(el => el.addEventListener("click", () => render(el.dataset.view)));
  const connect = document.querySelector("#connect");
  if (connect) connect.onclick = () => alert("Account connection is next. We will support MT5, cTrader and futures accounts.");
}

render();
