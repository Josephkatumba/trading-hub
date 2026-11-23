import { getEngineUrl } from "../engine.js";
import { STATUS_TEXT, VERDICT_TEXT, evidenceNote, money, notifiable, num, pct, safetyBanner, signed } from "./scalperModel.mjs";

const POLL_MS = 10_000;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const seen = new Set();
let firstLoad = true;

async function getJson(path) {
  const r = await fetch(getEngineUrl() + path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

function kpi(label, value, note = "") {
  return `<div class="sc-kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<small>${esc(note)}</small>` : ""}</div>`;
}

function renderKpis(s) {
  const p = s.performance, t = s.today, cur = s.account?.currency || "";
  $("sc-kpis").innerHTML = [
    kpi(`Net P&L, all demo${cur ? " (" + cur + ")" : ""}`, money(p.net_pnl), evidenceNote(p.trades)),
    kpi("Today (UTC)", money(t.net_pnl), `${t.trades} closed`),
    kpi("Win rate", pct(p.win_rate)),
    kpi("Profit factor", num(p.profit_factor)),
    kpi("Avg win", money(p.avg_win)),
    kpi("Avg loss", money(p.avg_loss)),
    kpi("Expectancy", p.expectancy_r == null ? "–" : `${signed(p.expectancy_r, 3)} R`),
    kpi("Max drawdown", pct(p.max_drawdown_pct, 2)),
    kpi("Trades / day", num(p.trades_per_day)),
  ].join("");
}

function renderRisk(s) {
  const r = s.risk;
  if (!r) { $("sc-risk").innerHTML = `<dt>No heartbeat yet</dt><dd></dd>`; return; }
  const rows = [
    ["Mode", r.mode], ["Balance", money(r.balance)], ["Equity", money(r.equity)],
    ["Realised today", money(r.realized_today)], ["Open risk to stops", money(r.open_risk)],
    ["Daily loss limit", money(r.daily_limit)], ["Consecutive losses", r.consecutive_losses],
    ["Status", r.halted ? `HALTED: ${r.halt_reason}` : "Scanning"],
  ];
  $("sc-risk").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}

function table(head, rows, numericFrom = 1) {
  if (!rows.length) return `<p class="sc-empty">Nothing yet.</p>`;
  return `<div class="sc-tablewrap"><table><thead><tr>${head.map((h, i) => `<th class="${i >= numericFrom ? "n" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map((c, i) => `<td class="${i >= numericFrom ? "n" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function renderGroups(s) {
  const block = (title, g) => {
    const rows = Object.entries(g || {}).map(([k, v]) => [k, v.trades, money(v.net_pnl), pct(v.win_rate), num(v.profit_factor), v.expectancy_r == null ? "–" : signed(v.expectancy_r, 3)]);
    return `<h3 class="sc-sub">${esc(title)}</h3>` + table([title, "Trades", "Net", "Win", "PF", "Exp R"], rows);
  };
  $("sc-groups").innerHTML = block("Instrument", s.by_symbol) + block("Setup", s.by_setup) + block("Session", s.by_session);
}

function renderOpen(s) {
  $("sc-open").innerHTML = table(["Symbol", "Side", "Units", "Entry", "Stop", "Target", "Net"],
    (s.open_positions || []).map(p => [p.symbol, p.side, p.units, p.entry, p.stop, p.target, money(p.net)]), 2);
}

function renderSignals(s) {
  const d = s.signals.decisions || {};
  const rows = Object.entries(s.signals.skip_reasons || {}).map(([k, v]) => [k, v]);
  $("sc-signals").innerHTML = `<p>${s.signals.total} signals seen · ${d.opened || 0} opened · ${d.skipped || 0} skipped · ${d.order_failed || 0} failed</p>` +
    table(["Skip reason", "Count"], rows);
}

function renderBacktest(s) {
  const b = s.backtest;
  if (!b) { $("sc-backtest").innerHTML = `<p class="sc-empty">No walk-forward report found in ctrader_scalper/reports.</p>`; return; }
  const rows = b.symbols.map(x => {
    const o = x.out_of_sample || {};
    return [x.symbol, VERDICT_TEXT[x.verdict] || x.verdict, o.trades, num(o.profit_factor), o.expectancy_r == null ? "–" : signed(o.expectancy_r, 3), num(o.t_stat), pct(o.return_pct, 2), `${x.configs_profitable_in_sample}/${x.configs_tested}`];
  });
  const port = b.portfolio_oos?.summary;
  $("sc-backtest").innerHTML = table(["Symbol", "Verdict", "OOS trades", "PF", "Exp R", "t-stat", "Return", "Profitable configs in-sample"], rows, 2) +
    (port ? `<p>Combined portfolio out-of-sample: <span class="sc-verdict ${esc(b.portfolio_oos.verdict)}">${esc(VERDICT_TEXT[b.portfolio_oos.verdict] || b.portfolio_oos.verdict)}</span>, ${port.trades} trades, PF ${num(port.profit_factor)}, ${signed(port.expectancy_r, 3)} R per trade, return ${pct(port.return_pct, 2)}, max drawdown ${pct(port.max_drawdown_pct, 2)}.</p>` : "") +
    `<p class="sc-sub">Report ${esc(b.file)} · strategy ${esc(b.strategy_version)} · train ${b.walk_forward?.train_weeks} weeks / test ${b.walk_forward?.test_weeks} weeks. Costs: spread floors, slippage and $3 per $100k commission per side.</p>`;
}

function renderFeed(s) {
  const items = (s.feed || []).map(e => {
    const t = (e.ts || "").slice(5, 16).replace("T", " ");
    let text = e.event;
    if (e.event === "signal") text = `${e.decision} ${e.side} ${e.symbol} ${e.setup} (score ${e.score})${e.error ? " · " + e.error : ""}`;
    else if (e.event === "close") text = `closed ${e.symbol} ${e.reason} · net ${signed(e.net)} · ${num(e.r_multiple)}R`;
    else if (e.event === "start") text = `started · demo verified: ${e.demo_verified} · ${e.symbols}`;
    else if (e.reason || e.message) text = `${e.event}: ${e.reason || e.message}`;
    return `<li><time>${esc(t)}</time>${esc(text)}</li>`;
  });
  $("sc-feed").innerHTML = items.join("") || `<li class="sc-empty">No executions yet.</li>`;
}

// ---- charts (single series line; diverging bars). Hover tooltips on both.
function lineChart(el, points) {
  if (points.length < 2) { el.innerHTML = `<p class="sc-empty">The curve appears after two closed trades.</p>`; return; }
  const W = 640, H = 220, L = 56, R = 12, T = 10, B = 24;
  const ys = points.map(p => p.balance), min = Math.min(...ys), max = Math.max(...ys), pad = (max - min) * 0.1 || 1;
  const y0 = min - pad, y1 = max + pad;
  const x = i => L + (i / (points.length - 1)) * (W - L - R), y = v => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const ticks = [y0, (y0 + y1) / 2, y1];
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Balance after each closed trade">
    <g class="axis">${ticks.map(v => `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)}</text>`).join("")}</g>
    <polyline fill="none" stroke="var(--series)" stroke-width="2" stroke-linejoin="round" points="${points.map((p, i) => `${x(i)},${y(p.balance)}`).join(" ")}"/>
    <line id="sc-cross" stroke="var(--ink-3)" stroke-dasharray="3 3" y1="${T}" y2="${H - B}" visibility="hidden"/>
    <circle id="sc-dot" r="4" fill="var(--series)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" id="sc-hit"/></svg><div class="sc-tip"></div>`;
  const svg = el.querySelector("svg"), tip = el.querySelector(".sc-tip"), cross = svg.querySelector("#sc-cross"), dot = svg.querySelector("#sc-dot");
  svg.querySelector("#sc-hit").addEventListener("pointermove", ev => {
    const box = svg.getBoundingClientRect(), sx = (ev.clientX - box.left) / box.width * W;
    const i = Math.max(0, Math.min(points.length - 1, Math.round((sx - L) / (W - L - R) * (points.length - 1))));
    const p = points[i];
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(p.balance)); dot.setAttribute("visibility", "visible");
    tip.style.display = "block"; tip.innerHTML = `${esc(p.t.slice(0, 16).replace("T", " "))} UTC<br><b>${money(p.balance)}</b>`;
    tip.style.left = `${Math.min(box.width - 140, x(i) / W * box.width + 10)}px`; tip.style.top = `${y(p.balance) / H * box.height - 40}px`;
  });
  svg.querySelector("#sc-hit").addEventListener("pointerleave", () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
}

function barChart(el, days) {
  if (!days.length) { el.innerHTML = `<p class="sc-empty">No closed trades yet.</p>`; return; }
  const W = 640, H = 220, L = 56, R = 12, T = 10, B = 24;
  const m = Math.max(1, ...days.map(d => Math.abs(d.net)));
  const zero = T + (H - T - B) / 2, scale = (H - T - B) / 2 / m;
  const bw = Math.min(28, (W - L - R) / days.length - 2);
  const bars = days.map((d, i) => {
    const cx = L + (i + 0.5) * (W - L - R) / days.length, h = Math.max(1, Math.abs(d.net) * scale);
    const yTop = d.net >= 0 ? zero - h : zero;
    return `<g class="bar" data-i="${i}"><rect x="${cx - bw / 2}" y="${yTop}" width="${bw}" height="${h}" rx="3" fill="${d.net >= 0 ? "var(--pos)" : "var(--neg)"}"/>
      <rect x="${cx - (W - L - R) / days.length / 2}" y="${T}" width="${(W - L - R) / days.length}" height="${H - T - B}" fill="transparent"/></g>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily net P&L, blue profit, orange loss">
    <g class="axis"><line class="gridline" x1="${L}" x2="${W - R}" y1="${zero}" y2="${zero}"/>
    <text x="${L - 6}" y="${T + 10}" text-anchor="end">+${Math.round(m)}</text><text x="${L - 6}" y="${zero + 4}" text-anchor="end">0</text><text x="${L - 6}" y="${H - B}" text-anchor="end">−${Math.round(m)}</text>
    <text x="${L}" y="${H - 6}">${esc(days[0].date)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${esc(days[days.length - 1].date)}</text></g>${bars}</svg><div class="sc-tip"></div>`;
  const tip = el.querySelector(".sc-tip"), svg = el.querySelector("svg");
  svg.querySelectorAll(".bar").forEach(g => {
    g.addEventListener("pointerenter", () => {
      const d = days[+g.dataset.i], box = svg.getBoundingClientRect(), r = g.getBoundingClientRect();
      tip.style.display = "block"; tip.innerHTML = `${esc(d.date)}<br><b>${signed(d.net)}</b> · ${d.trades} trades`;
      tip.style.left = `${Math.min(box.width - 140, r.left - box.left + 8)}px`; tip.style.top = "0px";
    });
    g.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });
}

// ---- notifications
function notify(s) {
  for (const n of notifiable(s.feed).reverse()) {
    if (seen.has(n.key)) continue;
    seen.add(n.key);
    if (firstLoad) continue;   // don't replay history on page open
    const el = document.createElement("div");
    el.className = "sc-toast"; el.innerHTML = `<b>${esc(n.title)}</b>${esc(n.body)}`;
    $("sc-toasts").append(el); setTimeout(() => el.remove(), 12_000);
    try { if (Notification.permission === "granted") new Notification(n.title, { body: n.body }); } catch {}
  }
}

async function loadReport() {
  const day = $("sc-day").value;
  try { const r = await getJson(`/api/scalper/daily-report?date=${encodeURIComponent(day)}`); $("sc-report").textContent = r.markdown; }
  catch (e) { $("sc-report").textContent = String(e.message || e); }
}

async function refresh() {
  try {
    const s = await getJson("/api/scalper/summary");
    const status = $("sc-status");
    status.textContent = STATUS_TEXT[s.bot_status] || s.bot_status;
    status.className = `sc-pill ${s.bot_status}`;
    const b = safetyBanner(s);
    $("sc-banner").className = `sc-banner ${b.level}`; $("sc-banner").textContent = b.text;
    renderKpis(s); renderRisk(s); renderGroups(s); renderOpen(s); renderSignals(s); renderBacktest(s); renderFeed(s);
    lineChart($("sc-equity"), s.equity_curve || []);
    barChart($("sc-daily"), s.daily_pnl || []);
    notify(s);
    firstLoad = false;
  } catch (e) {
    $("sc-status").textContent = "Engine unreachable"; $("sc-status").className = "sc-pill offline";
    $("sc-banner").className = "sc-banner serious";
    $("sc-banner").textContent = `Cannot reach the Trading Hub engine at ${getEngineUrl()}. Start it with START TRADING HUB.bat. (${e.message})`;
  }
}

$("sc-day").value = new Date().toISOString().slice(0, 10);
$("sc-day").addEventListener("change", loadReport);
$("sc-day-dl").addEventListener("click", () => {
  const blob = new Blob([$("sc-report").textContent], { type: "text/markdown" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `tradeden-scalper-${$("sc-day").value}.md` });
  a.click(); URL.revokeObjectURL(a.href);
});
$("sc-notify").addEventListener("click", async () => {
  try { const p = await Notification.requestPermission(); $("sc-notify").textContent = p === "granted" ? "Notifications on" : "Notifications blocked"; } catch {}
});
refresh(); loadReport();
setInterval(refresh, POLL_MS);
setInterval(loadReport, 60_000);
