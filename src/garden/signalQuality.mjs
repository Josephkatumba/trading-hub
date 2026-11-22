// Signal Quality dashboard. Pure functions over /api/signal-quality; no DOM access.
// Three sources are kept visibly apart: RECORDED live signals (hypothetical R), the HISTORICAL walk-forward
// comparison of the old and quality-gated engines (simulated, out of sample, net of costs), and how live
// bank signals are currently being graded.
import {esc} from "./gardenCards.mjs";

const pct = v => v == null ? "—" : (v * 100).toFixed(1) + "%";
const rr = v => v == null ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(3) + "R";
const num = v => v == null ? "—" : String(v);
const pf = v => v == null ? "—" : Number(v).toFixed(2);

export const POLICY_LABELS = {
  baseline: "Old engine (every signal, own exits)",
  exits_only: "Exits chosen per strategy",
  quality_A: "New engine: A/A+ quality gate",
  quality_B: "Quality gate B and above (own exits)",
  combined_A: "A/A+ gate + exit changes (ablation)",
  combined_B: "B and above + exit changes (ablation)",
  combined_A_nocaps: "A/A+ gate + exits, no regime caps (ablation)",
  entry_confirm: "Confirmation-candle entry (ablation)",
  entry_pullback: "Pullback-limit entry (ablation)",
};

/** Rows of a {key: stats} breakdown, as table HTML. */
export function statsTable(rows, {caption = "", keyLabel = "GROUP", limit = 40} = {}) {
  const entries = Object.entries(rows || {}).slice(0, limit);
  if (!entries.length) return '<p class="gd-na">No data.</p>';
  return '<div class="performance-table-wrap"><table class="performance-table">' + (caption ? '<caption class="gd-bank-caption">' + esc(caption) + '</caption>' : '')
    + '<thead><tr><th>' + esc(keyLabel) + '</th><th>TRADES</th><th>WIN RATE</th><th>EXPECTANCY</th><th>PROFIT FACTOR</th><th>TOTAL</th><th>MAX DD</th></tr></thead><tbody>'
    + entries.map(([key, s]) => '<tr><td>' + esc(key) + (s.sufficient === false ? ' <small class="gd-na">(small sample)</small>' : '') + '</td><td>' + num(s.trades ?? s.resolved)
      + '</td><td>' + pct(s.win_rate) + '</td><td>' + rr(s.expectancy_r) + '</td><td>' + pf(s.profit_factor) + '</td><td>' + rr(s.total_r)
      + '</td><td>' + (s.max_drawdown_r == null ? "—" : Number(s.max_drawdown_r).toFixed(1) + "R") + '</td></tr>').join("")
    + '</tbody></table></div>';
}

/** Old vs new engine on the same out-of-sample signals. */
export function policyTable(scope) {
  const policies = scope?.policies || {};
  const keys = Object.keys(POLICY_LABELS).filter(k => policies[k]);
  if (!keys.length) return '<p class="gd-na">No walk-forward results yet. Run <code>python -m research.quality_research</code>.</p>';
  return '<div class="performance-table-wrap"><table class="performance-table gd-quality-policies"><thead><tr><th>ENGINE</th><th>SELECTED</th><th>TRADES</th><th>WIN RATE</th><th>EXPECTANCY (95% CI)</th><th>PROFIT FACTOR</th><th>MAX DD</th><th>2× COSTS</th></tr></thead><tbody>'
    + keys.map(k => {
      const p = policies[k], s = p.costs_1x || {}, s2 = p.costs_2x || {};
      const ci = s.expectancy_ci95 && s.expectancy_ci95[0] != null ? ' <small>(' + rr(s.expectancy_ci95[0]) + ' to ' + rr(s.expectancy_ci95[1]) + ')</small>' : '';
      return '<tr data-policy="' + esc(k) + '"' + (k === "baseline" || k === "quality_A" ? ' class="gd-quality-key"' : '') + '><td>' + esc(POLICY_LABELS[k]) + '</td><td>' + pct(p.selection_rate)
        + '</td><td>' + num(s.trades) + '</td><td>' + pct(s.win_rate) + '</td><td>' + rr(s.expectancy_r) + ci + '</td><td>' + pf(s.profit_factor)
        + '</td><td>' + (s.max_drawdown_r == null ? "—" : Number(s.max_drawdown_r).toFixed(1) + "R") + '</td><td>' + rr(s2.expectancy_r) + ' · PF ' + pf(s2.profit_factor) + '</td></tr>';
    }).join("") + '</tbody></table></div>';
}

