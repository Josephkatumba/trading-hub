// Strategy Lab measurement views. Pure functions over /api/market/strategy-lab and
// /api/market/setups/{id}; no DOM access. Strategies are shown side by side and
// never combined. Every explanation is a stored, deterministic strategy field;
// nothing here is generated or inferred.
import {esc} from "./gardenCards.mjs";
import {formatPrice, formatUtc, isValidatedOutcome} from "./gardenModel.mjs";
import {strategyTag} from "../strategyModel.mjs";

const STATE_ROWS = [["DEVELOPING", "Developing"], ["CONFIRMING", "Confirming"], ["CONFIRMED", "Confirmed"], ["ACTIVE", "Active"]];
const OUTCOME_ROWS = [["pending", "Outcome pending"], ["unverified", "Outcome unverified"], ["verified_target", "Verified target hit"],
  ["verified_stop", "Verified stop hit"], ["verified_other", "Verified no hit / ambiguous"]];
const na = '<span class="gd-na">—</span>';

/** Strategies worth showing: registered LIVE/SHADOW ones and any strategy that has records. */
export function labStrategies(report) {
  return (report?.strategies || []).filter(item => item.mode === "LIVE" || item.mode === "SHADOW" || item.setups?.total > 0);
}

/** Metric rows x strategy columns; each cell comes from that strategy's own block. */
export function comparisonRows(report) {
  const strategies = labStrategies(report);
  const row = (label, pick) => ({label, values: strategies.map(pick)});
  return {
    strategies: strategies.map(item => ({...strategyTag(item.strategy_id), mode: item.mode, version: item.version})),
    rows: [
      row("Setups recorded", item => item.setups.total),
      ...STATE_ROWS.map(([state, label]) => row(label + " (open)", item => item.setups.by_state[state] ?? 0)),
      row("Closed", item => item.setups.closed),
      row("Closed · invalidated", item => item.setups.by_state.INVALIDATED ?? 0),
      row("Closed · expired / resolved", item => (item.setups.by_state.EXPIRED ?? 0) + (item.setups.by_state.RESOLVED ?? 0)),
      row("Confirmations", item => item.confirmations),
      ...OUTCOME_ROWS.map(([key, label]) => row(label, item => item.outcomes[key] ?? 0)),
      row("Win rate (verified target vs stop)", item => item.win_rate == null ? null : item.win_rate + "%"),
    ],
    notes: strategies.map(item => ({tag: strategyTag(item.strategy_id).tag, note: item.win_rate_note})),
  };
}

function table(head, rows) {
  return '<div class="performance-table-wrap"><table class="performance-table gd-lab-table"><thead><tr>' + head.map(h => '<th>' + h + '</th>').join("")
    + '</tr></thead><tbody>' + rows.join("") + '</tbody></table></div>';
}

function breakdown(title, groups) {
  const keys = Object.keys(groups || {});
  if (!keys.length) return '';
  return '<h5>' + esc(title) + '</h5>' + table(["", "SETUPS", "CONFIRMED", "PENDING", "UNVERIFIED", "TARGET", "STOP", "OTHER"],
    keys.map(key => {
      const g = groups[key];
      return '<tr><th>' + esc(key) + '</th>' + [g.setups, g.confirmed, g.pending, g.unverified, g.verified_target, g.verified_stop, g.verified_other]
        .map(value => '<td>' + Number(value || 0) + '</td>').join("") + '</tr>';
    }));
}

