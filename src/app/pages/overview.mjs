import * as store from "../store.mjs";
import { esc, fmt, tone, icon, panel, stat, dir, stageBadge, outcomeBadge, lifecycle, spark, hbars, seg, guard, empty, unavailable, sourceNote, tierBadge, skeleton, confPill } from "../ui.mjs";
import { FEATURED, lifecycleOf, radarRank, rCurve, rStats, tradeCurve, pnlSince, signalOutcome, signalR, strategyTier, ago, biasOf } from "../model.mjs";
import { equityChart } from "../charts.mjs";
import { getTrades, calculateMetrics } from "../../data.js";
import { openMarket, openSignal } from "./common.mjs";

export const subtitle = "Command centre · live engine data";
export const need = ["signals", "bank", "intel", "strategies"];
const DAY = 864e5;

export function mount(root) {
  let perfSource = localStorage.getItem("td_ov_src") || "signals", period = localStorage.getItem("td_ov_period") || "1M", chart = null;
  const trades = getTrades();
  const tCurve = tradeCurve(trades);

  root.innerHTML = `
    <div class="ph"><div><h1>Command centre</h1><p>Live market state, the recorded signal book and system health. Every figure is sourced from the engine or your journal; anything missing is marked unavailable.</p></div>
      <div class="ph-a"><button class="btn" id="ovRefresh">${icon("refresh")}Refresh</button><button class="btn primary" data-goto="radar">${icon("radar")}Open Market Radar</button></div></div>
    <div id="ovStats"></div>
    <section class="panel mt flush"><header class="panel-h"><div><span class="kicker">Market overview</span><h2>Monitored instruments</h2></div><div class="panel-a" id="ovMkMeta"></div></header><div class="panel-b"><div class="mkts" id="ovMarkets"></div></div></section>
    <div class="grid g-12 mt">
      <div class="c-8">${panel({ kicker: "Performance", title: "Equity curve", id: "ovPerf", actions: seg("ovSrc", [["signals", "Signal record · R"], ["journal", "Journal · USD"]], perfSource) + seg("ovPer", [["1W", "1W"], ["1M", "1M"], ["3M", "3M"], ["ALL", "All"]], period), body: `<div id="ovPerfStats" class="toolbar" style="margin-bottom:8px"></div><div class="chart" id="ovChart"></div><div id="ovPerfNote"></div>` })}</div>
      <div class="c-4">${panel({ kicker: "Market Radar", title: "Opportunities", cls: "flush", actions: `<button class="btn sm ghost" data-goto="radar">All ${icon("chevron")}</button>`, body: `<div id="ovRadar"></div>` })}</div>
      <div class="c-8">${panel({ kicker: "Signal Centre", title: "Recent signals", cls: "flush", actions: `<button class="btn sm ghost" data-goto="signals">Signal Centre ${icon("chevron")}</button>`, body: `<div id="ovSignals"></div>` })}</div>
      <div class="c-4">${panel({ kicker: "Infrastructure", title: "System health", cls: "flush", body: `<div id="ovHealth"></div>` })}</div>
      <div class="c-12">${panel({ kicker: "Strategy performance", title: "Live signal record by strategy", actions: `<button class="btn sm ghost" data-goto="lab">Strategy Lab ${icon("chevron")}</button>`, body: `<div id="ovStrat"></div>` })}</div>
    </div>`;

  root.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => window.tdGo(b.dataset.goto));
  root.querySelector("#ovRefresh").onclick = () => store.refreshAll();
  root.querySelectorAll('[data-seg="ovSrc"] button').forEach(b => b.onclick = () => { perfSource = b.dataset.v; localStorage.setItem("td_ov_src", perfSource); segOn("ovSrc", perfSource); drawPerf(); });
  root.querySelectorAll('[data-seg="ovPer"] button').forEach(b => b.onclick = () => { period = b.dataset.v; localStorage.setItem("td_ov_period", period); segOn("ovPer", period); drawPerf(); });
  const segOn = (n, v) => root.querySelectorAll(`[data-seg="${n}"] button`).forEach(x => x.classList.toggle("on", x.dataset.v === v));
  const $ = id => root.querySelector("#" + id);

  function drawStats() {
    const sc = store.get("scalper");
    const acct = sc.data?.account, risk = sc.data?.risk;
    const eq = Number.isFinite(risk?.equity) ? risk.equity : acct?.balance;
    const age = sc.data?.heartbeat_age_seconds;
    const m = calculateMetrics(trades);
    const d = pnlSince(tCurve, DAY), w = pnlSince(tCurve, 7 * DAY), mo = pnlSince(tCurve, 30 * DAY);
    const last = tCurve.at(-1);
    const jsub = n => n.trades ? n.trades + " trade" + (n.trades === 1 ? "" : "s") : last ? "No trades · last " + fmt.date(last.t) : "No journal trades";
    $("ovStats").innerHTML = `<div class="stats">
      ${Number.isFinite(eq)
        ? stat({ label: "Account equity", value: fmt.money(eq, acct?.currency), num: eq, key: "eq", cls: "hero", sub: `cTrader ${acct?.is_live === false ? "demo" : ""} · ${Number.isFinite(age) && age < 180 ? "live" : "last report " + ago(Date.now() - age * 1000)}`, title: acct?.verification || "" })
        : stat({ label: "Account equity", value: '<span class="na">Unavailable</span>', sub: sc.status === "error" ? "cTrader journal unreachable" : "No broker account reported", cls: "hero" })}
      ${stat({ label: "Today's P&L", value: `<span class="${tone(d.pnl)}">${fmt.money(d.pnl, "USD", true)}</span>`, num: d.pnl, key: "d", sub: jsub(d) })}
      ${stat({ label: "Weekly P&L", value: `<span class="${tone(w.pnl)}">${fmt.money(w.pnl, "USD", true)}</span>`, num: w.pnl, key: "w", sub: jsub(w) })}
      ${stat({ label: "Monthly P&L", value: `<span class="${tone(mo.pnl)}">${fmt.money(mo.pnl, "USD", true)}</span>`, num: mo.pnl, key: "m", sub: jsub(mo) })}
      ${stat({ label: "Win rate", value: trades.length ? fmt.pct(m.winRate, 1, false) : '<span class="na">—</span>', sub: trades.length ? `${m.wins}W · ${m.losses}L · journal` : "No journal trades" })}
      ${stat({ label: "Max drawdown", value: trades.length ? `<span class="down">${fmt.money(-m.maxDrawdown)}</span>` : '<span class="na">—</span>', sub: "Peak-to-trough · journal" })}
    </div>${sourceNote(`P&L, win rate and drawdown come from your executed-trade journal (${trades.length} trades; import more in Trade History). Equity is the broker-reported balance from the cTrader journal.`)}`;
  }

  let sparks = {}, sparksStarted = false;
  async function loadSparks() {
    const have = new Set((store.data("radar")?.markets || []).map(m => m.symbol));
    if (!have.size || sparksStarted) return;
    sparksStarted = true;
    await Promise.all(FEATURED.filter(s => have.has(s)).map(async s => {
      const r = await store.candles(s, "H1", 48, { maxAge: 300000 });
      sparks[s] = r.ok ? r.candles.map(c => c.close) : null;
    }));
    if (root.isConnected) drawMarkets();
  }
  function drawMarkets() {
    const r = store.get("radar");
    const by = Object.fromEntries((r.data?.markets || []).map(m => [m.symbol, m]));
    $("ovMkMeta").innerHTML = r.data?.scan ? `<span class="chip"><span class="dot ${r.data.scan.status === "FRESH" ? "ok" : "warn"}"></span>Scan #${esc(r.data.scan.sequence)} · ${ago(r.data.scan.completed_at)}</span>` : "";
    if (!r.data) { $("ovMarkets").innerHTML = r.status === "error" ? `<div style="grid-column:1/-1">${unavailable("Live prices", r.error)}</div>` : FEATURED.map(() => `<div class="mkt">${skeleton(3)}</div>`).join(""); return; }
    $("ovMarkets").innerHTML = FEATURED.map(s => {
      const m = by[s];
      if (!m) return `<div class="mkt"><div class="mkt-top"><span class="sym">${s}</span></div><div class="px na">Not on watchlist</div><small class="muted">The engine does not scan ${s}.</small></div>`;
      const st = lifecycleOf(m), b = biasOf(m);
      return `<div class="mkt" data-sym="${s}" tabindex="0" role="button" aria-label="${s} details">
        <div class="mkt-top"><span class="sym">${s}</span><span class="chg ${tone(m.change_pct)}">${fmt.pct(m.change_pct)}</span></div>
        <div class="px" data-num="${m.price}" data-key="px-${s}">${fmt.price(m.price, s, m.digits)}</div>
        ${sparks[s] ? spark(sparks[s], { w: 160, h: 34 }) : sparks[s] === null ? '<div class="spark" style="height:34px;display:grid;place-items:center;font-size:10px;color:var(--t4)">H1 history unavailable</div>' : `<div style="height:34px;margin-top:6px">${skeleton(1, 6)}</div>`}
        <div class="mkt-foot"><span class="${b === "BULLISH" ? "up" : b === "BEARISH" ? "down" : ""}">${b}</span>${lifecycle(st, true)}</div></div>`;
    }).join("");
    $("ovMarkets").querySelectorAll("[data-sym]").forEach(el => { el.onclick = () => openMarket(by[el.dataset.sym]); el.onkeydown = e => { if (e.key === "Enter") openMarket(by[el.dataset.sym]); }; });
  }

  function drawRadar() {
    const r = store.get("radar");
    $("ovRadar").innerHTML = guard(r, d => {
      const rows = (d.markets || []).filter(m => lifecycleOf(m) !== "IDLE").sort(radarRank).slice(0, 7);
      if (!rows.length) return empty("No developing or confirmed opportunities", "The scanner is watching; nothing has progressed past observation.");
      const intel = Object.fromEntries((store.data("intel")?.markets || []).map(x => [x.symbol, x.confluence]));
      return `<div class="opps">${rows.map(m => { const st = lifecycleOf(m), c = intel[m.symbol]; return `<div class="opp" data-sym="${esc(m.symbol)}"><span class="sym">${esc(m.symbol)}</span>${st === "WATCHING" ? '<span class="muted" style="font:10px var(--mono)">CONTEXT</span>' : dir(m.direction)}<div style="min-width:0">${lifecycle(st, true)}<p><b style="color:var(--t2);font-weight:500">${esc(st[0] + st.slice(1).toLowerCase())}</b> · ${esc(m.setup || m.stage || "")}</p></div>${c && c.classification !== "NONE" ? confPill(c) : `<span class="score" title="Scanner score"><i style="--w:${Math.max(0, Math.min(100, m.score || 0))}%"></i>${fmt.int(m.score)}</span>`}</div>`; }).join("")}</div>`;
    }, "Market Radar");
    $("ovRadar").querySelectorAll("[data-sym]").forEach(el => el.onclick = () => openMarket(r.data.markets.find(m => m.symbol === el.dataset.sym)));
  }

  function drawSignals() {
    const e = store.get("signals");
    $("ovSignals").innerHTML = guard(e, d => {
      const rows = (d.signals || []).slice(0, 8);
      if (!rows.length) return empty("No signals recorded yet");
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Time</th><th>Instrument</th><th>Side</th><th class="r">Entry</th><th class="r">SL</th><th class="r">TP</th><th>Strategy</th><th>Status</th><th class="r">R</th></tr></thead><tbody>
        ${rows.map(s => `<tr class="click" data-sig="${esc(s.signal_id)}"><td class="num muted">${fmt.dt(s.confirmed_at).slice(5)}</td><td><span class="sym">${esc(s.symbol)}</span></td><td>${dir(s.direction)}</td><td class="r">${fmt.price(s.entry, s.symbol)}</td><td class="r down">${fmt.price(s.stop_loss, s.symbol)}</td><td class="r up">${fmt.price(s.take_profit, s.symbol)}</td><td style="max-width:180px;overflow:hidden;text-overflow:ellipsis">${esc(s.strategy_name)}</td><td>${outcomeBadge(signalOutcome(s))}</td><td class="r ${tone(signalR(s))}">${fmt.r(signalR(s))}</td></tr>`).join("")}
      </tbody></table></div><div class="tbl-foot"><span>${esc(d.basis || "")}</span></div>`;
    }, "Signal feed");
    $("ovSignals").querySelectorAll("[data-sig]").forEach(r => r.onclick = () => { const all = store.data("signals")?.signals || []; openSignal(all.find(s => s.signal_id === r.dataset.sig), all); });
  }

  function drawHealth() {
    const h = store.get("health"), sc = store.get("scalper"), d = h.data;
    const row = (state, name, detail) => `<div class="hrow"><span class="dot ${state}"></span><div><b>${name}</b><small title="${esc(detail)}">${esc(detail)}</small></div></div>`;
    if (!d) { $("ovHealth").innerHTML = h.status === "error" ? unavailable("Engine health", h.error) : skeleton(5); return; }
    const fr = d.data_freshness || {}, bank = d.strategy_bank || {}, tg = d.telegram_alerts || {};
    const age = sc.data?.heartbeat_age_seconds;
    $("ovHealth").innerHTML = `<div class="health">
      ${row(h.status === "ok" ? "ok" : "bad", "Engine API", h.status === "ok" ? `v${d.engine_version} · up since ${fmt.time(d.uptime_started)}` : h.error)}
      ${row(d.scanner_status === "READY" ? (fr.status === "FRESH" ? "ok" : "warn") : "bad", "Scanner", `${d.scanner_status} · ${fr.market_count ?? "—"} mkts · ${fr.age_seconds != null ? Math.round(fr.age_seconds) + "s old" : "no scan"}`)}
      ${row(d.mt5_connected ? "ok" : "bad", "MT5 data feed", `${d.mt5_status} · ${d.symbols || 0} symbols · ${d.terminal?.version || ""}`)}
      ${row(sc.data && Number.isFinite(age) && age < 180 ? "ok" : sc.data ? "warn" : "off", "cTrader", sc.data ? `${sc.data.bot_status} · heartbeat ${Number.isFinite(age) ? ago(Date.now() - age * 1000) : "never"}` : "journal unavailable")}
      ${row(bank.running ? (bank.last_error ? "warn" : "ok") : "off", "Strategy bank", bank.running ? `scan ${ago(bank.last_scan_at)}${bank.last_error ? " · " + bank.last_error : ""}` : "not running")}
      ${row(tg.running ? "ok" : "off", "Telegram alerts", tg.configured ? (tg.running ? "running · tick " + ago(tg.last_tick_at) : "stopped") : "not configured")}
      ${row(d.signal_outcomes?.running ? "ok" : "off", "Outcome tracker", d.signal_outcomes?.running ? `${d.signal_outcomes.outstanding ?? 0} outstanding · ${ago(d.signal_outcomes.last_run_at)}` : "not running")}
      ${row("ok", "Execution", d.execution_enabled ? "ENABLED" : "Disabled by design · signals only")}
    </div>`;
  }

  function drawStrategies() {
    const e = store.get("bank");
    $("ovStrat").innerHTML = guard(e, d => {
      const rows = (d.strategies || []).filter(s => s.resolved > 0).sort((a, b) => (b.expectancy_r ?? -9) - (a.expectancy_r ?? -9));
      if (!rows.length) return empty("No resolved strategy signals yet");
      const tiers = Object.fromEntries((store.data("strategies")?.strategies || []).map(x => [x.key, x.evidence?.tier]));
      return hbars(rows.map(s => ({ label: `${tierBadge(tiers[s.key] || strategyTier(s.qualification))}<span>${esc(s.name)}</span>`, value: s.expectancy_r, meta: `${fmt.ratio(s.win_rate, 0)} win · ${s.resolved} res. · ${fmt.r(s.total_r, 1)} total`, title: s.name })), { fmtV: v => fmt.r(v, 2) })
        + sourceNote("Expectancy per resolved signal (R). Live hypothetical signal outcomes recorded since each strategy began alerting — not executed trades, and small samples are noisy. Badges show the evidence tier from the Strategy Lab's historical validation.");
    }, "Strategy record");
  }

  async function drawPerf() {
    chart?.destroy(); chart = null;
    const el = $("ovChart"), statsEl = $("ovPerfStats"), note = $("ovPerfNote");
    const since = { "1W": 7, "1M": 30, "3M": 90, ALL: 1e5 }[period] * DAY;
    let points = [], unit = "", prec = 2, stats = "", src = "";
    if (perfSource === "signals") {
      const e = store.get("signals");
      if (!e.data) { el.innerHTML = e.status === "error" ? `<div class="chart-msg">${esc(e.error)}</div>` : `<div class="chart-msg">${skeleton(2)}</div>`; statsEl.innerHTML = ""; return; }
      const curve = rCurve(e.data.signals || []).filter(x => x.t >= Date.now() - since);
      let eqv = 0; points = curve.map(x => ({ t: x.t, value: (eqv += x.r) }));
      const s = rStats(curve.map(x => x.r));
      unit = "R"; src = "Hypothetical signal outcomes from the strategy bank's last 300 signals (all strategies). Not executed trades.";
      stats = `<span class="chip">Net <b class="${tone(s.total)}">${fmt.r(s.total, 1)}</b></span><span class="chip">Signals <b>${s.n}</b></span><span class="chip">Win <b>${s.winRate == null ? "—" : fmt.ratio(s.winRate, 1)}</b></span><span class="chip">PF <b>${fmt.num(s.profitFactor, 2)}</b></span><span class="chip">Max DD <b class="down">${fmt.num(-s.maxDrawdown, 1)}R</b></span>`;
    } else {
      const c = tCurve.filter(x => x.t >= Date.now() - since);
      let eqv = 0; points = c.map(x => ({ t: x.t, value: (eqv += x.pnl) }));
      unit = ""; src = `Executed trades in your journal (${trades.length} total).`;
      const s = rStats(c.map(x => x.pnl));
      stats = `<span class="chip">Net <b class="${tone(s.total)}">${fmt.money(s.total, "USD", true)}</b></span><span class="chip">Trades <b>${s.n}</b></span><span class="chip">Win <b>${s.winRate == null ? "—" : fmt.ratio(s.winRate, 1)}</b></span><span class="chip">PF <b>${fmt.num(s.profitFactor, 2)}</b></span>`;
    }
    statsEl.innerHTML = stats;
    note.innerHTML = sourceNote(src);
    if (points.length < 2) { el.innerHTML = `<div class="chart-msg">${icon("info")} Not enough ${perfSource === "signals" ? "resolved signals" : "journal trades"} in this period to draw a curve.${perfSource === "journal" && tCurve.length ? " Last journal trade " + fmt.date(tCurve.at(-1).t) + "." : ""}</div>`; return; }
    el.innerHTML = "";
    points.unshift({ t: points[0].t - 1000, value: 0 });
    chart = await equityChart(el, points, { precision: prec, unit });
  }

  drawStats(); drawMarkets(); drawRadar(); drawSignals(); drawHealth(); drawStrategies(); drawPerf(); loadSparks();
  return {
    keys: ["radar", "signals", "bank", "health", "scalper", "intel", "strategies"],
    update(k) {
      if (k === "radar") { loadSparks(); drawMarkets(); drawRadar(); }
      if (k === "signals") { drawSignals(); if (perfSource === "signals") drawPerf(); }
      if (k === "bank" || k === "strategies") drawStrategies();
      if (k === "intel") drawRadar();
      if (k === "health" || k === "scalper") { drawHealth(); if (k === "scalper") drawStats(); }
    },
    destroy() { chart?.destroy(); },
  };
}
