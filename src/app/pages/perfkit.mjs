// Shared performance dashboard: equity, drawdown, daily bars, monthly table,
// breakdowns and distribution for a list of results {t, v, symbol, group}.
import { equityChart, drawdownChart, barChart } from "../charts.mjs";
import { esc, fmt, tone, icon, panel, stat, hbars, empty } from "../ui.mjs";
import { rStats, groupSum, dayKey, monthKey } from "../model.mjs";

export function filtersHtml(prefix, { symbols, groups, groupLabel }) {
  const opt = (vals, label) => `<option value="">${label}</option>` + vals.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  return `<div class="toolbar">
    <div class="field" title="From date (UTC)"><span class="kicker" style="margin:0">From</span><input type="date" id="${prefix}From"></div>
    <div class="field" title="To date (UTC)"><span class="kicker" style="margin:0">To</span><input type="date" id="${prefix}To"></div>
    <div class="seg" data-seg="${prefix}Quick">${[["7", "7D"], ["30", "30D"], ["90", "90D"], ["", "All"]].map(([v, l]) => `<button data-v="${v}" class="${v === "" ? "on" : ""}">${l}</button>`).join("")}</div>
    <select class="sel" id="${prefix}Sym">${opt(symbols, "All instruments")}</select>
    <select class="sel" id="${prefix}Grp">${opt(groups, "All " + groupLabel.toLowerCase() + "s")}</select>
  </div>`;
}

export function bindFilters(root, prefix, onChange) {
  const $ = id => root.querySelector("#" + prefix + id);
  const st = { from: null, to: null, symbol: "", group: "" };
  const fire = () => onChange({ ...st });
  $("From").onchange = e => { st.from = e.target.value ? Date.parse(e.target.value + "T00:00:00Z") : null; quickOff(); fire(); };
  $("To").onchange = e => { st.to = e.target.value ? Date.parse(e.target.value + "T23:59:59Z") : null; quickOff(); fire(); };
  $("Sym").onchange = e => { st.symbol = e.target.value; fire(); };
  $("Grp").onchange = e => { st.group = e.target.value; fire(); };
  const quick = root.querySelectorAll(`[data-seg="${prefix}Quick"] button`);
  const quickOff = () => quick.forEach(b => b.classList.remove("on"));
  quick.forEach(b => b.onclick = () => {
    quickOff(); b.classList.add("on");
    st.to = null; st.from = b.dataset.v ? Date.now() - Number(b.dataset.v) * 864e5 : null;
    $("From").value = st.from ? new Date(st.from).toISOString().slice(0, 10) : ""; $("To").value = "";
    fire();
  });
  return st;
}

export const applyFilters = (rows, f) => rows.filter(r => (!f.from || r.t >= f.from) && (!f.to || r.t <= f.to) && (!f.symbol || r.symbol === f.symbol) && (!f.group || r.group === f.group));