/** Full Strategy Lab measurement block: comparison, then the selected strategy's detail. */
export function labReportPanel(report, {selected = "support_resistance"} = {}) {
  if (!report) return '<p class="gd-na">Strategy measurements unavailable (engine offline).</p>';
  const comparison = comparisonRows(report);
  if (!comparison.strategies.length) return '<p class="gd-na">No strategies registered.</p>';
  const head = ["METRIC", ...comparison.strategies.map(s => esc(s.tag) + (s.mode === "SHADOW" ? ' <span class="gd-shadow-badge">SHADOW</span>' : ''))];
  const rows = comparison.rows.map(r => '<tr><th>' + esc(r.label) + '</th>' + r.values.map(v => '<td>' + (v == null ? na : esc(v)) + '</td>').join("") + '</tr>');
  const chosen = labStrategies(report).find(item => item.strategy_id === selected) || labStrategies(report)[0];
  const tabs = labStrategies(report).map(item => '<button type="button" data-lab-strategy="' + esc(item.strategy_id) + '" aria-pressed="' + (item === chosen) + '">'
    + esc(strategyTag(item.strategy_id).tag) + '</button>').join("");
  const recent = (chosen.recent || []).map(item => '<tr><th>' + esc(item.symbol) + '</th><td>' + esc(item.direction || "—") + '</td><td>' + esc(item.setup_type || "—")
    + '</td><td>' + esc(item.lifecycle_state) + '</td><td>' + (item.confirmed ? "yes" : "no") + '</td><td>' + esc(item.outcome || (item.confirmed ? "pending" : "—"))
    + '</td><td>' + (formatUtc(item.last_observed_at) ? esc(formatUtc(item.last_observed_at)) : na)
    + '</td><td><button type="button" class="gd-link" data-lab-inspect="' + esc(item.setup_id) + '">Inspect</button></td></tr>');
  return '<section class="gd-lab-report"><h4>Strategies measured separately</h4>'
    + '<p class="gd-note">' + esc(report.comparison_note || "") + '</p>'
    + table(head, rows)
    + comparison.notes.map(n => '<p class="gd-note"><b>' + esc(n.tag) + ':</b> ' + esc(n.note) + '</p>').join("")
    + '<p class="gd-note">' + esc(report.outcome_rules || "") + '</p>'
    + '<div class="gd-lab-tabs" role="group" aria-label="Strategy detail">' + tabs + '</div>'
    + breakdown("By instrument", chosen.by_instrument) + breakdown("By direction", chosen.by_direction)
    + breakdown("By timeframe", chosen.by_timeframe) + breakdown("By setup family", chosen.by_setup_type)
    + '<h5>Recent ' + esc(strategyTag(chosen.strategy_id).tag) + ' setups</h5>'
    + (recent.length ? table(["MARKET", "DIRECTION", "FAMILY", "LIFECYCLE", "CONFIRMED", "OUTCOME", "LAST SEEN", ""], recent)
      : '<p class="gd-na">No setups recorded yet.</p>')
    + '</section>';
}

/** Deterministic evidence of one setup, from its stored snapshots, events and outcomes. */
export function evidenceModel(detail) {
  const snapshots = (detail?.snapshots || []).filter(row => row?.record_type === "setup_snapshot");
  if (!snapshots.length) return null;
  const confirmation = (detail.confirmation_events || [])[0] || null;
  const confirmed = confirmation ? snapshots.find(row => row.observation_id === confirmation.observation_id) : null;
  const basis = confirmed || snapshots[snapshots.length - 1];
  const evidence = basis.strategy_evidence || {};
  const level = evidence.level || null;
  const outcomes = (detail.market_outcomes || []).filter(row => !confirmation || row.observation_id === confirmation.observation_id)
    .map(row => ({horizon: row.horizon, label: row.label || "PENDING", verified: isValidatedOutcome(row)}));
  return {
    setupId: detail.setup_id, symbol: basis.symbol, direction: basis.direction, strategy: strategyTag(basis.strategy_id),
    shadow: basis.shadow === true, version: basis.strategy_version, basis: confirmed ? "confirmation snapshot" : "latest snapshot",
    observedAt: formatUtc(basis.observed_at), family: evidence.family || basis.setup_type || null,
    level: level && {type: level.type, price: formatPrice(level.price), zone: formatPrice(level.zone_low) + " – " + formatPrice(level.zone_high),
      reactions: level.reactions, strength: level.strength, byTimeframe: level.reactions_by_timeframe || {},
      htf: level.higher_timeframe_confluence === true, htfReactions: level.higher_timeframe_reactions, roleReversal: level.role_reversal === true},
    touch: evidence.touch || null, rejection: evidence.rejection || null,
    rules: Object.entries(evidence.confirmation?.rules || {}).map(([name, passed]) => ({name, passed: passed === true})),
    plan: evidence.plan ? {entry: formatPrice(evidence.plan.entry), stop: formatPrice(evidence.plan.stop), target: formatPrice(evidence.plan.target),
      rr: evidence.plan.rr, minRr: evidence.plan.min_rr} : null,
    lifecycle: (detail.lifecycle_events || []).map(event => ({to: event.to_state, reason: event.reason_code, at: formatUtc(event.occurred_at)})),
    confirmedAt: confirmation ? formatUtc(confirmation.confirmed_at) : null,
    outcomes,
    trend: trendModel(evidence),
    hasEvidence: Boolean(level || evidence.confirmation || evidence.trend),
  };
}

