import * as store from "../store.mjs";
import { esc, fmt, icon, panel, guard, empty, dir, hbars, sourceNote } from "../ui.mjs";
import { filtersHtml, bindFilters, applyFilters, perfDashboard } from "./perfkit.mjs";

export const subtitle = "Signal-record analytics in R";
export const need = ["signals", "quality"];

export function mount(root) {
  let destroy = () => {}, filters = {}, built = false;
  root.innerHTML = `
    <div class="ph"><div><h1>Analytics</h1><p>Performance analytics of the recorded signal book: equity and drawdown in R, daily and monthly results, instrument and strategy breakdowns, distribution and current exposure.</p></div></div>
    <div class="banner info">${icon("info")}<div><b>Hypothetical outcomes.</b> Each R is the tracked outcome of a recorded signal's plan (target, stop or time exit), not an executed trade. Executed results live in Portfolio.</div></div>
    <div id="anFilters"></div><div class="mt" id="anDash"></div><div class="mt" id="anAudit"></div>`;
  const $ = id => root.querySelector("#" + id);

  const rows = () => (store.data("signals")?.signals || [])
    .filter(s => s.outcome_status && s.outcome_status !== "PENDING" && Number.isFinite(Number(s.r_multiple)))
    .map(s => ({ t: Date.parse(s.outcome_at || s.confirmed_at), v: Number(s.r_multiple), symbol: s.symbol, group: s.strategy_name || s.strategy_key }))
    .filter(r => Number.isFinite(r.t));

  function exposure() {
    const open = (store.data("signals")?.signals || []).filter(s => s.outcome_status === "PENDING");
    const by = {};
    for (const s of open) { const k = s.symbol; by[k] ||= { long: 0, short: 0 }; by[k][s.direction === "LONG" ? "long" : "short"]++; }
    return `<div class="mt">${panel({ kicker: "Risk exposure", title: `Open signals · ${open.length}`, cls: "flush", body: open.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Instrument</th><th class="r">Long</th><th class="r">Short</th><th class="r">Net (1R each)</th><th>Signals</th></tr></thead><tbody>${Object.entries(by).map(([k, v]) => `<tr><td class="sym">${esc(k)}</td><td class="r up">${v.long}</td><td class="r down">${v.short}</td><td class="r">${v.long - v.short > 0 ? "+" : ""}${v.long - v.short}R</td><td>${open.filter(s => s.symbol === k).map(s => dir(s.direction)).join(" ")}</td></tr>`).join("")}</tbody></table></div>` : empty("No open signals", "All recorded signals have resolved.") })}</div>`;
  }

  function build() {
    const data = rows();
    if (!store.data("signals")) { $("anDash").innerHTML = guard(store.get("signals"), () => "", "Signal record"); return; }
    if (!built) {
      $("anFilters").innerHTML = filtersHtml("an", { symbols: [...new Set(data.map(r => r.symbol))].sort(), groups: [...new Set(data.map(r => r.group))].sort(), groupLabel: "Strategy" });
      bindFilters(root, "an", f => { filters = f; draw(); });
      built = true;
    }
    draw();
  }
  function draw() {
    destroy();
    destroy = perfDashboard($("anDash"), applyFilters(rows(), filters), { unit: "R", groupLabel: "Strategy", exposure: exposure(), note: esc(store.data("signals")?.basis || "") + " Covers the latest 300 bank signals." });
  }
  function audit() {
    $("anAudit").innerHTML = panel({ kicker: "Live signal audit", title: "Full live record (production + bank)", body: guard(store.get("quality"), d => {
      const la = d.live_audit; if (!la) return empty("No audit available");
      const o = la.overall || {};
      const row = (name, x) => x ? `<tr><td>${name}</td><td class="r">${fmt.int(x.signals)}</td><td class="r">${fmt.int(x.resolved)}</td><td class="r">${fmt.ratio(x.win_rate, 1)}</td><td class="r">${fmt.ratio(x.breakeven_win_rate, 1)}</td><td class="r">${fmt.r(x.expectancy_r, 3)}</td><td class="r">${fmt.num(x.profit_factor, 2)}</td><td class="r">${fmt.r(x.total_r, 1)}</td><td class="r down">${fmt.num(-x.max_drawdown_r, 1)}R</td></tr>` : "";
      const lc = la.lifecycle || {};
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Book</th><th class="r">Signals</th><th class="r">Resolved</th><th class="r">Win</th><th class="r">Breakeven win</th><th class="r">Expectancy</th><th class="r">PF</th><th class="r">Total</th><th class="r">Max DD</th></tr></thead><tbody>${row("Production", o.production)}${row("Strategy bank", o.bank)}${row("All", o.all)}</tbody></table></div>
        <div class="grid g-12 mt"><div class="c-6"><span class="kicker">Setup lifecycle funnel (${fmt.int(lc.setups)} setups)</span>${hbars(Object.entries(lc.ever_reached || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: esc(k), value: v, meta: fmt.ratio(v / (lc.setups || 1), 1) })), { fmtV: v => fmt.int(v) })}</div>
        <div class="c-6"><span class="kicker">Top close reasons</span>${hbars(Object.entries(lc.top_close_reasons || {}).slice(0, 8).map(([k, v]) => ({ label: `<span title="${esc(k)}">${esc(k.replace(/_/g, " ").toLowerCase())}</span>`, value: -v })), { fmtV: v => fmt.int(-v) })}</div></div>`
        + sourceNote(esc(la.label || "") + ` · window ${fmt.date(la.window?.first)} → ${fmt.date(la.window?.last)} · confirm rate ${fmt.ratio(lc.confirm_rate, 2)}`);
    }, "Signal audit") });
  }
  build(); audit();
  return { keys: ["signals", "quality"], update(k) { if (k === "signals") build(); else audit(); }, destroy: () => destroy() };
}