/** Headline tiles: old vs new engine, plus how many signals the gate rejects. */
export function headline(report) {
  const scope = report?.research?.target_instruments || report?.research?.all_instruments;
  const base = scope?.policies?.baseline, next = scope?.policies?.quality_A;
  const audit = report?.live_audit?.overall?.all;
  const tile = (label, value, note) => '<div class="gd-quality-tile"><span>' + esc(label) + '</span><b>' + esc(value) + '</b><small>' + esc(note) + '</small></div>';
  return '<div class="gd-quality-tiles">'
    + (audit ? tile("Live record (all signals)", pct(audit.win_rate) + " · " + rr(audit.expectancy_r), audit.resolved + " resolved · total " + rr(audit.total_r)) : "")
    + (base ? tile("Old engine · out of sample", pct(base.costs_1x.win_rate) + " · " + rr(base.costs_1x.expectancy_r), base.costs_1x.trades + " trades · PF " + pf(base.costs_1x.profit_factor)) : "")
    + (next ? tile("New engine · out of sample", pct(next.costs_1x.win_rate) + " · " + rr(next.costs_1x.expectancy_r), next.costs_1x.trades + " trades · PF " + pf(next.costs_1x.profit_factor)) : "")
    + (next ? tile("Signal rejection rate", pct(1 - next.selection_rate), "share of rule-confirmed signals graded below A") : "")
    + '</div>';
}

export function calibrationTable(cal) {
  const order = ["A+", "A", "B", "C", "REJECTED"];
  const rows = order.filter(g => cal?.[g]).map(g => [g, cal[g]]);
  if (!rows.length) return "";
  return '<div class="performance-table-wrap"><table class="performance-table"><caption class="gd-bank-caption">Out-of-sample result by grade (every signal, no position filter): a useful grade is ordered A+ &gt; A &gt; B &gt; C &gt; REJECTED</caption><thead><tr><th>GRADE</th><th>SIGNALS</th><th>WIN RATE</th><th>EXPECTANCY (95% CI)</th><th>PROFIT FACTOR</th></tr></thead><tbody>'
    + rows.map(([g, s]) => '<tr><td><span class="gd-grade" data-grade="' + esc(g) + '">' + esc(g) + '</span></td><td>' + num(s.trades) + '</td><td>' + pct(s.win_rate) + '</td><td>' + rr(s.expectancy_r)
      + (s.expectancy_ci95 && s.expectancy_ci95[0] != null ? ' <small>(' + rr(s.expectancy_ci95[0]) + ' to ' + rr(s.expectancy_ci95[1]) + ')</small>' : '') + '</td><td>' + pf(s.profit_factor) + '</td></tr>').join("")
    + '</tbody></table></div>';
}

