import * as store from "../store.mjs";
import { esc, fmt, tone, icon, badge, tierBadge, guard, empty, seg, sourceNote, hbars, openDrawer, panel, skeleton, spark } from "../ui.mjs";
import { rankStrategies, TIER_ORDER, sortRows } from "../model.mjs";

export const subtitle = "Strategy performance intelligence";
export const need = ["strategies", "lab"];

const TIER_TEXT = {
  PRODUCTION: "Validated historically and forward, approved for deployment.",
  VALIDATED: "Passed every historical test; forward record still pending.",
  RESEARCH: "Positive after costs but fails at least one validation test.",
  EXPERIMENTAL: "No credible edge yet: negative-but-inconclusive or too few trades.",
  SUSPENDED: "Significantly negative after costs. Suspension recommended.",
};
const FAMILIES = [["ALL", "All"], ["ICT", "ICT family"], ["UPGRADE", "Upgrades"], ["T-034 BANK", "Bank"], ["PRODUCTION-LINKED", "Production"], ["EXP", "Expansion"]];
const DIMS = [["by_session", "Session"], ["by_trend_regime", "Trend regime"], ["by_volatility_regime", "Volatility"], ["by_instrument", "Instrument"], ["by_direction", "Direction"]];
const famOf = r => ["ICT", "UPGRADE", "T-034 BANK", "PRODUCTION-LINKED"].includes(r.family) ? r.family : "EXP";
const famChip = r => { const f = famOf(r); return `<span class="fam-chip ${f === "ICT" ? "ict" : f === "UPGRADE" ? "upgrade" : f === "PRODUCTION-LINKED" ? "linked" : ""}">${f === "PRODUCTION-LINKED" ? "LINKED" : f === "T-034 BANK" ? "BANK" : f === "EXP" ? "EXPANSION" : f}</span>`; };
const A = r => r.historical?.all_periods || {};