// Render the full dashboard into `el`. Returns destroy().
export function perfDashboard(el, rows, { unit = "R", money = false, groupLabel = "Strategy", note = "", exposure = "" }) {
  const v = n => money ? fmt.money(n, "USD", true) : fmt.r(n, 2);
  const vPlain = n => money ? fmt.money(n, "USD") : fmt.num(n, 2) + "R";
  const sorted = [...rows].sort((a, b) => a.t - b.t);
  const s = rStats(sorted.map(r => r.v));
  const handles = [];
  if (!sorted.length) { el.innerHTML = `<section class="panel">${empty("No results in this selection", "Widen the date range or clear filters.")}</section>${exposure}`; return () => {}; }
  let eq = 0, peak = 0;
  const curve = sorted.map(r => { eq += r.v; peak = Math.max(peak, eq); return { t: r.t, eq, dd: eq - peak }; });
  const days = groupSum(sorted, r => dayKey(r.t), r => r.v).sort((a, b) => a.key.localeCompare(b.key));
  const months = groupSum(sorted, r => monthKey(r.t), r => r.v).sort((a, b) => b.key.localeCompare(a.key));
  const bySym = groupSum(sorted, r => r.symbol, r => r.v);
  const byGrp = groupSum(sorted, r => r.group, r => r.v);
  const wins = sorted.filter(r => r.v > 0), losses = sorted.filter(r => r.v < 0);
  const avgW = wins.length ? wins.reduce((a, r) => a + r.v, 0) / wins.length : null, avgL = losses.length ? losses.reduce((a, r) => a + r.v, 0) / losses.length : null;
  const best = [...sorted].sort((a, b) => b.v - a.v)[0], worst = [...sorted].sort((a, b) => a.v - b.v)[0];
  let streakW = 0, streakL = 0, cw = 0, cl = 0;
  for (const r of sorted) { if (r.v > 0) { cw++; cl = 0; } else if (r.v < 0) { cl++; cw = 0; } streakW = Math.max(streakW, cw); streakL = Math.max(streakL, cl); }
  // Distribution buckets
  const step = money ? niceStep(Math.max(...sorted.map(r => Math.abs(r.v))) / 6) : 0.5;
  const buckets = new Map();
  for (const r of sorted) { const b = Math.floor(r.v / step) * step; buckets.set(b, (buckets.get(b) || 0) + 1); }
  const bk = [...buckets].sort((a, b) => a[0] - b[0]);
  const maxB = Math.max(...bk.map(x => x[1]));

  el.innerHTML = `
    <div class="stats">
      ${stat({ label: "Net result", value: `<span class="${tone(s.total)}">${v(s.total)}</span>`, sub: `${s.n} ${money ? "trades" : "signals"}`, num: s.total, key: "pk-net" })}
      ${stat({ label: "Win rate", value: s.winRate == null ? "—" : fmt.ratio(s.winRate, 1), sub: `${s.wins}W · ${s.losses}L` })}
      ${stat({ label: "Profit factor", value: fmt.num(s.profitFactor, 2), sub: "Gross win / gross loss" })}
      ${stat({ label: "Expectancy", value: `<span class="${tone(s.expectancy)}">${v(s.expectancy)}</span>`, sub: money ? "Per trade" : "Per signal" })}
      ${stat({ label: "Max drawdown", value: `<span class="down">${money ? fmt.money(-s.maxDrawdown) : fmt.num(-s.maxDrawdown, 1) + "R"}</span>`, sub: "Peak-to-trough" })}
      ${stat({ label: "Avg win / loss", cls: "compact", value: `<span class="up">${avgW == null ? "—" : vPlain(avgW)}</span> <span class="muted">/</span> <span class="down">${avgL == null ? "—" : vPlain(avgL)}</span>`, sub: `Streaks ${streakW}W / ${streakL}L` })}
    </div>
    <div class="grid g-12 mt">
      <div class="c-8">${panel({ kicker: "Equity", title: "Equity curve", body: `<div class="chart" data-c="eq"></div>` })}</div>
      <div class="c-4">${panel({ kicker: "Outcomes", title: "Winning vs losing", body: winLoss(s, best, worst, v) })}</div>
      <div class="c-6">${panel({ kicker: "Risk", title: "Drawdown curve", body: `<div class="chart sm" data-c="dd"></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Daily", title: "Daily result", body: `<div class="chart sm" data-c="day"></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Breakdown", title: "By instrument", body: hbars(bySym.map(g => ({ label: `<span class="sym">${esc(g.key)}</span>`, value: g.total, meta: `n=${g.n} · ${Math.round(g.wins / g.n * 100)}% win` })), { fmtV: v }) })}</div>
      <div class="c-6">${panel({ kicker: "Breakdown", title: "By " + groupLabel.toLowerCase(), body: hbars(byGrp.map(g => ({ label: esc(g.key), value: g.total, meta: `n=${g.n} · ${Math.round(g.wins / g.n * 100)}% win`, title: g.key })), { fmtV: v }) })}</div>
      <div class="c-6">${panel({ kicker: "Distribution", title: "Trade distribution", body: `<div class="dist">${bk.map(([b, n]) => `<div class="dist-col" title="${esc(money ? fmt.money(b) + " to " + fmt.money(b + step) : b.toFixed(1) + "R to " + (b + step).toFixed(1) + "R")}: ${n}"><i class="${b >= 0 ? "pos" : "neg"}" style="height:${Math.max(3, n / maxB * 100)}%"></i><span>${money ? compact(b) : b.toFixed(1)}</span></div>`).join("")}</div>` })}</div>
      <div class="c-6">${panel({ kicker: "Calendar", title: "Monthly performance", cls: "flush", body: `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Month</th><th class="r">${money ? "Trades" : "Signals"}</th><th class="r">Win rate</th><th class="r">Result</th></tr></thead><tbody>${months.map(m => `<tr><td class="mono">${m.key}</td><td class="r">${m.n}</td><td class="r">${Math.round(m.wins / m.n * 100)}%</td><td class="r ${tone(m.total)}">${v(m.total)}</td></tr>`).join("")}</tbody></table></div>` })}</div>
    </div>
    ${exposure}
    ${note ? `<p class="source">${icon("info")}<span>${note}</span></p>` : ""}`;
  const prec = 2, u = money ? "" : unit;
  const c = n => el.querySelector(`[data-c="${n}"]`);
  equityChart(c("eq"), curve.map(x => ({ t: x.t, value: x.eq })), { precision: prec, unit: u }).then(h => h && handles.push(h));
  drawdownChart(c("dd"), curve.map(x => ({ t: x.t, value: x.dd })), { precision: prec, unit: u }).then(h => h && handles.push(h));
  barChart(c("day"), days.map(d => ({ time: Date.parse(d.key + "T00:00:00Z") / 1000, value: d.total })), { precision: prec, unit: u }).then(h => h && handles.push(h));
  return () => handles.forEach(h => h.destroy());
}

function winLoss(s, best, worst, v) {
  const w = s.n ? s.wins / s.n * 100 : 0, l = s.n ? s.losses / s.n * 100 : 0;
  return `<div style="display:flex;flex-direction:column;gap:12px">
    <div style="display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--track)"><i style="width:${w}%;background:var(--up)"></i><i style="width:${100 - w - l}%;background:var(--t4)"></i><i style="width:${l}%;background:var(--down)"></i></div>
    <div class="kv"><div><span>Wins</span><b class="up">${s.wins}</b></div><div><span>Losses</span><b class="down">${s.losses}</b></div><div><span>Flat</span><b>${s.n - s.wins - s.losses}</b></div><div><span>Best</span><b class="up">${best ? v(best.v) : "—"}</b><small class="muted">${best ? esc(best.symbol) : ""}</small></div><div><span>Worst</span><b class="down">${worst ? v(worst.v) : "—"}</b><small class="muted">${worst ? esc(worst.symbol) : ""}</small></div></div></div>`;
}
const compact = n => Math.abs(n) >= 1000 ? (n / 1000).toFixed(1) + "k" : Math.round(n);
function niceStep(x) { if (!(x > 0)) return 1; const p = 10 ** Math.floor(Math.log10(x)); const m = x / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; }
