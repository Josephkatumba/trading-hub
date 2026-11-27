import * as store from "../store.mjs";
import { esc, fmt, tone, icon, dir, outcomeBadge, badge, guard, empty, seg, sourceNote, stat } from "../ui.mjs";
import { signalRows, sortRows, rStats, ago } from "../model.mjs";
import { openSignal } from "./common.mjs";

export const subtitle = "Signal feed, history and analysis";
export const need = ["signals"];

const COLS = [
  ["time", "Confirmed"], ["symbol", "Instrument"], ["direction", "Side"], ["entry", "Entry", "r"], ["stop", "Stop", "r"], ["target", "Target", "r"],
  ["rr", "R:R", "r"], ["strategy", "Strategy"], ["score", "Score", "r"], ["stage", "Lifecycle"], ["outcome", "Outcome"], ["r", "Result", "r"],
];

export function mount(root, { params }) {
  const st = { tab: "live", sort: "time", dir: "desc", q: "", side: "", strategy: "", symbol: params.symbol || "", outcome: "", grade: "" };
  let seen = new Set((store.data("signals")?.signals || []).map(s => s.signal_id)), fresh = new Set();
  root.innerHTML = `
    <div class="ph"><div><h1>Signal Centre</h1><p>Every confirmed strategy-bank signal with its recorded plan, quality grade and tracked outcome. Click a signal for its full analysis and history.</p></div>
      <div class="ph-a">${seg("sgTab", [["live", "Live feed"], ["history", "History"]], st.tab)}</div></div>
    <div id="sgStats"></div>
    <div class="toolbar mt" id="sgTools"></div>
    <section class="panel flush mt"><div class="tbl-wrap" style="max-height:calc(100vh - 330px);min-height:320px" id="sgTable"></div><div class="tbl-foot" id="sgFoot"></div></section>`;
  const $ = id => root.querySelector("#" + id);
  root.querySelectorAll('[data-seg="sgTab"] button').forEach(b => b.onclick = () => { st.tab = b.dataset.v; root.querySelectorAll('[data-seg="sgTab"] button').forEach(x => x.classList.toggle("on", x === b)); draw(); });

  const all = () => signalRows(store.data("signals")?.signals || []);
  function filtered() {
    const now = Date.now();
    return all().filter(r =>
      (st.tab === "history" || r.outcome === "OPEN" || now - r.time < 864e5) &&
      (!st.side || r.direction === st.side) && (!st.strategy || r.strategyKey === st.strategy) && (!st.symbol || r.symbol === st.symbol) &&
      (!st.outcome || r.outcome === st.outcome) && (!st.grade || (r.grade || "UNGRADED") === st.grade) &&
      (!st.q || [r.symbol, r.strategy, r.direction, r.outcome, r.grade].join(" ").toUpperCase().includes(st.q)));
  }

  function tools() {
    const rows = all();
    const opts = (vals, cur, label) => `<option value="">${label}</option>` + [...new Set(vals)].filter(Boolean).sort().map(v => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
    const strategies = [...new Map(rows.map(r => [r.strategyKey, r.strategy]))].sort((a, b) => a[1].localeCompare(b[1]));
    $("sgTools").innerHTML = `<div class="field">${icon("search")}<input data-search id="sgQ" value="${esc(st.q)}" placeholder="Search signals  /" autocomplete="off"></div>
      <select class="sel" data-k="symbol">${opts(rows.map(r => r.symbol), st.symbol, "All instruments")}</select>
      <select class="sel" data-k="side"><option value="">Both sides</option><option value="LONG" ${st.side === "LONG" ? "selected" : ""}>Buy</option><option value="SHORT" ${st.side === "SHORT" ? "selected" : ""}>Sell</option></select>
      <select class="sel" data-k="strategy"><option value="">All strategies</option>${strategies.map(([k, n]) => `<option value="${esc(k)}" ${k === st.strategy ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
      <select class="sel" data-k="outcome">${opts(rows.map(r => r.outcome), st.outcome, "Any outcome")}</select>
      <select class="sel" data-k="grade">${opts(rows.map(r => r.grade || "UNGRADED"), st.grade, "Any grade")}</select>
      <button class="btn ghost sm" id="sgClear">Clear</button>`;
    $("sgQ").oninput = e => { st.q = e.target.value.trim().toUpperCase(); drawTable(); };
    $("sgTools").querySelectorAll("[data-k]").forEach(s => s.onchange = () => { st[s.dataset.k] = s.value; drawTable(); });
    $("sgClear").onclick = () => { Object.assign(st, { q: "", side: "", strategy: "", symbol: "", outcome: "", grade: "" }); tools(); drawTable(); };
  }

  function drawStats() {
    const rows = filtered();
    const res = rows.filter(r => r.r != null && r.outcome !== "OPEN");
    const s = rStats(res.map(r => r.r));
    const open = rows.filter(r => r.outcome === "OPEN").length;
    $("sgStats").innerHTML = `<div class="stats s5">
      ${stat({ label: "Signals in view", value: fmt.int(rows.length), sub: st.tab === "live" ? "Open or last 24h" : "Last 300 recorded", num: rows.length, key: "sgn" })}
      ${stat({ label: "Open", value: `<span class="${open ? "" : "na"}">${open}</span>`, sub: "Awaiting outcome" })}
      ${stat({ label: "Win rate", value: s.winRate == null ? '<span class="na">—</span>' : fmt.ratio(s.winRate, 1), sub: `${s.wins}W · ${s.losses}L of ${s.n} resolved` })}
      ${stat({ label: "Expectancy", value: `<span class="${tone(s.expectancy)}">${fmt.r(s.expectancy, 3)}</span>`, sub: "Per resolved signal" })}
      ${stat({ label: "Net result", value: `<span class="${tone(s.total)}">${fmt.r(s.total, 1)}</span>`, sub: `PF ${fmt.num(s.profitFactor, 2)} · hypothetical` })}
    </div>`;
  }

  function drawTable() {
    drawStats();
    const e = store.get("signals");
    $("sgTable").innerHTML = guard(e, () => {
      const rows = sortRows(filtered(), st.sort, st.dir);
      if (!rows.length) return empty(st.tab === "live" ? "No live signals right now" : "No signals match these filters", st.tab === "live" ? "Nothing is open and nothing confirmed in the last 24 hours. Switch to History for the full record." : "Clear filters to see all recorded signals.");
      return `<table class="tbl"><thead><tr>${COLS.map(([k, l, a]) => `<th class="sort ${a || ""} ${st.sort === k ? "sorted" : ""}" data-sort="${k}" aria-sort="${st.sort === k ? (st.dir === "asc" ? "ascending" : "descending") : "none"}">${l}${st.sort === k ? (st.dir === "asc" ? " ↑" : " ↓") : ""}</th>`).join("")}</tr></thead><tbody>
        ${rows.map(r => `<tr class="click ${fresh.has(r.id) ? "new" : ""}" data-sig="${esc(r.id)}">
          <td class="num muted" title="${fmt.dt(r.time)} UTC">${fmt.dt(r.time).slice(5)}</td><td><span class="sym">${esc(r.symbol)}</span></td><td>${dir(r.direction)}</td>
          <td class="r">${fmt.price(r.entry, r.symbol)}</td><td class="r down">${fmt.price(r.stop, r.symbol)}</td><td class="r up">${fmt.price(r.target, r.symbol)}</td>
          <td class="r">${fmt.num(r.rr, 2)}</td><td style="max-width:190px;overflow:hidden;text-overflow:ellipsis" title="${esc(r.strategy)}">${esc(r.strategy)}</td>
          <td class="r">${r.score == null ? '<span class="na">—</span>' : `<span class="score"><i style="--w:${r.score}%"></i>${r.score}${r.grade ? " " + esc(r.grade) : ""}</span>`}</td>
          <td>${badge(r.stage, r.stage === "CONFIRMED" ? "good" : r.stage === "NO_TRADE" ? "muted" : "info")}</td><td>${outcomeBadge(r.outcome)}</td><td class="r ${tone(r.r)}">${fmt.r(r.r)}</td></tr>`).join("")}
      </tbody></table>`;
    }, "Signal feed");
    const d = store.data("signals");
    $("sgFoot").innerHTML = `<span>${esc(d?.basis || "")}</span><span>${d?.timestamp ? "Updated " + ago(d.timestamp) : ""}</span>`;
    $("sgTable").querySelectorAll("[data-sort]").forEach(th => th.onclick = () => { if (st.sort === th.dataset.sort) st.dir = st.dir === "asc" ? "desc" : "asc"; else { st.sort = th.dataset.sort; st.dir = ["symbol", "strategy", "direction", "stage", "outcome"].includes(st.sort) ? "asc" : "desc"; } drawTable(); });
    $("sgTable").querySelectorAll("[data-sig]").forEach(tr => tr.onclick = () => { const raw = store.data("signals")?.signals || []; openSignal(raw.find(s => s.signal_id === tr.dataset.sig), raw); });
  }
  function draw() { tools(); drawTable(); }
  draw();
  return {
    keys: ["signals"],
    update() {
      const ids = (store.data("signals")?.signals || []).map(s => s.signal_id);
      fresh = new Set(ids.filter(id => !seen.has(id))); seen = new Set(ids);
      draw();
    },
  };
}