/** Trend / Momentum evidence (stored calculations only): trend, impulse, pullback, trigger, score parts. */
function trendModel(evidence) {
  const trend = evidence?.trend;
  if (!trend) return null;
  const round = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? null : Number(value).toFixed(digits);
  return {
    h4: trend.h4 ? {structure: trend.h4.structure, slope: round(trend.h4.ema50_slope_atr), direction: trend.h4.direction} : null,
    d1: trend.d1 ? trend.d1.status : null,
    h1Aligned: trend.h1 ? trend.h1.aligned === true : null,
    impulseAtr: round(evidence.momentum?.impulse_atr), efficiency: round(evidence.momentum?.efficiency),
    retracement: round(evidence.pullback?.retracement, 3), pullbackBars: evidence.pullback?.pullback_bars ?? null,
    controlled: evidence.pullback ? evidence.pullback.controlled === true : null, failed: evidence.pullback?.failed || [],
    trigger: evidence.trigger ? evidence.trigger.resumption === true : null,
    structureInvalidation: evidence.plan?.structure_invalidation == null ? null : formatPrice(evidence.plan.structure_invalidation),
    score: Object.entries(evidence.score_components || {}).map(([name, part]) => ({name, points: part.points, max: part.max})),
  };
}

function trendSection(trend) {
  if (!trend) return '';
  const yes = value => value == null ? na : value ? "yes" : "no";
  const show = value => value == null ? na : esc(value);
  return '<h5>Trend and momentum</h5><dl class="gd-lab-dl">'
    + (trend.h4 ? '<div><dt>H4 trend</dt><dd>' + show(trend.h4.direction || "none") + ' · ' + show(trend.h4.structure) + ' · EMA50 slope ' + show(trend.h4.slope) + ' × ATR</dd></div>' : '')
    + '<div><dt>D1 context</dt><dd>' + show(trend.d1) + '</dd></div>'
    + '<div><dt>H1 aligned</dt><dd>' + yes(trend.h1Aligned) + '</dd></div>'
    + '<div><dt>Impulse</dt><dd>' + show(trend.impulseAtr) + ' × ATR H1 · efficiency ' + show(trend.efficiency) + '</dd></div>'
    + '<div><dt>Pullback</dt><dd>retraced ' + show(trend.retracement) + ' over ' + show(trend.pullbackBars) + ' H1 bars · controlled ' + yes(trend.controlled)
    + (trend.failed.length ? ' (' + trend.failed.map(esc).join("; ") + ')' : '') + '</dd></div>'
    + '<div><dt>M15 continuation</dt><dd>' + yes(trend.trigger) + '</dd></div>'
    + (trend.structureInvalidation ? '<div><dt>Structure invalidation</dt><dd>' + esc(trend.structureInvalidation) + '</dd></div>' : '')
    + '</dl>'
    + (trend.score.length ? '<h5>Score components</h5><ul class="gd-lab-rules">' + trend.score.map(part => '<li>' + esc(part.name) + ' ' + Number(part.points || 0)
      + ' / ' + Number(part.max || 0) + '</li>').join("") + '</ul>' : '');
}

