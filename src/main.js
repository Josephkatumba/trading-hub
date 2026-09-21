import "./styles.css";

const accounts = [
  ["Goldimus Funded", "FundedNext", "$52,140", "+$2,140"],
  ["Personal Futures", "Tradovate", "$12,480", "+$1,480"],
  ["XAUUSD Account", "MT5", "$8,460", "-$340"]
];

const trades = [
  ["XAUUSD", "BUY", "+$620", "Today, 14:32"],
  ["NAS100", "SELL", "+$410", "Today, 11:08"],
  ["XAUUSD", "SELL", "-$185", "Yesterday, 16:41"],
  ["BTCUSD", "BUY", "+$295", "Yesterday, 10:14"]
];

const rows = accounts.map(a =>
  '<div class="row"><span><b>' + a[0] + '</b><small>' + a[1] +
  '</small></span><span class="right"><b>' + a[2] +
  '</b><small class="' + (a[3][0] === "+" ? "up" : "down") + '">' +
  a[3] + '</small></span></div>'
).join("");

const tradeRows = trades.map(t =>
  '<div class="row"><span><b>' + t[0] + '</b><small>' + t[1] +
  ' · ' + t[3] + '</small></span><b class="' +
  (t[2][0] === "+" ? "up" : "down") + '">' + t[2] +
  '</b></div>'
).join("");

document.querySelector("#root").innerHTML =
  '<div class="app">' +
    '<aside>' +
      '<div class="brand"><b>TH</b> Trading Hub</div>' +
      '<nav><a class="active">Overview</a><a>Accounts</a><a>Trades</a><a>Analytics</a><a>AI Insights</a></nav>' +
      '<div class="bottom"><a>Settings</a><div class="profile"><i>JK</i><span><strong>Joseph</strong><small>Pro account</small></span></div></div>' +
    '</aside>' +
    '<main>' +
      '<header><div><label>OVERVIEW</label><h1>Your trading command center.</h1></div><button>+ Connect account</button></header>' +
      '<section class="hero"><div><small>Total portfolio equity</small><h2>$73,080</h2><em>+$3,280 this period</em></div><span class="badge">● 3 accounts connected</span></section>' +
      '<section class="stats">' +
        '<div><small>P&L</small><strong>+$3,280</strong><small>Across all accounts</small></div>' +
        '<div><small>Return</small><strong>5.72%</strong><small>Since start</small></div>' +
        '<div><small>Drawdown</small><strong>2.14%</strong><small>Current</small></div>' +
        '<div><small>Win rate</small><strong>68.4%</strong><small>Last 50 trades</small></div>' +
        '<div><small>Profit factor</small><strong>2.31</strong><small>Last 50 trades</small></div>' +
      '</section>' +
      '<section class="grid">' +
        '<div class="panel"><label>PORTFOLIO PERFORMANCE</label><h3>Equity curve</h3><div class="chart"><svg viewBox="0 0 900 260" preserveAspectRatio="none"><path d="M0 220 C90 205 110 225 180 185 S300 210 370 150 S480 175 550 110 S680 145 750 70 S830 100 900 28" fill="none" stroke="currentColor" stroke-width="4"/></svg></div></div>' +
        '<div class="panel"><label>AI INSIGHT</label><h3>What changed?</h3><p>Your strongest performance is coming from <b>XAUUSD</b> during the New York session. Your recent trades show improved consistency, but position size increased after consecutive wins.</p><button class="link">Ask about my trading →</button></div>' +
      '</section>' +
      '<section class="grid">' +
        '<div class="panel"><label>CONNECTED ACCOUNTS</label><h3>Your accounts</h3>' + rows + '</div>' +
        '<div class="panel"><label>RECENT ACTIVITY</label><h3>Latest trades</h3>' + tradeRows + '</div>' +
      '</section>' +
    '</main>' +
  '</div>';
