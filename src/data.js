const DEMO_TRADES = [
  { account:"Goldimus Funded", symbol:"XAUUSD", side:"BUY", entry:3342.2, exit:3356.8, volume:0.3, pnl:620, r:1.84, time:"2026-09-21 14:32", session:"New York" },
  { account:"Personal Futures", symbol:"NAS100", side:"SELL", entry:22780, exit:22690, volume:1, pnl:410, r:1.35, time:"2026-09-21 11:08", session:"London" },
  { account:"XAUUSD Account", symbol:"XAUUSD", side:"SELL", entry:3358.4, exit:3364.2, volume:0.2, pnl:-185, r:-0.55, time:"2026-09-20 16:41", session:"New York" },
  { account:"Personal Futures", symbol:"BTCUSD", side:"BUY", entry:115200, exit:116050, volume:0.1, pnl:295, r:0.92, time:"2026-09-20 10:14", session:"London" },
  { account:"Goldimus Funded", symbol:"US500", side:"SELL", entry:6532, exit:6540, volume:1, pnl:-90, r:-0.28, time:"2026-09-18 13:22", session:"London" }
];

export function getTrades() {
  try {
    const saved = localStorage.getItem("th_trades");
    return saved ? JSON.parse(saved) : DEMO_TRADES;
  } catch {
    return DEMO_TRADES;
  }
}

export function saveTrades(trades) {
  localStorage.setItem("th_trades", JSON.stringify(trades));
}

export function resetTrades() {
  localStorage.removeItem("th_trades");
}

export function parseCSV(text) {
  const lines = text.replace(/\r/g, "").split("\n").filter(Boolean);
  if (lines.length < 2) return [];
  const parseLine = line => {
    const out = [];
    let value = "", quoted = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"' && line[i + 1] === '"') { value += '"'; i++; }
      else if (c === '"') quoted = !quoted;
      else if (c === "," && !quoted) { out.push(value.trim()); value = ""; }
      else value += c;
    }
    out.push(value.trim());
    return out;
  };

  const headers = parseLine(lines[0]).map(h => h.toLowerCase().replace(/[^a-z0-9]/g, ""));
  const find = (row, names) => {
    for (const name of names) {
      const i = headers.indexOf(name);
      if (i >= 0) return row[i] ?? "";
    }
    return "";
  };
  const num = value => Number(String(value).replace(/[$,%]/g, "").replace(/,/g, "")) || 0;

  return lines.slice(1).map(rowText => {
    const row = parseLine(rowText);
    const sideRaw = find(row, ["side","direction","type","action"]).toUpperCase();
    const time = find(row, ["time","datetime","date","closetime","opentime"]);
    return {
      account: find(row, ["account","accountname","accountid"]) || "Imported Account",
      symbol: find(row, ["symbol","instrument","market"]) || "UNKNOWN",
      side: sideRaw.includes("SELL") ? "SELL" : "BUY",
      entry: num(find(row, ["entry","entryprice","openprice"])),
      exit: num(find(row, ["exit","exitprice","closeprice"])),
      volume: num(find(row, ["volume","lots","size","quantity"])),
      pnl: num(find(row, ["pnl","profit","profitloss","netprofit"])),
      r: num(find(row, ["r","rr","riskreward"])),
      time: time || new Date().toISOString().slice(0,16).replace("T"," "),
      session: find(row, ["session"]) || inferSession(time)
    };
  }).filter(t => t.symbol !== "UNKNOWN");
}

function inferSession(time) {
  const hour = Number(String(time).match(/(?:T|\s)(\d{1,2})/)?.[1] ?? 12);
  if (hour >= 13 && hour < 18) return "New York";
  if (hour >= 8 && hour < 13) return "London";
  return "Asia";
}

export function calculateMetrics(trades) {
  const pnl = trades.reduce((s,t) => s + t.pnl, 0);
  const wins = trades.filter(t => t.pnl > 0);
  const losses = trades.filter(t => t.pnl < 0);
  const grossProfit = wins.reduce((s,t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((s,t) => s + t.pnl, 0));
  const winRate = trades.length ? wins.length / trades.length * 100 : 0;
  const profitFactor = grossLoss ? grossProfit / grossLoss : 0;
  const avgR = trades.length ? trades.reduce((s,t) => s + (Number(t.r) || 0), 0) / trades.length : 0;

  let peak = 0, equity = 0, maxDrawdown = 0;
  for (const t of [...trades].reverse()) {
    equity += t.pnl;
    peak = Math.max(peak, equity);
    maxDrawdown = Math.max(maxDrawdown, peak - equity);
  }

  const bySymbol = {};
  trades.forEach(t => bySymbol[t.symbol] = (bySymbol[t.symbol] || 0) + t.pnl);
  const bestInstrument = Object.entries(bySymbol).sort((a,b) => b[1]-a[1])[0]?.[0] || "—";

  const bySession = {};
  trades.forEach(t => bySession[t.session] = (bySession[t.session] || 0) + t.pnl);
  const bestSession = Object.entries(bySession).sort((a,b) => b[1]-a[1])[0]?.[0] || "—";

  return { pnl, wins:wins.length, losses:losses.length, winRate, profitFactor, avgR, maxDrawdown, bestInstrument, bestSession };
}

export function getAccounts(trades) {
  const map = new Map();
  trades.forEach(t => {
    if (!map.has(t.account)) map.set(t.account, {name:t.account, platform:"Imported", balance:0, pnl:0, trades:0});
    const a = map.get(t.account);
    a.pnl += t.pnl;
    a.trades++;
  });
  return [...map.values()].map(a => ({...a, balance: a.balance || 0}));
}
