import { getEngineUrl } from "../engine.js";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n = (v, d = 3) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "–" : Number(v).toFixed(d));
const sg = (v, d = 3) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`);
const PROJ = { A: "var(--proj-a)", B: "var(--proj-b)", C: "var(--proj-c)" };
const VERDICT = {
  NO_EDGE: "No edge demonstrated", NOT_RUN: "Not run yet", EDGE_PROMOTED_TO_SHADOW: "Candidate promoted to shadow",
  REJECTED_AT_GATE1: "Rejected (development)", REJECTED_AT_HOLDOUT: "Rejected (holdout)",
  AWAITING_HOLDOUT: "Passed development, awaiting holdout", PROMOTED_TO_SHADOW: "Promoted to shadow",
};
const short = id => id.replace(/^([A-Z]\d)_/, "$1 ").replace(/_/g, " ");

function table(head, rows, numFrom = 1) {
  if (!rows.length) return `<p class="sc-empty">Nothing yet.</p>`;
  return `<div class="sc-tablewrap"><table><thead><tr>${head.map((h, i) => `<th class="${i >= numFrom ? "n" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
  <tbody>${rows.map(r => `<tr>${r.map((c, i) => `<td class="${i >= numFrom ? "n" : ""}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
const mark = ok => (ok ? `<span class="rs-ok" title="pass">✓</span>` : `<span class="rs-no" title="fail">✗</span>`);

function renderHeader(o) {
  const v3 = o.programs.find(p => p.id === "tradeden-v3");
  $("rs-verdict").textContent = o.overall_verdict === "NO_EDGE" ? "Verdict: no edge demonstrated" : "Candidate in shadow";
  $("rs-verdict").className = `sc-pill ${o.overall_verdict === "NO_EDGE" ? "noedge" : "running"}`;
  const locked = o.cbot.found && !o.cbot.execution_unlocked;
  $("rs-lock").textContent = locked ? "cBot execution locked" : "cBot execution UNLOCKED";
  $("rs-lock").className = `sc-pill ${locked ? "locked" : "unlocked"}`;
  $("rs-banner").className = `sc-banner ${o.overall_verdict === "NO_EDGE" ? "serious" : "good"}`;
  const pre = (v3?.hypotheses || []).filter(h => !h.confirmatory);
  const conf = (v3?.hypotheses || []).filter(h => h.confirmatory);
  const g1 = pre.filter(h => h.gate1_pass).length;
  $("rs-banner").textContent = o.overall_verdict === "NO_EDGE"
    ? `No strategy has independently validated positive expectancy. ${o.cumulative_trials_on_gold_or_including_gold.toLocaleString()} trials across ${o.programs.length} programs plus earlier work. V3: ${g1} of ${pre.length} pre-registered hypotheses passed development${conf.length ? `; ${conf.length} confirmatory test on the sealed holdout was rejected` : ""}.`
    : `Promoted to shadow (forward signals only): ${(v3?.promoted || []).join(", ")}. Execution remains locked.`;
  const k = (l, v, s = "") => `<div class="sc-kpi"><span>${esc(l)}</span><strong>${esc(v)}</strong>${s ? `<small>${esc(s)}</small>` : ""}</div>`;
  $("rs-kpis").innerHTML = [
    k("Programs", o.programs.length, "plus ~227 earlier configs"),
    k("Trials logged", o.cumulative_trials_on_gold_or_including_gold.toLocaleString(), "multiple-testing burden"),
    k("V3 hypotheses", pre.length, `${g1} passed gate 1 · ${conf.length} confirmatory`),
    k("Promoted", (v3?.promoted || []).length, "to shadow only"),
  ].join("");
}

function renderPrograms(o) {
  $("rs-programs").innerHTML = table(["Program", "Date", "Scope", "Trials", "Verdict", "Report"],
    o.programs.map(p => [esc(p.id), esc(p.date), esc(p.scope), p.trials ? Number(p.trials).toLocaleString() : "–",
      `<span class="${p.verdict === "NO_EDGE" ? "rs-fail" : "rs-ok"}">${esc(VERDICT[p.verdict] || p.verdict)}</span>`, `<code>${esc(p.report)}</code>`]), 3);
}

function forest(v3) {
  const hs = (v3?.hypotheses || []).filter(h => h.oos && h.oos.trades && !h.confirmatory);
  if (!hs.length) { $("rs-forest").innerHTML = `<p class="sc-empty">V3 development results not available yet.</p>`; return; }
  const W = 760, L = 230, R = 70, row = 26, T = 10, H = T + hs.length * row + 30;
  const vals = hs.flatMap(h => [h.oos.ci95_r?.[0], h.oos.ci95_r?.[1], h.oos.mean_r]).filter(v => Number.isFinite(v));
  const lim = Math.max(0.25, ...vals.map(Math.abs)) * 1.1;
  const x = v => L + ((v + lim) / (2 * lim)) * (W - L - R);
  const ticks = [-lim, -lim / 2, 0, lim / 2, lim].map(v => Math.round(v * 100) / 100);
  const rowsSvg = hs.map((h, k) => {
    const y = T + k * row + row / 2, ci = h.oos.ci95_r || [h.oos.mean_r, h.oos.mean_r], col = PROJ[h.project] || "var(--ink-2)";
    return `<g class="rs-row" data-k="${k}">
      <text x="${L - 10}" y="${y + 4}" text-anchor="end">${esc(short(h.id))}</text>
      <line x1="${x(ci[0])}" x2="${x(ci[1])}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="${x(h.oos.mean_r)}" cy="${y}" r="5" fill="${col}" stroke="var(--surface)" stroke-width="2"/>
      <text x="${W - R + 8}" y="${y + 4}">${h.gate1_pass ? "pass" : "fail"}</text>
      <rect x="0" y="${y - row / 2}" width="${W}" height="${row}" fill="transparent"/></g>`;
  }).join("");
  $("rs-forest").innerHTML = `<div class="rs-legend"><span><i style="background:var(--proj-a)"></i>A macro</span><span><i style="background:var(--proj-b)"></i>B positioning/flow</span><span><i style="background:var(--proj-c)"></i>C regime</span><span>dot = mean R · line = 95% bootstrap CI</span></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Out-of-sample mean R with confidence intervals per hypothesis">
    ${ticks.map(v => `<line class="rs-grid" x1="${x(v)}" x2="${x(v)}" y1="${T}" y2="${H - 24}"/><text x="${x(v)}" y="${H - 8}" text-anchor="middle">${v}</text>`).join("")}
    <line class="rs-zero" x1="${x(0)}" x2="${x(0)}" y1="${T}" y2="${H - 24}"/>${rowsSvg}</svg><div class="sc-tip"></div>`;
  const tip = $("rs-forest").querySelector(".sc-tip"), svg = $("rs-forest").querySelector("svg");
  svg.querySelectorAll(".rs-row").forEach(g => {
    g.addEventListener("pointerenter", () => {
      const h = hs[+g.dataset.k], o = h.oos, box = svg.getBoundingClientRect(), r = g.getBoundingClientRect();
      tip.style.display = "block";
      tip.innerHTML = `<b>${esc(short(h.id))}</b><br>${o.trades} trades · mean ${sg(o.mean_r)} R (${sg(o.mean_net_bp, 1)} bp)<br>CI ${sg(o.ci95_r?.[0])} … ${sg(o.ci95_r?.[1])} · p ${n(o.p_one_sided)}`;
      tip.style.left = `${Math.min(box.width - 230, Math.max(0, r.left - box.left + 240))}px`; tip.style.top = `${r.top - box.top - 4}px`;
    });
    g.addEventListener("pointerleave", () => { tip.style.display = "none"; });
  });
  $("rs-forest-table").innerHTML = table(["Hypothesis", "Trades", "Mean R", "CI low", "CI high", "p"],
    hs.map(h => [esc(short(h.id)), h.oos.trades, sg(h.oos.mean_r), sg(h.oos.ci95_r?.[0]), sg(h.oos.ci95_r?.[1]), n(h.oos.p_one_sided)]));
}

function projectTable(v3, p) {
  const hs = (v3?.hypotheses || []).filter(h => h.project === p);
  const checks = ["min_trades", "mean_positive", "profit_factor", "p_value", "beats_direction_control", "beats_benchmark", "parameter_robustness"];
  return table(["Hypothesis", "Trades", "Mean R", "Net bp", "PF", "p", "Control p90", "Benchmark", "2× costs", "Configs +", "Gate-1 checks", "Verdict"],
    hs.map(h => {
      const o = h.oos || {};
      const label = h.confirmatory ? `<br><small>development row is in-sample (not counted); see holdout</small>` : "";
      return [`<b>${esc(short(h.id))}</b><div class="rs-mech">${esc(h.mechanism)}</div>${label}`, o.trades ?? 0, sg(o.mean_r), sg(o.mean_net_bp, 1), n(o.profit_factor, 2),
        n(o.p_one_sided), sg(h.direction_control?.p90), `${sg(h.benchmark?.mean_r)}<br><small>${esc((h.benchmark?.kind || "").replace(/_/g, " "))}</small>`,
        sg(h.oos_stress_2x?.mean_r), `${Math.round((h.share_configs_positive || 0) * 100)}%`,
        checks.map(c => `<span title="${c}">${mark(h.gate1_checks?.[c])}</span>`).join(""),
        `<span class="${h.verdict === "PROMOTED_TO_SHADOW" ? "rs-ok" : "rs-fail"}">${esc(VERDICT[h.verdict] || h.verdict)}</span>`];
    }), 1);
}

function renderDiagnostics(v3) {
  const d = v3?.diagnostics;
  if (!d) { $("rs-diag").innerHTML = `<p class="sc-empty">Not available yet.</p>`; return; }
  const ev = lay => {
    const t = d[`A_event_study_${lay}`]?.by_kind || {};
    return table([`Release (${lay})`, "Events", "corr(gold, USD) same window", "corr(next gold, USD reaction)", "corr(next gold, data surprise)", "Mean |gold move| bp"],
      Object.entries(t).map(([k, v]) => [k, v.events, sg(v.corr_gold_vs_usd_reaction), sg(v.corr_next_gold_vs_usd_reaction), sg(v.corr_next_gold_vs_data_surprise), n(v.mean_abs_gold_reaction_bp, 1)]));
  };
  const b5 = d.B5_cot_descriptive_vs_predictive || {};
  const c2 = d.C2_regime_persistence || {};
  $("rs-diag").innerHTML = `<p class="sc-sub">Descriptive = moves together at the same time. Predictive = explains what happens next. Only predictive information can be traded.</p>` +
    ev("H1") + ev("D1") +
    table(["COT (weeks: " + (b5.weeks ?? "–") + ")", "Correlation"], [
      ["Managed-money change vs SAME week gold (descriptive)", sg(b5.corr_mm_change_vs_same_week_gold)],
      ["Managed-money change vs NEXT week after release (predictive)", sg(b5.corr_mm_change_vs_next_1w_after_release)],
      ["Managed-money change vs next 4 weeks", sg(b5.corr_mm_change_vs_next_4w_after_release)],
      ["COT index vs next 4 weeks", sg(b5.corr_cot_index_vs_next_4w)]]) +
    table(["Regime persistence", "Trend (ER) t→t+20", "Volatility t→t+20"], Object.entries(c2).map(([tf, v]) => [tf, sg(v["er_t_vs_er_t+20_spearman"]), sg(v["volpct_t_vs_t+20_spearman"])]));
}

function renderHoldout(v3) {
  const hs = (v3?.hypotheses || []).filter(h => h.gate1_pass || h.confirmatory);
  if (!hs.length) { $("rs-holdout").innerHTML = `<p>No hypothesis passed development, so the sealed holdout was ${v3?.holdout_run ? "run with no entrants" : "not opened"}. It stays untouched for future pre-registered work.</p>`; return; }
  $("rs-holdout").innerHTML = `<p class="sc-sub">No V3 pre-registered hypothesis reached the holdout. One post-hoc FOMC rule was given a single confirmatory test.</p>` + table(["Hypothesis", "Trades", "Mean R", "CI", "Halves 21–23 / 24–26", "p", "Verdict"], hs.map(h => {
    const o = h.holdout?.holdout || {};
    const halves = Object.values(h.holdout?.halves || {}).map(x => sg(x.mean_r, 2)).join(" / ");
    return [esc(short(h.id)) + (h.confirmatory ? " <small>(V3.1)</small>" : ""), o.trades ?? "–", sg(o.mean_r), o.ci95_r ? `${sg(o.ci95_r[0])} … ${sg(o.ci95_r[1])}` : "–", halves || "–", n(h.holdout?.holm_p), `<span class="${h.verdict === "PROMOTED_TO_SHADOW" ? "rs-ok" : "rs-fail"}">${esc(VERDICT[h.verdict] || h.verdict)}</span>`];
  }));
}

function renderEarlier(o) {
  const v2 = o.programs.find(p => p.id === "edge-discovery-v2"), s1 = o.programs.find(p => p.id === "scalper-tds-1.0");
  $("rs-earlier").innerHTML = `<h3 class="sc-sub">Edge Discovery V2 (gold, M15)</h3>` + table(["Hypothesis", "Dev OOS trades", "Dev mean R", "Holdout mean R", "Verdict"],
    (v2?.hypotheses || []).map(h => [esc(short(h.id)), h.oos?.trades ?? "–", sg(h.oos?.expectancy_r), sg(h.holdout?.expectancy_r), esc(VERDICT[h.verdict] || h.verdict)])) +
    `<h3 class="sc-sub">Scalper tds-1.0 (M5)</h3>` + table(["Symbol", "OOS trades", "Mean R", "PF", "Verdict"],
    (s1?.symbols || []).map(s => [esc(s.symbol), s.oos?.trades ?? "–", sg(s.oos?.expectancy_r), n(s.oos?.profit_factor, 2), esc(s.verdict)]));
}

async function load() {
  try {
    const r = await fetch(getEngineUrl() + "/api/research/overview", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const o = await r.json();
    const v3 = o.programs.find(p => p.id === "tradeden-v3");
    renderHeader(o); renderPrograms(o); forest(v3);
    ["A", "B", "C"].forEach(p => { $(`rs-${p}`).innerHTML = projectTable(v3, p); });
    renderDiagnostics(v3); renderHoldout(v3); renderEarlier(o);
  } catch (e) {
    $("rs-banner").className = "sc-banner serious";
    $("rs-banner").textContent = `Cannot reach the Trading Hub engine at ${getEngineUrl()} (${e.message}). Restart it so it loads /api/research/overview.`;
    $("rs-verdict").textContent = "Engine unreachable";
  }
}
load();
