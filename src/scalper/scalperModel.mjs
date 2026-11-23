// Pure presentation helpers for the TradeDen Scalper dashboard (tested in tests/scalperModel.test.mjs).

export const STATUS_TEXT = {
  running: "Running",
  offline: "Offline: no heartbeat for over 3 minutes",
  stopped: "Stopped",
  never_started: "Not started yet",
};

export const VERDICT_TEXT = {
  NO_EDGE: "No edge: loses after costs out-of-sample",
  INSUFFICIENT_EVIDENCE: "Not enough out-of-sample trades to judge",
  PROFITABLE_NOT_SIGNIFICANT: "Profitable out-of-sample but not statistically significant",
  EDGE_CANDIDATE: "Edge candidate: profitable and significant out-of-sample",
};

export function money(v, currency = "") {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "–";
  const n = Number(v);
  const s = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "−" : ""}${currency ? currency + " " : ""}${s}`;
}

export function signed(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "–";
  const n = Number(v);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}`;
}

export function pct(v, digits = 1) {
  return v === null || v === undefined ? "–" : `${Number(v).toFixed(digits)}%`;
}

export function num(v, digits = 2) {
  return v === null || v === undefined ? "–" : Number(v).toFixed(digits);
}

/** Banner describing whether the account is verified demo; never claims more than the journal says. */
export function safetyBanner(summary) {
  if (!summary?.account) return { level: "info", text: "No cBot start record yet. Start TradeDen Scalper in cTrader (DEMO) to populate this page." };
  if (summary.live_account_ever_seen) return { level: "critical", text: "A LIVE account was detected at start. The cBot refused to trade; check which account cTrader is logged into." };
  if (summary.account.demo_verified) return { level: "good", text: `Demo verified by the cBot (${summary.account.verification}). Account ${summary.account.account}, ${summary.account.broker ?? ""}.` };
  return { level: "serious", text: `Demo verification failed: ${summary.account.verification}` };
}

/** Feed entries that deserve a notification, newest first, keyed so each is shown once. */
export function notifiable(feed) {
  return (feed || []).filter(e => (e.event === "signal" && e.decision === "opened") || ["close", "halt", "safety"].includes(e.event))
    .map(e => ({ key: `${e.run_id}|${e.event}|${e.position_id ?? ""}|${e.ts}`, title: notifyTitle(e), body: notifyBody(e) }));
}

function notifyTitle(e) {
  if (e.event === "signal") return `Opened ${e.side} ${e.symbol}`;
  if (e.event === "close") return `Closed ${e.symbol}: ${signed(e.net)}`;
  if (e.event === "halt") return "Trading halted for the day";
  return "Safety event";
}

function notifyBody(e) {
  if (e.event === "signal") return `${e.setup} score ${e.score} · entry ${e.entry} · stop ${e.stop} · risk ${num(e.risk_cash)}`;
  if (e.event === "close") return `${e.reason} · ${num(e.r_multiple)}R`;
  return e.reason || e.message || "";
}

/** Sample-size honesty for live stats. */
export function evidenceNote(trades) {
  if (!trades) return "No closed demo trades yet.";
  if (trades < 30) return `${trades} closed trade${trades === 1 ? "" : "s"}: far too few to judge an edge.`;
  if (trades < 100) return `${trades} closed trades: early evidence; confidence intervals are still wide.`;
  return `${trades} closed trades.`;
}