export function evidencePanel(model) {
  if (!model) return '<p class="gd-na">No recorded snapshot for this setup.</p>';
  const yes = value => value ? "yes" : "no";
  const byTf = model.level ? Object.entries(model.level.byTimeframe).map(([tf, n]) => esc(tf) + " " + n).join(" · ") : "";
  return '<section class="gd-lab-evidence"><h4>' + esc(model.symbol) + ' · ' + esc(model.direction || "no direction") + ' · ' + esc(model.strategy.tag)
    + (model.shadow ? ' <span class="gd-shadow-badge">SHADOW</span>' : '') + '</h4>'
    + '<p class="gd-note">Recorded ' + esc(model.basis) + (model.observedAt ? ' at ' + esc(model.observedAt) : '') + ' · ' + esc(model.version || "") + ' · '
    + esc(model.family || "") + '. Stored strategy calculations, not a generated explanation.</p>'
    + (!model.hasEvidence ? '<p class="gd-na">This setup has no structured strategy evidence (recorded before evidence was stored, or its strategy stores none).</p>' : '')
    + trendSection(model.trend)
    + (model.level ? '<h5>Why this level</h5><dl class="gd-lab-dl"><div><dt>Level</dt><dd>' + esc(model.level.type) + ' ' + esc(model.level.price) + ' (zone ' + esc(model.level.zone) + ')</dd></div>'
      + '<div><dt>Reactions</dt><dd>' + model.level.reactions + ' (strength ' + model.level.strength + ') · ' + byTf + '</dd></div>'
      + '<div><dt>Higher timeframe</dt><dd>' + (model.level.htf ? 'yes, ' + model.level.htfReactions + ' H4/D1 reactions' : 'no H4/D1 reaction') + '</dd></div>'
      + '<div><dt>Role reversal</dt><dd>' + yes(model.level.roleReversal) + '</dd></div></dl>' : '')
    + (model.touch || model.rejection ? '<h5>Test and rejection</h5><dl class="gd-lab-dl">'
      + (model.touch ? '<div><dt>Touched</dt><dd>' + yes(model.touch.touched) + (model.touch.bars_ago != null ? ' (' + model.touch.bars_ago + ' bars ago)' : '') + '</dd></div>'
        + '<div><dt>Clean test</dt><dd>' + yes(model.touch.clean_test) + ' (approach ' + esc(model.touch.approach_atr_h1) + ' × ATR H1)</dd></div>' : '')
      + (model.rejection ? '<div><dt>Rejection candle</dt><dd>' + yes(model.rejection.confirmed) + ' (close position ' + esc(model.rejection.close_position) + ')</dd></div>' : '')
      + '</dl>' : '')
    + (model.rules.length ? '<h5>Confirmation rules</h5><ul class="gd-lab-rules">' + model.rules.map(rule => '<li class="' + (rule.passed ? 'is-pass' : 'is-fail') + '">'
      + (rule.passed ? '✓ ' : '✗ ') + esc(rule.name) + '</li>').join("") + '</ul>' : '')
    + (model.plan ? '<h5>Plan</h5><dl class="gd-lab-dl"><div><dt>Entry</dt><dd>' + (model.plan.entry ? esc(model.plan.entry) : na) + '</dd></div><div><dt>Stop</dt><dd>'
      + (model.plan.stop ? esc(model.plan.stop) : na) + '</dd></div><div><dt>Target</dt><dd>' + (model.plan.target ? esc(model.plan.target) : na)
      + '</dd></div><div><dt>R</dt><dd>' + (model.plan.rr == null ? na : esc(model.plan.rr) + ' (min ' + esc(model.plan.minRr) + ')') + '</dd></div></dl>' : '')
    + '<h5>What happened afterwards</h5>'
    + (model.lifecycle.length ? '<ul>' + model.lifecycle.map(e => '<li>' + esc(e.to) + ' · ' + esc(e.reason || "") + (e.at ? ' · ' + esc(e.at) : '') + '</li>').join("") + '</ul>' : '<p class="gd-na">No lifecycle events.</p>')
    + (model.confirmedAt ? '<p>Shadow confirmation recorded ' + esc(model.confirmedAt) + '.</p>' : '<p class="gd-note">Never confirmed.</p>')
    + (model.outcomes.length ? '<ul>' + model.outcomes.map(o => '<li>' + esc(o.horizon) + ': ' + (o.verified ? esc(o.label) + ' (verified)' : 'unverified — not counted') + '</li>').join("") + '</ul>'
      : (model.confirmedAt ? '<p class="gd-note">Outcome pending.</p>' : ''))
    + '</section>';
}