export function strategyStatusTable(status) {
  const rows = Object.entries(status || {});
  if (!rows.length) return "";
  return '<div class="performance-table-wrap"><table class="performance-table"><caption class="gd-bank-caption">Per-strategy verdicts (out of sample, net of costs). Records are never deleted.</caption><thead><tr><th>STRATEGY</th><th>TRADES</th><th>WIN RATE</th><th>AVG WIN</th><th>AVG LOSS</th><th>EXPECTANCY</th><th>PF</th><th>MAX DD</th><th>GATED E</th><th>VERDICT</th></tr></thead><tbody>'
    + rows.map(([k, v]) => {
      const b = v.baseline || {}, q = v.quality_gated || {};
      return '<tr><td>' + esc(k) + '</td><td>' + num(b.trades) + '</td><td>' + pct(b.win_rate) + '</td><td>' + rr(b.avg_win_r) + '</td><td>' + rr(b.avg_loss_r) + '</td><td>' + rr(b.expectancy_r)
        + '</td><td>' + pf(b.profit_factor) + '</td><td>' + (b.max_drawdown_r == null ? "—" : Number(b.max_drawdown_r).toFixed(0) + "R") + '</td><td>' + rr(q.expectancy_r) + ' <small>(' + num(q.trades) + ')</small></td><td><b>'
        + esc(v.verdict) + '</b><br><small>' + esc(v.reason) + '</small></td></tr>';
    }).join("") + '</tbody></table></div>';
}

function compare(breakdown, label) {
  if (!breakdown) return "";
  return '<details class="gd-quality-compare"><summary>' + esc(label) + '</summary><div class="gd-quality-split">'
    + statsTable(breakdown.baseline, {caption: "Old engine", keyLabel: label.toUpperCase()})
    + statsTable(breakdown.quality_A, {caption: "New engine (A/A+)", keyLabel: label.toUpperCase()}) + '</div></details>';
}

/** The whole panel. */
export function qualityPanel(report) {
  if (!report) return '<p class="gd-na">Signal quality report unavailable (engine offline).</p>';
  const research = report.research, audit = report.live_audit, live = report.live_grading || {};
  const b = research?.breakdowns || {};
  const liveGrades = Object.entries(live.by_grade || {});
  const sections = [
    headline(report),
    '<h4>Old engine vs new engine · six target instruments · historical walk-forward (simulated, out of sample)</h4>',
    policyTable(research?.target_instruments),
    '<details><summary>All 16 instruments</summary>' + policyTable(research?.all_instruments) + '</details>',
    research?.random_control?.quality_A ? '<p class="gd-note">Random-selection control: choosing the same number of signals at random gives ' + rr(research.random_control.quality_A.expectancy_r_mean)
      + ' per trade (20 draws, range ' + rr(research.random_control.quality_A.expectancy_r_range?.[0]) + ' to ' + rr(research.random_control.quality_A.expectancy_r_range?.[1]) + ').</p>' : "",
    calibrationTable(research?.grade_calibration?.target_instruments || research?.grade_calibration?.base_exits),
    compare(b.target_symbol, "Instrument"), compare(b.target_strategy, "Strategy"), compare(b.session, "Session"),
    compare(b.regime, "Regime"), compare(b.month, "Month"),
    strategyStatusTable(research?.strategy_status),
    audit ? '<h4>Live record · recorded signals (hypothetical R)</h4>' + statsTable(audit.production?.by_strategy, {caption: "Production strategies", keyLabel: "STRATEGY"})
      + statsTable(audit.target_instruments?.by_symbol, {caption: "Target instruments (production + bank)", keyLabel: "INSTRUMENT"})
      + '<p class="gd-note">Lifecycle: ' + num(audit.lifecycle?.setups) + ' setups detected, ' + pct(audit.lifecycle?.confirm_rate) + ' reached ACTIVE, ' + pct(audit.lifecycle?.expired_share) + ' expired, ' + pct(audit.lifecycle?.invalidated_share) + ' invalidated.</p>' : "",
    '<h4>Live grading · mode <code>' + esc(live.mode || "—") + '</code></h4>'
      + (liveGrades.length ? '<p class="gd-note">' + liveGrades.map(([g, c]) => esc(g) + ': ' + c.signals + ' signals, ' + c.resolved + ' resolved, ' + rr(c.total_r)).join(" · ") + '</p>' : '<p class="gd-na">No graded live signals yet.</p>'),
    '<ul class="gd-lab-rules">' + (report.notes || []).map(n => '<li>' + esc(n) + '</li>').join("") + '</ul>',
  ];
  return sections.join("");
}