export function mount(root) {
  let tier = "", fam = sessionStorage.getItem("td_lab_fam") || "ALL", sort = "rank", dim = "by_session";
  root.innerHTML = `
    <div class="ph"><div><h1>Strategy Lab</h1><p>Which strategies actually work. Every strategy is replayed through the live confirmation gates with spread, commission, slippage and financing, split into development and an untouched test period, walk-forward folds and a doubled-cost stress test, then ranked by evidence — not by how many signals it produces.</p></div>
      <div class="ph-a" id="labGen"></div></div>
    <div id="labHead"></div>
    <div class="tiers" id="labTiers"></div>
    <div class="grid g-12 mt">
      <div class="c-12">${panel({ kicker: "Evidence ranking", title: "Expectancy per trade with 95% confidence interval (all periods, after costs)", cls: "accent", actions: seg("labFam", FAMILIES, fam), body: `<div id="labCI"></div>` })}</div>
      <div class="c-12"><section class="panel flush"><header class="panel-h"><div><span class="kicker">Catalogue</span><h2>Strategy comparison</h2></div><div class="panel-a"><span class="muted" id="labCount" style="font-size:11.5px"></span></div></header><div class="tbl-wrap" id="labTable"></div></section></div>
      <div class="c-7">${panel({ kicker: "Market conditions", title: "Where strategies work · expectancy (R) by condition", actions: seg("labDim", DIMS, dim), body: `<div id="labHeat"></div>` })}</div>
      <div class="c-5">${panel({ kicker: "Strategy audit", title: "Upgrades vs the strategies they replace", body: `<div id="labUpg"></div>` })}</div>
      <div class="c-12">${panel({ kicker: "Production engines", title: "Live engine outcomes (verified market outcomes)", cls: "flush", body: `<div id="labEngines"></div>` })}</div>
    </div>`;
  const $ = id => root.querySelector("#" + id);
  const segBind = (name, set) => root.querySelectorAll(`[data-seg="${name}"] button`).forEach(b => b.onclick = () => { set(b.dataset.v); root.querySelectorAll(`[data-seg="${name}"] button`).forEach(x => x.classList.toggle("on", x === b)); draw(); });
  segBind("labFam", v => { fam = v; sessionStorage.setItem("td_lab_fam", v); });
  segBind("labDim", v => { dim = v; });

  const all = () => store.data("strategies")?.strategies || [];
  const visible = () => rankStrategies(all()).filter(r => (fam === "ALL" || famOf(r) === fam) && (!tier || r.evidence?.tier === tier));

  function drawHead() {
    const e = store.get("strategies"), d = e.data;
    if (!d) { $("labHead").innerHTML = guard(e, () => "", "Strategy intelligence"); $("labTiers").innerHTML = ""; return; }
    $("labGen").innerHTML = d.generated_at ? `<span class="chip" title="${esc(d.costs || "")}">${icon("lab")}Evaluated ${esc(String(d.generated_at).slice(0, 16).replace("T", " "))} UTC</span>` : "";
    if (!d.available) { $("labHead").innerHTML = `<div class="banner">${icon("info")}<div><b>No historical evaluation recorded yet.</b> Run <code>python -m research.strategy_intel</code> in the backend to evaluate every strategy. Forward records are shown below.</div></div>`; }
    const rows = all(), n = k => rows.filter(r => r.evidence?.tier === k).length;
    const suspend = rows.filter(r => r.suspension_recommended);
    const valid = n("VALIDATED") + n("PRODUCTION");
    if (d.available) $("labHead").innerHTML = `<div class="banner ${valid ? "info" : ""}">${icon(valid ? "shield" : "info")}<div><b>${valid ? `${valid} of ${rows.length} strategies pass every historical validation test.` : `None of the ${rows.length} strategies demonstrates a validated edge after costs.`}</b> ${n("RESEARCH")} are promising but unproven, ${n("SUSPENDED")} are significantly negative${suspend.length ? ` — ${suspend.length} of those still alert on Telegram (suspension is recommended; it is your decision and nothing is switched off automatically)` : ""}. Development ${esc((d.development || []).join(" → "))}, untouched test ${esc((d.periods?.test || []).join(" → "))}. ${esc(d.protocol?.multiple_testing || "")}.</div></div>`;
    $("labTiers").innerHTML = TIER_ORDER.map(t => `<button class="tcard ${tier === t ? "on" : ""}" data-t="${t}"><b>${n(t)}</b><span>${t}</span><p>${TIER_TEXT[t]}</p></button>`).join("");
    $("labTiers").querySelectorAll("[data-t]").forEach(b => b.onclick = () => { tier = tier === b.dataset.t ? "" : b.dataset.t; draw(); });
  }

  function drawCI() {
    if (!store.data("strategies")) { $("labCI").innerHTML = skeleton(8); return; }
    const rows = visible().filter(r => (A(r).trades || 0) >= 30 && A(r).expectancy_ci95?.[0] != null);
    if (!rows.length) { $("labCI").innerHTML = empty("No strategy in this view has 30+ historical trades"); return; }
    const lo = Math.min(-0.5, ...rows.map(r => A(r).expectancy_ci95[0])), hi = Math.max(0.5, ...rows.map(r => A(r).expectancy_ci95[1]));
    const x = v => ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100;
    $("labCI").innerHTML = `<div class="ci-chart">${rows.map(r => { const a = A(r), [l, h] = a.expectancy_ci95; return `<div class="ci-row" data-k="${esc(r.key)}" data-t="${esc(r.evidence.tier)}" title="${esc(r.name)} · n=${a.trades} · CI [${fmt.num(l, 3)}, ${fmt.num(h, 3)}]"><span class="nm">${famChip(r)}<span>${esc(r.name)}</span></span><span class="ci-track"><span class="zero" style="left:${x(0)}%"></span><span class="whisk" style="left:${x(l)}%;width:${Math.max(0.5, x(h) - x(l))}%"></span><span class="pt" style="left:${x(a.expectancy_r)}%"></span></span><span class="v ${tone(a.expectancy_r)}">${fmt.r(a.expectancy_r, 3)}</span></div>`; }).join("")}
      <div class="ci-axis"><span></span><div><span>${fmt.r(lo, 2)}</span><span>0</span><span>${fmt.r(hi, 2)}</span></div><span></span></div></div>
      ${sourceNote("Dot = mean R per trade over all periods after modelled costs; bar = 95% bootstrap confidence interval. A bar crossing zero means the data cannot distinguish the strategy from no edge. Colour = evidence tier.")}`;
    $("labCI").querySelectorAll("[data-k]").forEach(el => el.onclick = () => openStrategy(el.dataset.k));
  }

  function drawTable() {
    if (!store.data("strategies")) { $("labTable").innerHTML = guard(store.get("strategies"), () => "", "Strategy catalogue"); return; }
    const base = visible().map((r, i) => ({ ...r, rank: i + 1, n: A(r).trades ?? null, wr: A(r).win_rate ?? null, exp: A(r).expectancy_r ?? null, pf: A(r).profit_factor ?? null,
      dd: A(r).max_drawdown_r ?? null, test: r.historical?.test?.expectancy_r ?? null, dev: r.historical?.development?.expectancy_r ?? null, x2: r.historical?.all_periods_x2_costs?.expectancy_r ?? null, fwd: r.forward?.resolved ?? null }));
    const rows = sort === "rank" ? base : sortRows(base, sort, sort === "dd" ? "asc" : "desc");
    $("labCount").textContent = `${rows.length} strategies`;
    const th = (k, l, r = true) => `<th class="${r ? "r " : ""}sort ${sort === k ? "sorted" : ""}" data-s="${k}">${l}</th>`;
    const wf = r => { const f = (r.historical?.walk_forward || []).filter(x => x.trades); const p = f.filter(x => x.expectancy_r > 0).length; return f.length ? `<span class="${p / f.length >= 2 / 3 ? "up" : ""}">${p}/${f.length}</span>` : '<span class="na">—</span>'; };
    $("labTable").innerHTML = `<table class="tbl"><thead><tr>${th("rank", "#", false)}<th>Strategy</th><th>Deployment</th><th>Evidence</th>${th("n", "Trades")}<th class="r">W / L</th>${th("wr", "Win")}${th("exp", "Avg R")}${th("pf", "PF")}${th("dd", "Max DD")}<th class="r">Avg R:R</th>${th("dev", "Dev")}${th("test", "Test")}${th("x2", "×2 costs")}<th class="r">WF folds</th>${th("fwd", "Forward")}</tr></thead><tbody>
      ${rows.map(r => `<tr class="click" data-k="${esc(r.key)}"><td class="muted num">${r.rank}</td><td>${famChip(r)} <b style="font-weight:500">${esc(r.name)}</b> <span class="muted mono" style="font-size:10.5px">${esc(r.timeframe)}</span></td>
        <td>${badge(r.deployment, r.deployment === "LINKED" ? "info" : r.deployment === "RESEARCH" ? "ai" : r.deployment === "UNSUPPORTED" ? "muted" : "warn")}${r.alerting ? ' <span class="badge live">ALERTING</span>' : ""}</td>
        <td>${tierBadge(r.evidence.tier)}</td><td class="r">${fmt.int(r.n)}</td><td class="r muted">${A(r).trades ? `${fmt.int(A(r).wins)} / ${fmt.int(A(r).losses)}` : "—"}</td><td class="r">${fmt.ratio(r.wr, 1)}</td>
        <td class="r ${tone(r.exp)}">${fmt.r(r.exp, 3)}</td><td class="r">${fmt.num(r.pf, 2)}</td><td class="r down">${r.dd != null ? fmt.num(-r.dd, 1) + "R" : "—"}</td><td class="r">${fmt.num(r.historical?.avg_planned_rr, 2)}</td>
        <td class="r ${tone(r.dev)}">${fmt.r(r.dev, 2)}</td><td class="r ${tone(r.test)}">${fmt.r(r.test, 2)}</td><td class="r ${tone(r.x2)}">${fmt.r(r.x2, 2)}</td><td class="r">${wf(r)}</td>
        <td class="r">${r.forward?.resolved ? `${fmt.int(r.forward.resolved)} · <span class="${tone(r.forward.expectancy_r)}">${fmt.r(r.forward.expectancy_r, 2)}</span>` : '<span class="na">—</span>'}</td></tr>`).join("")}
    </tbody></table><div class="tbl-foot"><span>Avg R = expectancy per trade after costs. Dev = train + validation; Test = untouched hold-out; WF = quarterly folds with positive expectancy. Forward = recorded live signal outcomes (hypothetical R).</span></div>`;
    $("labTable").querySelectorAll("[data-s]").forEach(h => h.onclick = e => { e.stopPropagation(); sort = h.dataset.s; drawTable(); });
    $("labTable").querySelectorAll("[data-k]").forEach(tr => tr.onclick = () => openStrategy(tr.dataset.k));
  }

  function drawHeat() {
    if (!store.data("strategies")) { $("labHeat").innerHTML = skeleton(6); return; }
    const rows = visible().filter(r => (A(r).trades || 0) >= 60).sort((a, b) => (A(b).trades || 0) - (A(a).trades || 0)).slice(0, 14);
    if (!rows.length) { $("labHeat").innerHTML = empty("No strategy in this view has 60+ trades"); return; }
    const cols = [...new Set(rows.flatMap(r => Object.keys(r.historical?.[dim] || {})))].filter(c => c !== "UNKNOWN").sort();
    const shown = dim === "by_instrument" ? cols.slice(0, 16) : cols;
    const cell = v => {
      if (!v || v.trades < 20) return `<td class="r" style="color:var(--t4)" title="${v ? v.trades + " trades" : "no trades"}">${v ? "n<20" : "·"}</td>`;
      const e = v.expectancy_r, a = Math.min(1, Math.abs(e) / 0.4);
      return `<td class="r" style="background:color-mix(in srgb, var(${e >= 0 ? "--up" : "--down"}) ${Math.round((0.08 + a * 0.38) * 100)}%, transparent);color:var(--t1)" title="n=${v.trades} · win ${fmt.ratio(v.win_rate, 0)} · PF ${fmt.num(v.profit_factor, 2)}">${fmt.num(e, 2)}</td>`;
    };
    $("labHeat").innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Strategy</th>${shown.map(c => `<th class="r">${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${rows.map(r => `<tr class="click" data-k="${esc(r.key)}"><td>${famChip(r)} ${esc(r.name)}</td>${shown.map(c => cell(r.historical?.[dim]?.[c])).join("")}</tr>`).join("")}</tbody></table></div>
      ${sourceNote("Cells: expectancy (R per trade, after costs) of the strategy's historical trades in that condition; cells under 20 trades are not coloured. Sessions by entry hour (UTC); trend regime from H1 ADX(14) (≥25 trending, <20 ranging); volatility regime from the H1 ATR percentile. Conditional splits are descriptive and multiply the number of comparisons: a good cell is a hypothesis, not a filter to deploy.")}`;
    $("labHeat").querySelectorAll("[data-k]").forEach(tr => tr.onclick = () => openStrategy(tr.dataset.k));
  }

  function drawUpgrades() {
    if (!store.data("strategies")) { $("labUpg").innerHTML = skeleton(6); return; }
    const by = Object.fromEntries(all().map(r => [r.key, r]));
    const ups = all().filter(r => r.family === "UPGRADE");
    if (!ups.length) { $("labUpg").innerHTML = empty("No upgraded strategies registered"); return; }
    $("labUpg").innerHTML = ups.map(u => {
      const olds = (u.replaces || []).map(k => by[k]).filter(Boolean);
      const line = (r, strong) => `<div class="hbar" style="grid-template-columns:minmax(120px,1.4fr) 54px 70px 64px"><span class="hbar-l" ${strong ? 'style="color:var(--t1);font-weight:600"' : ""}>${esc(r.name)}</span><span class="hbar-v muted">${fmt.int(A(r).trades)}</span><span class="hbar-v ${tone(A(r).expectancy_r)}">${fmt.r(A(r).expectancy_r, 3)}</span><span>${tierBadge(r.evidence.tier)}</span></div>`;
      return `<div style="padding:8px 0;border-bottom:1px solid var(--line)">${line(u, true)}${olds.map(o => line(o)).join("")}<p class="dsub" style="margin:4px 0 0;font-size:11px">${esc(u.hypothesis || "")}</p></div>`;
    }).join("") + sourceNote("Each upgrade changes the market hypothesis (regime, volatility or liquidity condition), not just a threshold, and runs as a separate shadow strategy; originals keep running unchanged. Columns: trades · avg R · tier.");
  }

  function openStrategy(key) {
    const r = all().find(x => x.key === key); if (!r) return;
    const h = r.historical, ev = r.evidence || {}, d = store.data("strategies") || {};
    const per = [["Train", h?.train, d.periods?.train], ["Validation", h?.validation, d.periods?.validation], ["Development", h?.development, d.development], ["Test (hold-out)", h?.test, d.periods?.test], ["All periods", h?.all_periods], ["All · ×2 costs", h?.all_periods_x2_costs]];
    const folds = (h?.walk_forward || []);
    const maxF = Math.max(0.05, ...folds.map(f => Math.abs(f.expectancy_r || 0)));
    const CHECK = { sample: "Sample size", out_of_sample: "Out-of-sample", significance: "Significance", costs: "Doubled costs", walk_forward: "Walk-forward" };
    const cv = (k, v) => k === "sample" ? `${v.all ?? "—"} trades · ${v.test ?? "—"} in test` : k === "out_of_sample" ? `dev ${fmt.r(v.development, 3)} · test ${fmt.r(v.test, 3)}` : k === "significance" ? `CI [${fmt.num(v.ci95?.[0], 3)}, ${fmt.num(v.ci95?.[1], 3)}] · Holm p ${v.holm_p == null ? "—" : fmt.num(v.holm_p, 3)}` : k === "costs" ? `${fmt.r(v, 3)} per trade` : `${v.positive}/${v.folds} folds positive`;
    const brk = name => { const g = h?.[name] || {}; const rows = Object.entries(g).filter(([, v]) => v.trades >= 10).map(([k, v]) => ({ label: esc(k), value: v.expectancy_r, meta: `n=${v.trades} · ${fmt.ratio(v.win_rate, 0)} · PF ${fmt.num(v.profit_factor, 2)}` })).sort((a, b) => b.value - a.value); return rows.length ? hbars(rows, { fmtV: v => fmt.r(v, 2) }) : empty("Fewer than 10 trades in every group"); };
    const tech = Object.entries(r.technical || {}).sort((a, b) => b[1] - a[1]);
    openDrawer(`<div class="dh"><h2 style="font-family:var(--sans)">${esc(r.name)}</h2>${tierBadge(ev.tier)}${famChip(r)}</div>
      <p class="dsub">${esc(r.key)} · ${esc(r.timeframe)} · deployment ${esc(r.deployment)}${r.alerting ? " (alerting)" : r.deployment === "RESEARCH" ? " (shadow: recorded, never alerted)" : ""} · lifecycle ${esc(r.qualification || "—")}${r.version ? " · " + esc(r.version) : ""}</p>
      <div class="banner ${ev.tier === "SUSPENDED" ? "bad" : ev.tier === "VALIDATED" || ev.tier === "PRODUCTION" ? "info" : ""}">${icon("info")}<div><b>${esc(ev.verdict || "Not evaluated")}.</b> ${esc((ev.reasons || []).join("; "))}${r.suspension_recommended ? " This strategy currently alerts: suspending it is recommended, and it is your decision." : ""}</div></div>
      ${r.hypothesis ? `<div class="dsec"><h3>Market hypothesis</h3><p class="prose">${esc(r.hypothesis)}</p>${r.replaces?.length ? `<p class="dsub" style="margin-top:6px">Upgrade of: ${esc(r.replaces.join(", "))}</p>` : ""}</div>` : ""}
      <div class="dsec"><h3>Validation tests</h3>${ev.checks && Object.keys(ev.checks).length ? `<div class="checks">${Object.entries(ev.checks).map(([k, v]) => `<div class="check ${v.pass ? "pass" : "fail"}"><b>${CHECK[k] || k}</b><small>${cv(k, v.value || {})}</small></div>`).join("")}</div>` : empty("No historical evaluation")}</div>
      <div class="dsec"><h3>Historical record by period (simulated, after costs)</h3>${h ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Period</th><th class="r">Trades</th><th class="r">W / L</th><th class="r">Win</th><th class="r">Avg R</th><th class="r">95% CI</th><th class="r">PF</th><th class="r">Total</th><th class="r">Max DD</th></tr></thead><tbody>${per.map(([p, v, w]) => v && v.trades ? `<tr><td>${p} <span class="muted">${esc((w || []).join(" → "))}</span></td><td class="r">${fmt.int(v.trades)}</td><td class="r muted">${fmt.int(v.wins)} / ${fmt.int(v.losses)}</td><td class="r">${fmt.ratio(v.win_rate, 1)}</td><td class="r ${tone(v.expectancy_r)}">${fmt.r(v.expectancy_r, 3)}</td><td class="r muted">${v.expectancy_ci95?.[0] != null ? `[${fmt.num(v.expectancy_ci95[0], 2)}, ${fmt.num(v.expectancy_ci95[1], 2)}]` : "—"}</td><td class="r">${fmt.num(v.profit_factor, 2)}</td><td class="r ${tone(v.total_r)}">${fmt.r(v.total_r, 1)}</td><td class="r down">${fmt.num(v.max_drawdown_r, 1)}R</td></tr>` : `<tr><td>${p}</td><td colspan="8" class="muted">No trades</td></tr>`).join("")}</tbody></table></div>` : empty(r.unsupported_reason || "Not evaluated")}</div>
      ${h?.equity_r?.length > 2 ? `<div class="dsec"><h3>Cumulative R (all periods, simulated)</h3>${spark(h.equity_r, { w: 860, h: 90 })}</div>` : ""}
      ${folds.length ? `<div class="dsec"><h3>Walk-forward folds · expectancy</h3><div class="folds">${folds.map(f => `<div class="f" title="${esc(f.start)} → ${esc(f.end)} · n=${f.trades} · ${fmt.r(f.expectancy_r, 3)}">${f.trades ? `<i class="${f.expectancy_r >= 0 ? "pos" : "neg"}" style="height:${Math.abs(f.expectancy_r || 0) / maxF * 48 + 2}%;${f.expectancy_r < 0 ? "margin-bottom:-" + (Math.abs(f.expectancy_r) / maxF * 48 + 2) + "%;" : ""}"></i>` : ""}</div>`).join("")}</div><div class="folds-lbl">${folds.map(f => `<span>${esc(f.start.slice(2, 7))}</span>`).join("")}</div></div>` : ""}
      <div class="grid g-12 dsec"><div class="c-6"><h3 class="kicker">By session</h3>${brk("by_session")}</div><div class="c-6"><h3 class="kicker">By trend regime</h3>${brk("by_trend_regime")}</div>
        <div class="c-6"><h3 class="kicker">By volatility regime</h3>${brk("by_volatility_regime")}</div><div class="c-6"><h3 class="kicker">By direction</h3>${brk("by_direction")}</div>
        <div class="c-12"><h3 class="kicker">By instrument</h3>${brk("by_instrument")}</div></div>
      <div class="dsec"><h3>Forward record (live, hypothetical R)</h3><div class="kv"><div><span>Signals</span><b>${fmt.int(r.forward?.signals)}</b></div><div><span>Resolved</span><b>${fmt.int(r.forward?.resolved)}</b></div><div><span>Open</span><b>${fmt.int(r.forward?.open)}</b></div><div><span>Win rate</span><b>${fmt.ratio(r.forward?.win_rate, 1)}</b></div><div><span>Avg R</span><b class="${tone(r.forward?.expectancy_r)}">${fmt.r(r.forward?.expectancy_r, 3)}</b></div><div><span>PF</span><b>${fmt.num(r.forward?.profit_factor, 2)}</b></div><div><span>Max DD</span><b class="down">${fmt.num(r.forward?.max_drawdown_r, 1)}R</b></div></div></div>
      ${tech.length ? `<div class="dsec"><h3>Technical funnel (historical)</h3><div class="kv" style="grid-template-columns:1fr auto">${tech.map(([k, v]) => `<div><b style="font:12px var(--sans);color:var(--t2)">${esc(k)}</b></div><div><b>${fmt.int(v)}</b></div>`).join("")}</div></div>` : ""}
      <div class="dsec"><h3>Rules</h3><div class="kv" style="grid-template-columns:1fr">${["entry", "confirmation", "stop", "take_profit", "invalidation"].filter(k => r.rules?.[k]).map(k => `<div><span>${k.replace("_", " ")}</span><b style="font:12px/1.55 var(--sans);color:var(--t2)">${esc(r.rules[k])}</b></div>`).join("") || "<div><b>No rule description recorded.</b></div>"}</div>
      <p class="source">${icon("info")}<span>Minimum R:R ${esc(r.rules?.min_rr ?? "—")} · instruments: ${esc((r.instruments || []).join(", "))}</span></p></div>`, { wide: true });
  }

  function drawEngines() {
    const e = store.get("lab");
    $("labEngines").innerHTML = guard(e, d => {
      const rows = d.strategies || [];
      if (!rows.length) return empty("No production engines reported");
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Engine</th><th>Mode</th><th>Version</th><th class="r">Setups</th><th class="r">Confirmed</th><th class="r">Verified</th><th class="r">Win rate</th><th class="r">Avg R</th><th class="r">Total R</th><th class="r">PF</th></tr></thead><tbody>
        ${rows.map(s => `<tr><td class="mono">${esc(s.strategy_id)}</td><td>${badge(s.mode, s.mode === "LIVE" ? "good" : "muted")}</td><td class="muted mono">${esc(s.version || "—")}</td><td class="r">${fmt.int(s.setups?.total)}</td><td class="r">${fmt.int(s.confirmations)}</td><td class="r">${fmt.int(s.r?.count)}</td><td class="r">${s.win_rate == null ? '<span class="na" title="Below minimum sample">n&lt;' + d.min_verified_for_rate + "</span>" : fmt.pct(s.win_rate, 1, false)}</td><td class="r ${tone(s.r?.average_r)}">${fmt.r(s.r?.average_r, 3)}</td><td class="r ${tone(s.r?.total_r)}">${fmt.r(s.r?.total_r, 1)}</td><td class="r">${fmt.num(s.r?.profit_factor, 2)}</td></tr>`).join("")}
      </tbody></table></div><div class="tbl-foot"><span>${esc(d.comparison_note || "")}</span></div>`;
    }, "Production engine record");
  }

  function draw() { drawHead(); drawCI(); drawTable(); drawHeat(); drawUpgrades(); }
  draw(); drawEngines();
  return { keys: ["strategies", "lab"], update(k) { if (k === "lab") drawEngines(); else draw(); } };
}
