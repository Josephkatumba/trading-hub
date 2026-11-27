import * as store from "../store.mjs";
import { esc, fmt, tone, icon, panel, badge, empty, unavailable, skeleton } from "../ui.mjs";
import { tradeCurve, ago } from "../model.mjs";
import { getTrades, getAccounts } from "../../data.js";
import { filtersHtml, bindFilters, applyFilters, perfDashboard } from "./perfkit.mjs";

export const subtitle = "Executed trades and broker accounts";
export const need = [];

export function mount(root) {
  const trades = getTrades();
  const rows = tradeCurve(trades).map(x => ({ t: x.t, v: x.pnl, symbol: x.trade.symbol, group: x.trade.account || "Unknown", trade: x.trade }));
  const symbols = [...new Set(rows.map(r => r.symbol))].sort(), accounts = [...new Set(rows.map(r => r.group))].sort();
  let destroy = () => {}, filters = {};
  root.innerHTML = `
    <div class="ph"><div><h1>Portfolio</h1><p>Your executed trades (journal) and the broker account reported by the cTrader journal. All amounts are realised P&L in account currency — no simulated or signal results here.</p></div>
      <div class="ph-a"><button class="btn" data-goto="history">${icon("upload")}Import trades</button></div></div>
    <div id="pfAccounts"></div>
    <div class="mt">${filtersHtml("pf", { symbols, groups: accounts, groupLabel: "Account" })}</div>
    <div class="mt" id="pfDash"></div>`;
  root.querySelector("[data-goto]").onclick = () => window.tdGo("history");

  function drawAccounts() {
    const sc = store.get("scalper"), d = sc.data;
    const accts = getAccounts(trades);
    const age = d?.heartbeat_age_seconds;
    const ct = !d ? (sc.status === "error" ? unavailable("cTrader account", sc.error) : skeleton(3)) : `
      <div class="kv">
        <div><span>Broker</span><b style="font-size:12px">${esc(d.account?.broker || "—")}</b></div>
        <div><span>Account</span><b>${esc(d.account?.account || "—")}</b></div>
        <div><span>Type</span><b>${d.account?.is_live === false ? "DEMO" : d.account?.is_live ? "LIVE" : "—"}</b></div>
        <div><span>Balance</span><b>${fmt.money(d.risk?.balance ?? d.account?.balance, d.account?.currency)}</b></div>
        <div><span>Equity</span><b>${fmt.money(d.risk?.equity, d.account?.currency)}</b></div>
        <div><span>Open positions</span><b>${(d.open_positions || []).length}</b></div>
        <div><span>Bot</span><b>${esc(d.bot_status)}</b></div>
        <div><span>Heartbeat</span><b>${Number.isFinite(age) ? ago(Date.now() - age * 1000) : "never"}</b></div>
      </div>
      <p class="source">${icon("info")}<span>${esc(d.account?.verification || "")} · leverage ${esc(d.account?.leverage || "—")} · ${d.risk?.halted ? "risk halt: " + esc(d.risk.halt_reason) : "no risk halt"} · values as of ${fmt.dt(d.risk?.ts || d.account?.ts)} UTC${Number.isFinite(age) && age > 600 ? " — <b>not live</b>" : ""}</span></p>`;
    root.querySelector("#pfAccounts").innerHTML = `<div class="grid g-12">
      <div class="c-6">${panel({ kicker: "Broker account", title: "cTrader", actions: d ? badge(Number.isFinite(age) && age < 180 ? "Connected" : "Last report", Number.isFinite(age) && age < 180 ? "good" : "warn") : "", body: ct })}</div>
      <div class="c-6">${panel({ kicker: "Journal", title: "Accounts in your trade journal", cls: "flush", body: accts.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Account</th><th class="r">Trades</th><th class="r">Realised P&L</th></tr></thead><tbody>${accts.map(a => `<tr><td>${esc(a.name)}</td><td class="r">${a.trades}</td><td class="r ${tone(a.pnl)}">${fmt.money(a.pnl, "USD", true)}</td></tr>`).join("")}</tbody></table></div>` : empty("No journal trades", "Import an MT5 or broker CSV in Trade History.") })}</div>
    </div>`;
  }

  function exposure() {
    const pos = store.data("scalper")?.open_positions || [];
    return `<div class="mt">${panel({ kicker: "Risk exposure", title: "Open positions", cls: "flush", body: pos.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Symbol</th><th>Side</th><th class="r">Volume</th><th class="r">Entry</th><th class="r">SL</th><th class="r">TP</th><th class="r">P&L</th></tr></thead><tbody>${pos.map(p => `<tr><td class="sym">${esc(p.symbol)}</td><td>${esc(p.side || p.direction || "")}</td><td class="r">${fmt.num(p.volume ?? p.lots, 2)}</td><td class="r">${fmt.price(p.entry ?? p.entry_price, p.symbol)}</td><td class="r down">${fmt.price(p.sl ?? p.stop_loss, p.symbol)}</td><td class="r up">${fmt.price(p.tp ?? p.take_profit, p.symbol)}</td><td class="r ${tone(p.pnl ?? p.net_profit)}">${fmt.money(p.pnl ?? p.net_profit, "USD", true)}</td></tr>`).join("")}</tbody></table></div>` : empty("No open positions reported", store.data("scalper") ? `cTrader reports no open positions${store.data("scalper").risk ? ` · open risk ${fmt.money(store.data("scalper").risk.open_risk)}` : ""}. Exposure from other brokers is not connected.` : "Broker position data is unavailable.") })}</div>`;
  }

  function drawDash() {
    destroy();
    destroy = perfDashboard(root.querySelector("#pfDash"), applyFilters(rows, filters), { money: true, groupLabel: "Account", exposure: exposure(), note: `Journal: ${trades.length} executed trades (${trades.filter(t => t.session === "Unverified").length} with unverified session time). Times are UTC where the broker time zone is known.` });
  }
  bindFilters(root, "pf", f => { filters = f; drawDash(); });
  drawAccounts(); drawDash();
  return { keys: ["scalper"], update() { drawAccounts(); }, destroy: () => destroy() };
}
