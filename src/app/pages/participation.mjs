// Strategy Participation: which strategies contribute, why the others do not,
// whether any of them is good, where they work, and how independent they are.
// Source: GET /api/intelligence/participation (research.participation). Live
// numbers are recorded signal outcomes (hypothetical); historical numbers are
// simulated with costs. Quantity is shown, never rewarded.
import * as store from "../store.mjs";
import { esc, fmt, tone, icon, badge, tierBadge, guard, empty, seg, sourceNote, hbars, openDrawer, panel, skeleton, stat } from "../ui.mjs";
import { sortRows } from "../model.mjs";

export const subtitle = "Participation, diversification and allocation by evidence";
export const need = ["participation"];

const FLAG = {
  DOMINANT: ["Dominant", "warn", "Takes a disproportionate share of its system's live confirmations."],
  UNDERREPRESENTED: ["Underrepresented", "info", "Confirms far less often than an equal share."],
  INACTIVE: ["Inactive", "muted", "Scanned, but no live confirmation recorded yet."],
  EXCESSIVE_FILTERING: ["Heavy filtering", "warn", "Below 5% of setups confirm and one gate causes most rejections."],
  PROMISING: ["Promising", "good", "Positive evidence after costs (not yet validated)."],
  HIGH_VOLUME_LOW_QUALITY: ["High volume · low quality", "bad", "Top-quartile frequency with a negative historical edge."],
};
const SYSTEMS = [["ALL", "All"], ["LIVE_SCANNER", "Live scanner"], ["STRATEGY_BANK", "Strategy bank"]];
const BASIS = [["live", "Live record"], ["hist", "Historical (simulated)"]];
const CLASS_TEXT = {
  PRODUCTION: "Validated historically and forward, owner-approved.", VALIDATED: "Passes every historical test; forward record pending.",
  EXPERIMENTAL: "Positive after costs but fails a validation test.", RESEARCH: "No credible edge yet, or significantly negative.",
};
const REG_ORDER = ["STRONG_UPTREND", "STRONG_DOWNTREND", "RANGING", "HIGH_VOLATILITY", "LOW_VOLATILITY", "BREAKOUT", "COMPRESSION", "REVERSAL"];
const REG_SHORT = { STRONG_UPTREND: "Uptrend", STRONG_DOWNTREND: "Downtrend", RANGING: "Range", HIGH_VOLATILITY: "High vol", LOW_VOLATILITY: "Low vol", BREAKOUT: "Breakout", COMPRESSION: "Squeeze", REVERSAL: "Reversal" };
const flagBadge = f => FLAG[f] ? badge(FLAG[f][0], FLAG[f][1]) : "";
const pctS = v => Number.isFinite(v) ? (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%" : "—";

export function mount(root) {
  let system = sessionStorage.getItem("td_pt_sys") || "ALL", basis = sessionStorage.getItem("td_pt_basis") || "live", flag = "";
  let sort = "confirmed", dirn = "desc";
  root.innerHTML = `
    <div class="ph"><div><h1>Strategy Participation</h1><p>Which strategy families actually contribute market intelligence, why the others rarely do, and whether any of them has earned it. Live counts come from the production stores; quality comes from the historical evaluation after costs. A strategy is never ranked up for producing more signals.</p></div>
      <div class="ph-a" id="ptGen"></div></div>
    <div id="ptHead"></div>
    <div class="stats s5" id="ptStats"></div>
    <div class="grid g-12 mt">
      <div class="c-6">${panel({ kicker: "Concentration", title: "Share of live confirmations · live scanner", body: `<div id="ptShareLive"></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Concentration", title: "Share of live confirmations · strategy bank (top 12)", body: `<div id="ptShareBank"></div>` })}</div>
      <div class="c-12"><div class="pt-flags" id="ptFlags"></div></div>
      <div class="c-12"><section class="panel flush"><header class="panel-h"><div><span class="kicker">Catalogue</span><h2>Strategy participation and performance</h2></div>
        <div class="panel-a">${seg("ptSys", SYSTEMS, system)}${seg("ptBasis", BASIS, basis)}</div></header><div class="tbl-wrap" id="ptTable"></div><div class="tbl-foot" id="ptFoot"></div></section></div>
      <div class="c-7">${panel({ kicker: "Why strategies stay quiet", title: "Confirmation funnel · live scanner", body: `<div id="ptFunnel"></div>` })}</div>
      <div class="c-5">${panel({ kicker: "Fix candidates, tested", title: "Relaxing the dominant gate · pre-registered test", body: `<div id="ptVariants"></div>` })}</div>
      <div class="c-12">${panel({ kicker: "Market regimes", title: "Expectancy (R) by regime · outlined cells are the regimes a strategy is designed for", body: `<div id="ptRegime"></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Methodology coverage", title: "Strategy families", body: `<div id="ptFam"></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Independence", title: "Diversification", body: `<div id="ptDiv"></div>` })}</div>
      <div class="c-12">${panel({ kicker: "Advisory allocation", title: "Evidence class and attention weight · never changes the engine", body: `<div id="ptAlloc"></div>` })}</div>
    </div>`;
  const $ = id => root.querySelector("#" + id);
  const segBind = (name, set) => root.querySelectorAll(`[data-seg="${name}"] button`).forEach(b => b.onclick = () => { set(b.dataset.v); root.querySelectorAll(`[data-seg="${name}"] button`).forEach(x => x.classList.toggle("on", x === b)); draw(); });
  segBind("ptSys", v => { system = v; sessionStorage.setItem("td_pt_sys", v); });
  segBind("ptBasis", v => { basis = v; sessionStorage.setItem("td_pt_basis", v); });

  const D = () => store.data("participation");
  const rows = () => (D()?.strategies || []);
  const byKey = () => Object.fromEntries(rows().map(r => [r.key, r]));

  function drawHead() {
    const e = store.get("participation"), d = e.data;
    if (!d) { $("ptHead").innerHTML = guard(e, () => "", "Participation report"); $("ptStats").innerHTML = ""; return false; }
    if (!d.available) { $("ptHead").innerHTML = `<div class="banner">${icon("info")}<div><b>No participation report recorded yet.</b> ${esc(d.reason || "")}</div></div>`; $("ptStats").innerHTML = ""; return false; }
    $("ptGen").innerHTML = `<span class="chip" title="${esc((d.notes || []).join(" "))}">${icon("grid")}Report ${esc(String(d.generated_at).slice(0, 16).replace("T", " "))} UTC</span>`;
    const rs = rows(), live = rs.filter(r => r.system === "LIVE_SCANNER");
    const top = [...live].sort((a, b) => (b.live_share || 0) - (a.live_share || 0))[0];
    const cls = c => rs.filter(r => r.allocation?.class === c).length;
    const fams = (d.family_coverage || []).filter(f => f.strategies.length).length;
    const neff = d.diversification?.effective_independent_sources;
    const hhi = live.reduce((s, r) => s + (r.live_share || 0) ** 2, 0);
    $("ptHead").innerHTML = `<div class="banner ${cls("VALIDATED") + cls("PRODUCTION") ? "info" : ""}">${icon("info")}<div><b>${top ? `${esc(top.name)} produces ${pctS(top.live_share)} of the live scanner's confirmations` : "Live scanner"}${top?.historical?.evidence?.tier === "SUSPENDED" ? " while its historical record is significantly negative after costs" : ""}.</b>
      ${cls("VALIDATED") + cls("PRODUCTION") ? `${cls("VALIDATED") + cls("PRODUCTION")} strategies have a validated edge.` : `No strategy has a validated edge after costs, so no strategy earns allocation weight; ${cls("EXPERIMENTAL")} are promising but unproven.`}
      The other families are quiet mainly because their reward/risk gate rejects setups — relaxing it was tested below and did not produce a better edge.</div></div>`;
    $("ptStats").innerHTML = [
      stat({ label: "Strategies evaluated", value: fmt.int(rs.length), sub: `${rs.filter(r => r.scanned).length} scanned · ${rs.filter(r => !r.scanned).length} unsupported`, cls: "hero" }),
      stat({ label: "Families covered", value: `${fams} / ${(d.family_coverage || []).length}`, sub: "methodologies with a strategy" }),
      stat({ label: "Live scanner concentration", value: top ? pctS(top.live_share) : "—", sub: `top strategy · HHI ${hhi.toFixed(2)}` }),
      stat({ label: "Independent sources", value: Number.isFinite(neff) ? neff.toFixed(1) : "—", sub: `effective, of ${d.diversification?.strategies?.length || 0} with history` }),
      stat({ label: "Validated edge", value: fmt.int(cls("VALIDATED") + cls("PRODUCTION")), sub: `${cls("EXPERIMENTAL")} promising · ${rs.filter(r => r.allocation?.suspension_recommended).length} suspension advised` }),
    ].join("");
    return true;
  }

  function drawShares() {
    const rs = rows();
    const bar = list => hbars(list.map(r => ({ label: `${esc(r.name)}`, value: r.live_share || 0, title: `${r.live?.confirmed || 0} confirmations` })), { fmtV: v => pctS(v), max: 1 });
    $("ptShareLive").innerHTML = bar(rs.filter(r => r.system === "LIVE_SCANNER").sort((a, b) => (b.live_share || 0) - (a.live_share || 0)));
    $("ptShareBank").innerHTML = bar(rs.filter(r => r.system === "STRATEGY_BANK" && r.scanned).sort((a, b) => (b.live_share || 0) - (a.live_share || 0)).slice(0, 12));
  }

  function drawFlags() {
    const rs = rows();
    $("ptFlags").innerHTML = Object.entries(FLAG).map(([k, [label, kind, text]]) => {
      const m = rs.filter(r => (r.flags || []).includes(k));
      return `<button class="pt-flag ${kind} ${flag === k ? "on" : ""}" data-f="${k}"><b>${m.length}</b><span>${label}</span><p>${text}</p><em>${m.slice(0, 4).map(r => esc(r.name)).join(" · ")}${m.length > 4 ? ` +${m.length - 4}` : ""}</em></button>`;
    }).join("");
    $("ptFlags").querySelectorAll("[data-f]").forEach(b => b.onclick = () => { flag = flag === b.dataset.f ? "" : b.dataset.f; draw(); });
  }

  function metric(r) {
    const L = r.live || {}, H = r.historical || {}, F = r.funnel || {};
    const hist = basis === "hist";
    return {
      key: r.key, name: r.name, family: r.family, system: r.system, inst: (r.instruments || []).length,
      setups: F.setups, confirmed: L.confirmed ?? 0, active: L.active, tp: L.tp, sl: L.sl, expired: L.expired, invalidated: L.invalidated,
      win: hist ? H.win_rate : L.win_rate, avg: hist ? H.expectancy_r : L.expectancy_r, net: hist ? H.total_r : L.total_r,
      freq: hist ? H.trades_per_month : L.signals_per_week, rate: F.confirmation_rate, pf: hist ? H.profit_factor : L.profit_factor,
      dd: hist ? H.max_drawdown_r : L.max_drawdown_r, n: hist ? H.trades : L.resolved, tier: H.evidence?.tier, flags: r.flags || [],
    };
  }

  function drawTable() {
    if (!D()?.available) { $("ptTable").innerHTML = skeleton(8); return; }
    let list = rows().filter(r => (system === "ALL" || r.system === system) && (!flag || (r.flags || []).includes(flag))).map(metric);
    list = sortRows(list, sort, dirn);
    const hist = basis === "hist";
    const cols = [["name", "Strategy"], ["family", "Family"], ["inst", "Inst.", "r"], ["setups", "Setups", "r"], ["confirmed", "Confirmed", "r"], ["active", "Active", "r"],
      ["tp", "TP", "r"], ["sl", "SL", "r"], ["expired", "Expired", "r"], ["invalidated", "Invalid.", "r"], ["n", hist ? "Trades" : "Resolved", "r"],
      ["win", "Win %", "r"], ["avg", "Avg R", "r"], ["net", "Net R", "r"], ["freq", hist ? "Trades/mo" : "Signals/wk", "r"], ["rate", "Conf. rate", "r"],
      ["pf", "PF", "r"], ["dd", "Max DD", "r"], ["tier", "Evidence"], ["flags", "Flags"]];
    const th = cols.map(([k, l, c]) => `<th class="sort ${c || ""} ${sort === k ? "sorted" : ""}" data-k="${k}">${l}${sort === k ? (dirn === "desc" ? " ↓" : " ↑") : ""}</th>`).join("");
    const n = v => fmt.int(v), r2 = v => `<span class="${tone(v)}">${fmt.r(v)}</span>`;
    $("ptTable").innerHTML = list.length ? `<table class="tbl"><thead><tr>${th}</tr></thead><tbody>${list.map(m => `<tr class="click" data-k="${esc(m.key)}">
      <td><span class="sym" style="font-family:var(--sans);font-size:12.5px">${esc(m.name)}<small>${m.system === "LIVE_SCANNER" ? "Live scanner" : "Strategy bank"} · ${esc(m.key)}</small></span></td>
      <td><span class="fam-chip">${esc(m.family)}</span></td><td class="r">${n(m.inst)}</td><td class="r">${n(m.setups)}</td><td class="r"><b>${n(m.confirmed)}</b></td><td class="r">${n(m.active)}</td>
      <td class="r up">${n(m.tp)}</td><td class="r down">${n(m.sl)}</td><td class="r">${n(m.expired)}</td><td class="r">${n(m.invalidated)}</td><td class="r">${n(m.n)}</td>
      <td class="r">${fmt.ratio(m.win, 0)}</td><td class="r">${r2(m.avg)}</td><td class="r">${r2(m.net)}</td><td class="r">${fmt.num(m.freq, 1)}</td><td class="r">${pctS(m.rate)}</td>
      <td class="r">${fmt.num(m.pf, 2)}</td><td class="r">${fmt.num(m.dd, 1)}</td><td>${m.tier ? tierBadge(m.tier) : badge("NO HISTORY", "muted")}</td><td><span class="pt-fl">${m.flags.map(flagBadge).join("")}</span></td></tr>`).join("")}</tbody></table>`
      : empty("No strategy matches this view");
    $("ptTable").querySelectorAll("th[data-k]").forEach(h => h.onclick = () => { const k = h.dataset.k; dirn = sort === k && dirn === "desc" ? "asc" : "desc"; sort = k; drawTable(); });
    $("ptTable").querySelectorAll("tr[data-k]").forEach(tr => tr.onclick = () => detail(byKey()[tr.dataset.k]));
    $("ptFoot").innerHTML = `<span>${hist ? "Historical: simulated on MT5 history with spread, commission, slippage and financing (not live results)." : "Live: recorded signal outcomes in R (hypothetical, not executed trades). Setups = episodes that reached DEVELOPING (scanner) or rule decisions (bank)."}</span><span>${list.length} strategies</span>`;
  }

  function drawFunnel() {
    const live = rows().filter(r => r.system === "LIVE_SCANNER");
    if (!live.length) { $("ptFunnel").innerHTML = empty("No live scanner strategies in the report"); return; }
    $("ptFunnel").innerHTML = `<div class="pt-funnel">${live.map(r => {
      const f = r.funnel || {}, rp = f.replay || {}, ep = f.episodes || 0;
      const steps = [["Episodes", ep], ["Setups", f.setups], ["Confirming", f.reached_confirming], ["Confirmed", f.confirmed]];
      const maxv = Math.max(1, ...steps.map(s => s[1] || 0));
      const rej = [...(rp.confirming_rejections || []), ...(rp.qualification_rejections || []).map(([k, v]) => ["executable " + k, v])].sort((a, b) => b[1] - a[1]).slice(0, 3);
      return `<div class="pt-fn"><header><b>${esc(r.name)}</b>${(r.flags || []).map(flagBadge).join("")}<span class="muted mono">${pctS(f.confirmation_rate)} of setups confirm</span></header>
        <div class="pt-steps">${steps.map(([l, v]) => `<div><i style="width:${Math.max(2, (v || 0) / maxv * 100)}%"></i><span>${l}</span><b class="mono">${fmt.int(v)}</b></div>`).join("")}</div>
        <p>${rej.length ? "Top rejections at CONFIRMING (replay " + esc((rp.window || []).join(" → ")) + "): " + rej.map(([k, v]) => `<code>${esc(k)}</code> ${fmt.int(v)}`).join(" · ") : "No replay funnel recorded."}
        ${rp.top_no_setup_reasons?.length ? `<br>Most frequent reason for no setup: <code>${esc(rp.top_no_setup_reasons[0][0])}</code>` : ""}</p></div>`;
    }).join("")}</div>${sourceNote("Live episodes from the production observation store; rejection reasons from a no-look-ahead replay sample of the same production code. A setup that fails a gate is not a bug: each gate was checked before any threshold was questioned.")}`;
  }

  function drawVariants() {
    const v = D()?.variant_tests;
    if (!v) { $("ptVariants").innerHTML = empty("No variant test recorded", "Run python -m research.v7_variants"); return; }
    const names = { tm_A_capped: "Production (target capped at prior high)", tm_B_measured: "Measured-move target", smc_A_v1: "Production v1 (any H1 swing)", smc_B_v2: "v2 (untaken liquidity only)" };
    $("ptVariants").innerHTML = Object.entries(v).map(([s, d]) => `<div class="check ${d.adopt ? "pass" : "fail"}" style="margin-bottom:8px"><b>${esc(s === "smc" ? "SMC" : "Trend / Momentum")} · ${d.adopt ? "adopted" : "not adopted"}</b>
      <small>${Object.entries(d.development_expectancy).map(([k, e]) => `${esc(names[k] || k)}: <span class="${tone(e)}">${fmt.r(e, 3)}</span>`).join("<br>")}<br>${esc(d.reason)} (development period only; the test period is never used to choose).</small></div>`).join("")
      + sourceNote("Candidates raised participation 5–25× but did not raise expectancy above zero, so production rules are unchanged.");
  }

  function drawRegime() {
    const rs = rows().filter(r => r.regimes && (r.historical?.trades || 0) >= 100);
    if (!rs.length) { $("ptRegime").innerHTML = empty("No regime breakdown recorded"); return; }
    const cell = (r, g) => {
      const v = r.regimes.by_regime?.[g], design = (r.regimes.designed_for || []).includes(g);
      if (!v || v.trades < 20) return `<td class="r ${design ? "pt-design" : ""}"><span class="na">${v ? "n<20" : "—"}</span></td>`;
      const e = v.expectancy_r, a = Math.min(1, Math.abs(e) / 0.4);
      return `<td class="r ${design ? "pt-design" : ""}" style="background:color-mix(in srgb, var(${e >= 0 ? "--up" : "--down"}) ${Math.round((0.06 + a * 0.36) * 100)}%, transparent)" title="${esc(r.name)} · ${esc(g)} · n=${v.trades} · win ${fmt.ratio(v.win_rate, 0)} · PF ${fmt.num(v.profit_factor, 2)}">${fmt.r(e)}</td>`;
    };
    $("ptRegime").innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Strategy</th>${REG_ORDER.map(g => `<th class="r">${REG_SHORT[g]}</th>`).join("")}<th class="r">In design</th><th class="r">Outside</th><th>Fit</th></tr></thead><tbody>
      ${rs.sort((a, b) => a.family.localeCompare(b.family)).map(r => `<tr class="click" data-k="${esc(r.key)}"><td><span class="sym" style="font-family:var(--sans);font-size:12px">${esc(r.name)}<small>${esc(r.family)}</small></span></td>${REG_ORDER.map(g => cell(r, g)).join("")}
        <td class="r ${tone(r.regimes.inside_design?.expectancy_r)}">${fmt.r(r.regimes.inside_design?.expectancy_r)}</td><td class="r ${tone(r.regimes.outside_design?.expectancy_r)}">${fmt.r(r.regimes.outside_design?.expectancy_r)}</td>
        <td>${r.regimes.regime_fit === "BETTER_IN_DESIGN" ? badge("Better in design", "good") : r.regimes.regime_fit ? badge("Not better", "muted") : ""}</td></tr>`).join("")}</tbody></table></div>
      ${sourceNote("Regime at entry from closed H1 bars only (market_regime.py: ADX, EMA50 slope, ATR vs its 200-bar median, Bollinger-width squeeze, H1-vs-H4 trend flip). Designed regimes come from each methodology's definition, not from these results.")}`;
    $("ptRegime").querySelectorAll("tr[data-k]").forEach(tr => tr.onclick = () => detail(byKey()[tr.dataset.k]));
  }

  function drawFamilies() {
    const fams = D()?.family_coverage || [];
    $("ptFam").innerHTML = `<div class="fam-grid">${fams.map(f => `<div class="fam"><header><span>${esc(f.family)}</span>${f.best_tier ? tierBadge(f.best_tier) : ""}</header>
      <p>${f.primary.length ? `${f.primary.length} primary · ${f.strategies.length} using it` : f.strategies.length ? `Concept only (${f.strategies.length})` : "No strategy"} · <b class="mono">${fmt.int(f.live_confirmations)}</b> live confirmations</p>
      <p class="mono" style="font-size:10.5px">Designed for: ${f.designed_regimes.map(g => REG_SHORT[g] || g).join(", ")}</p></div>`).join("")}</div>`;
  }

  function drawDiv() {
    const d = D()?.diversification;
    if (!d) { $("ptDiv").innerHTML = empty("No diversification analysis recorded"); return; }
    const names = byKey(), nm = k => esc(names[k]?.name || k.replace(/_/g, " "));
    const groups = (d.clusters || []).filter(c => c.length > 1);
    const pairs = [...(d.pairs || [])].sort((a, b) => Math.max(b.outcome_corr || 0, b.overlap_jaccard) - Math.max(a.outcome_corr || 0, a.overlap_jaccard)).slice(0, 8);
    $("ptDiv").innerHTML = `<div class="kv" style="margin-bottom:12px"><div><span>Strategies with history</span><b>${fmt.int(d.strategies.length)}</b></div><div><span>Effective independent</span><b>${fmt.num(d.effective_independent_sources, 1)}</b></div><div><span>Near-duplicate groups</span><b>${groups.length}</b></div></div>
      ${groups.length ? `<div class="setups">${groups.map(g => `<div class="setup" data-s="CONFIRMING"><header><b>${g.length} strategies trade the same opportunities</b></header><ul>${g.map(k => `<li>${nm(k)}</li>`).join("")}</ul></div>`).join("")}</div>` : ""}
      <div class="tbl-wrap mt"><table class="tbl"><thead><tr><th>Pair</th><th class="r">Same trade</th><th class="r">Outcome ρ</th><th class="r">Same dir.</th><th class="r">Shared exp.</th></tr></thead><tbody>
      ${pairs.map(p => `<tr><td style="white-space:normal;font-size:11.5px;min-width:180px">${nm(p.a)}<br><span class="muted">${nm(p.b)}</span></td><td class="r">${pctS(Math.max(p.overlap_a, p.overlap_b))}</td><td class="r">${fmt.num(p.outcome_corr, 2)}</td><td class="r">${pctS(p.directional_agreement)}</td><td class="r">${pctS(p.shared_exposure)}</td></tr>`).join("")}</tbody></table></div>
      ${sourceNote(esc(d.method || ""))}`;
  }

  function drawAlloc() {
    const rs = rows(), pol = D()?.allocation_policy || {};
    const by = c => rs.filter(r => r.allocation?.class === c);
    const weighted = rs.filter(r => (r.allocation?.weight || 0) > 0);
    $("ptAlloc").innerHTML = `<div class="tiers" style="grid-template-columns:repeat(4,minmax(0,1fr))">${["PRODUCTION", "VALIDATED", "EXPERIMENTAL", "RESEARCH"].map(c => `<div class="tcard" data-t="${c === "EXPERIMENTAL" ? "EXPERIMENTAL" : c === "RESEARCH" ? "RESEARCH" : c}"><b>${by(c).length}</b><span>${c}</span><p>${CLASS_TEXT[c]}</p></div>`).join("")}</div>
      <div class="banner ${weighted.length ? "info" : ""} mt">${icon("shield")}<div><b>${weighted.length ? `${weighted.length} strategies receive attention weight.` : "No strategy receives allocation weight."}</b> Weight goes only to VALIDATED or PRODUCTION strategies, in proportion to the lower bound of their 95% expectancy interval, shared within near-duplicate groups, capped at ${pctS(pol.max_weight_per_strategy)}. Signal volume plays no part. ${rs.filter(r => r.allocation?.suspension_recommended && r.deployment === "LIVE").length ? `Suspension is advised for ${rs.filter(r => r.allocation?.suspension_recommended && r.deployment === "LIVE").map(r => esc(r.name)).join(", ")} (live): an owner decision — nothing is switched off automatically.` : ""}</div></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Strategy</th><th>Deployment now</th><th>Evidence tier</th><th>Allocation class</th><th class="r">Weight</th><th>Blocking promotion</th></tr></thead><tbody>
      ${[...rs].sort((a, b) => ["PRODUCTION", "VALIDATED", "EXPERIMENTAL", "RESEARCH"].indexOf(a.allocation?.class) - ["PRODUCTION", "VALIDATED", "EXPERIMENTAL", "RESEARCH"].indexOf(b.allocation?.class) || a.name.localeCompare(b.name)).map(r => `<tr class="click" data-k="${esc(r.key)}"><td>${esc(r.name)}</td><td>${badge(r.deployment, r.deployment === "LIVE" ? "live" : r.deployment === "EXPERIMENTAL" ? "warn" : "muted")}</td>
        <td>${r.allocation?.evidence_tier ? tierBadge(r.allocation.evidence_tier) : "—"}</td><td>${badge(r.allocation?.class || "—", r.allocation?.class === "EXPERIMENTAL" ? "warn" : r.allocation?.class === "VALIDATED" || r.allocation?.class === "PRODUCTION" ? "good" : "muted")}${r.allocation?.suspension_recommended ? " " + badge("Suspension advised", "bad") : ""}</td>
        <td class="r">${pctS(r.allocation?.weight || 0)}</td><td style="white-space:normal;color:var(--t3);font-size:11.5px">${esc((r.allocation?.blockers || []).slice(0, 3).join("; ") || "—")}</td></tr>`).join("")}</tbody></table></div>`;
    $("ptAlloc").querySelectorAll("tr[data-k]").forEach(tr => tr.onclick = () => detail(byKey()[tr.dataset.k]));
  }

  function draw() {
    if (!drawHead()) { ["ptShareLive", "ptShareBank", "ptTable", "ptFunnel", "ptRegime", "ptFam", "ptDiv", "ptAlloc", "ptVariants"].forEach(id => { $(id).innerHTML = D() ? "" : skeleton(4); }); $("ptFlags").innerHTML = ""; return; }
    drawShares(); drawFlags(); drawTable(); drawFunnel(); drawVariants(); drawRegime(); drawFamilies(); drawDiv(); drawAlloc();
  }
  draw();
  return { keys: ["participation"], update: draw };
}

function detail(r) {
  if (!r) return;
  const L = r.live || {}, H = r.historical || {}, F = r.funnel || {}, G = r.regimes || {}, A = r.allocation || {};
  const kv = pairs => `<div class="kv">${pairs.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("")}</div>`;
  const rej = F.replay ? [...(F.replay.confirming_rejections || []), ...(F.replay.qualification_rejections || []).map(([k, v]) => ["executable " + k, v])] : (F.rejections || []);
  openDrawer(`<div class="dh"><h2 style="font-family:var(--sans)">${esc(r.name)}</h2>${(r.flags || []).map(flagBadge).join("")}</div>
    <p class="dsub">${esc(r.family)}${r.concepts?.length ? " · " + r.concepts.map(esc).join(", ") : ""} · ${r.system === "LIVE_SCANNER" ? "Live scanner" : "Strategy bank"} · ${esc(r.deployment)} · ${esc(r.timeframe || "")} · ${fmt.int((r.instruments || []).length)} instruments</p>
    ${r.unsupported_reason ? `<div class="banner">${icon("info")}<div>${esc(r.unsupported_reason)}</div></div>` : ""}
    ${(r.flag_notes || []).length ? `<ul class="evid warn">${r.flag_notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <div class="dsec"><h3>Live record (hypothetical signal outcomes)</h3>${kv([["Confirmed", fmt.int(L.confirmed)], ["Active", fmt.int(L.active)], ["TP / SL", `${fmt.int(L.tp)} / ${fmt.int(L.sl)}`], ["Expired · invalid.", `${fmt.int(L.expired)} · ${fmt.int(L.invalidated)}`],
      ["Win rate", fmt.ratio(L.win_rate, 0)], ["Avg R", fmt.r(L.expectancy_r)], ["Net R", fmt.r(L.total_r)], ["Profit factor", fmt.num(L.profit_factor, 2)], ["Max DD", fmt.num(L.max_drawdown_r, 1) + "R"], ["Signals / week", fmt.num(L.signals_per_week, 1)]])}
      ${(L.resolved || 0) < 100 ? sourceNote(`${fmt.int(L.resolved || 0)} resolved outcomes: too few to judge expectancy (100+ needed).`) : ""}</div>
    <div class="dsec"><h3>Confirmation funnel</h3>${kv([["Setups", fmt.int(F.setups)], ["Confirmed", fmt.int(F.confirmed)], ["Confirmation rate", pctS(F.confirmation_rate)], ["Top gate", esc(F.top_rejection || "—")]])}
      ${rej.length ? `<ul class="evid neg mt">${rej.slice(0, 6).map(([k, v]) => `<li>${esc(k)} <code>${fmt.int(v)}</code></li>`).join("")}</ul>` : ""}<p class="dsub mt">${esc(F.source || "")}</p></div>
    <div class="dsec"><h3>Historical evaluation (simulated, after costs)</h3>${H.trades ? kv([["Trades", fmt.int(H.trades)], ["Win rate", fmt.ratio(H.win_rate, 0)], ["Expectancy", fmt.r(H.expectancy_r, 3)], ["95% CI", (H.expectancy_ci95 || []).map(v => fmt.r(v, 2)).join(" … ")],
      ["Profit factor", fmt.num(H.profit_factor, 2)], ["Max DD", fmt.num(H.max_drawdown_r, 1) + "R"], ["Development", fmt.r(H.development_expectancy, 3)], ["Untouched test", fmt.r(H.test_expectancy, 3)],
      ["Doubled costs", fmt.r(H.x2_cost_expectancy, 3)], ["Walk-forward", `${H.walk_forward_positive ?? "—"} / ${H.walk_forward_folds ?? "—"} folds positive`], ["Instruments positive", `${H.instruments_positive ?? "—"} / ${H.instruments_evaluated ?? "—"}`], ["Evidence tier", H.evidence?.tier || "—"]])
      + (H.evidence?.reasons?.length ? `<p class="dsub mt">${esc(H.evidence.verdict || "")}: ${esc(H.evidence.reasons.join("; "))}</p>` : "") : empty("No historical evaluation recorded")}</div>
    ${G.by_regime ? `<div class="dsec"><h3>By market regime</h3><div class="zones">${REG_ORDER.map(g => { const v = G.by_regime[g]; const d = (G.designed_for || []).includes(g); return `<div class="zrow ${v && v.expectancy_r > 0 ? "bull" : v ? "bear" : ""}"><span class="t">${REG_SHORT[g]}${d ? " · designed" : ""}</span><span>${v ? "n=" + fmt.int(v.trades) : "—"}</span><b class="${tone(v?.expectancy_r)}">${v ? fmt.r(v.expectancy_r) : "—"}</b></div>`; }).join("")}</div>
      <p class="dsub mt">${pctS(G.share_inside_design)} of trades were taken in a designed regime · inside ${fmt.r(G.inside_design?.expectancy_r)} vs outside ${fmt.r(G.outside_design?.expectancy_r)}.</p></div>` : ""}
    <div class="dsec"><h3>Allocation (advisory)</h3>${kv([["Deployment now", esc(r.deployment)], ["Evidence tier", esc(A.evidence_tier || "—")], ["Allocation class", esc(A.class || "—")], ["Weight", pctS(A.weight || 0)]])}
      ${(A.blockers || []).length ? `<ul class="evid warn mt">${A.blockers.map(b => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}</div>`, { wide: true });
}
