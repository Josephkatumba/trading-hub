// Strategy Bank views. Pure functions over /api/strategy-bank; no DOM access.
// Live columns show ONLY recorded signals and outcomes ("Pending" until a signal has resolved).
// Historical backtest results are shown separately and labelled as simulated, never as live results.
import {esc} from "./gardenCards.mjs";
import {validationOf} from "../strategyUnified.mjs";
import {formatPrice, formatUtc} from "./gardenModel.mjs";

const pct = value => (value * 100).toFixed(0) + "%";
const r = value => (value > 0 ? "+" : "") + Number(value).toFixed(2) + "R";
const pending = '<span class="gd-na">Pending</span>';

/** Status label: what the strategy is actually doing now. */
export function bankStatus(row, worker) {
  if (row.status === "UNSUPPORTED") return "Unsupported";
  if (row.status === "LINKED") return "Monitoring · live production strategy";
  return worker?.enabled ? (worker.running ? "Monitoring · experimental" : "Experimental · starting") : "Experimental · not running";
}

/** One display row per strategy, from recorded statistics only. */
export function bankRows(report) {
  const worker = report?.worker || {};
  return (report?.strategies || []).map(row => ({
    n: row.n, key: row.key, name: row.name, status: bankStatus(row, worker), kind: row.status, validation: validationOf(row.status),
    signals: row.status === "UNSUPPORTED" ? null : (row.signals ?? 0),
    winRate: row.win_rate == null ? null : pct(row.win_rate),
    expectancy: row.expectancy_r == null ? null : r(row.expectancy_r),
    drawdown: row.max_drawdown_r == null ? null : Number(row.max_drawdown_r).toFixed(1) + "R",
    resolved: row.resolved ?? 0, open: row.open ?? 0, reason: row.unsupported_reason || null,
  }));
}

/** Historical backtest rows (simulated), kept apart from live rows. */
export function historicalRows(report) {
  const results = report?.historical?.results?.strategies || {};
  return Object.entries(results).map(([key, item]) => {
    const all = item?.performance?.all_periods || null;
    return {key, n: item.n, name: item.name, verdict: item.verdict,
      trades: all ? all.trades : null,
      winRate: all && all.win_rate != null ? pct(all.win_rate) : null,
      expectancy: all && all.expectancy_r != null ? r(all.expectancy_r) : null,
      ci: all && all.expectancy_ci95 && all.expectancy_ci95[0] != null ? r(all.expectancy_ci95[0]) + " to " + r(all.expectancy_ci95[1]) : null};
  }).sort((a, b) => a.n - b.n);
}

/**
 * Performance view for one bank strategy (strategy selector): its RECORDED forward results,
 * and, separately and labelled as simulated, its historical backtest. The two are never mixed.
 */
export function bankStrategyPerformance(report, key) {
  if (!report) return '<div class="macro-empty"><b>Strategy bank unavailable</b><span>The engine did not return the bank report.</span></div>';
  const row = bankRows(report).find(item => item.key === key);
  if (!row) return '<div class="macro-empty"><b>Unknown strategy</b></div>';
  const forward = row.resolved
    ? '<b>' + esc(row.winRate ?? "—") + ' win rate · ' + esc(row.expectancy ?? "—") + ' per signal</b><span>' + row.resolved + ' resolved of ' + row.signals + ' recorded signals · max drawdown ' + esc(row.drawdown ?? "—") + '</span>'
    : '<b>Pending</b><span>' + (row.signals ?? 0) + ' recorded signals, none resolved yet.</span>';
  const hist = historicalRows(report).find(item => item.key === key);
  return '<div class="performance-headline gd-bank-forward"><span class="gd-validation" data-validation="' + esc(row.validation.key) + '">' + esc(row.validation.label) + '</span>'
    + '<b class="gd-combined">' + esc(row.name.toUpperCase()) + ' · FORWARD RESULTS (RECORDED)</b>' + forward + '</div>'
    + (hist ? '<p class="gd-note gd-bank-hist"><b>Historical backtest (simulated, not live results):</b> ' + (hist.trades ?? "—") + ' trades · win rate ' + esc(hist.winRate ?? "—")
      + ' · expectancy ' + esc(hist.expectancy ?? "—") + (hist.ci ? ' (95% CI ' + esc(hist.ci) + ')' : '') + ' · ' + esc(hist.verdict || "") + '</p>' : '')
    + '<small>R multiples are hypothetical signal outcomes, not executed trades.</small>';
}

const OUTCOME_LABEL = {TARGET_HIT: "🎯 Take profit reached", STOP_HIT: "🛑 Stop loss reached", TIME_EXIT: "⌛ Time exit",
  AMBIGUOUS: "◐ Ambiguous (both levels in one candle)", NO_HIT: "◌ Neither level reached", UNAVAILABLE: "… Outcome unverifiable", PENDING: "⏳ Open"};

/**
 * Details drawer for one recorded Strategy Bank signal: the responsible strategy and its
 * validation status, the confirmed plan, the recorded rationale and contradicting evidence,
 * every strategy that confirmed the same opportunity, and the recorded outcome (hypothetical R).
 */
export function bankResearchPanel(card, signal) {
  if (!card || !signal) return '<div class="gd-analyst-empty"><b>Nothing selected</b></div>';
  const side = signal.direction === "LONG" ? "BUY" : signal.direction === "SHORT" ? "SELL" : "—";
  const status = String(signal.outcome_status || "PENDING").toUpperCase();
  const rValue = signal.r_multiple == null ? null : Number(signal.r_multiple);
  const cell = (label, value, cls = "") => '<div class="' + cls + '"><dt>' + label + '</dt><dd>' + (value == null ? '—' : esc(value)) + '</dd></div>';
  const notes = Array.isArray(signal.contradictions) ? signal.contradictions : [];
  return '<header class="gd-rs-head" data-dir="' + (signal.direction === "LONG" ? "long" : signal.direction === "SHORT" ? "short" : "none") + '" data-stage="' + esc(card.stage) + '">'
    + '<div class="gd-rs-title"><span class="gd-eyebrow">Strategy bank signal · ' + esc(card.validation?.label || "Experimental") + '</span>'
    + '<h2 id="gardenResearchTitle">' + esc(signal.symbol) + ' <span class="gd-bias" data-dir="' + (signal.direction === "LONG" ? "long" : "short") + '">' + side + '</span></h2>'
    + '<div class="gd-rs-sub"><span>' + esc(card.unified?.label || signal.strategy_name) + '</span><span>' + esc(signal.timeframe || "") + '</span></div></div>'
    + '<button type="button" class="gd-rs-close" data-research-action="close" aria-label="Close signal details">×</button></header>'
    + '<div class="gd-rs-body">'
    + '<p class="gd-responsible" data-family="' + esc(card.unified?.family || "other") + '"><span>Strategy: <b>' + esc(card.unified?.label || signal.strategy_name) + '</b></span>'
    + '<span class="gd-validation" data-validation="' + esc(card.validation?.key || "experimental") + '">' + esc(card.validation?.label || "Experimental · not proven profitable") + '</span>'
    + ((card.confirmedBy || []).length > 1 ? '<span>Confirmed independently by: ' + card.confirmedBy.map(esc).join(", ") + '</span>' : '') + '</p>'
    + '<section class="gd-rs-section"><h4>Confirmed plan</h4><dl class="gd-rs-plan">' + cell("Entry", formatPrice(signal.entry)) + cell("Stop", formatPrice(signal.stop_loss), "is-stop")
    + cell("Target", formatPrice(signal.take_profit), "is-target") + cell("R:R", signal.rr == null ? null : "1:" + Number(signal.rr).toFixed(2)) + '</dl>'
    + '<p class="gd-note">Confirmed ' + esc(card.confirmationTime || signal.confirmed_at || "—") + ' on a completed ' + esc(signal.timeframe || "") + ' candle.'
    + (signal.time_exit_at ? ' Time exit ' + esc(formatUtc(signal.time_exit_at) || signal.time_exit_at) + '.' : '') + ' ' + esc(signal.execution_basis || "") + '</p></section>'
    + '<section class="gd-rs-section"><h4>Trade rationale</h4><p>' + esc(signal.explanation || "—") + '</p></section>'
    + '<section class="gd-rs-section"><h4>Contradicting evidence</h4>' + (notes.length ? '<ul>' + notes.map(note => '<li>' + esc(note) + '</li>').join("") + '</ul>' : '<p class="gd-na">None recorded at confirmation.</p>') + '</section>'
    + '<section class="gd-rs-section"><h4>Outcome</h4><p><b>' + esc(OUTCOME_LABEL[status] || status) + '</b>'
    + (rValue == null ? '' : ' · ' + esc(r(rValue))) + (signal.outcome_at ? ' · ' + esc(formatUtc(signal.outcome_at) || signal.outcome_at) : '') + '</p>'
    + '<p class="gd-note">Hypothetical signal outcome from MT5 candles, not an executed trade. Experimental strategies have not demonstrated profitability.</p></section>'
    + '</div>';
}

export function bankPanel(report) {
  if (!report) return '<p class="gd-na">Strategy Bank unavailable (engine offline).</p>';
  const rows = bankRows(report);
  const cell = value => value == null ? pending : esc(value);
  const live = '<div class="performance-table-wrap"><table class="performance-table gd-bank-table"><caption class="gd-bank-caption">Forward results: recorded signals and outcomes only (hypothetical R, not trades)</caption><thead><tr><th>#</th><th>STRATEGY</th><th>STATUS</th><th>VALIDATION</th><th>SIGNALS</th><th>WIN RATE</th><th>EXPECTANCY</th><th>MAX DD</th></tr></thead><tbody>'
    + rows.map(row => '<tr data-bank-strategy="' + esc(row.key) + '" class="gd-bank-' + esc(row.kind.toLowerCase()) + '"><td>' + row.n + '</td><td>' + esc(row.name)
      + '</td><td>' + esc(row.status) + '</td><td><span class="gd-validation" data-validation="' + esc(row.validation.key) + '">' + esc(row.validation.label) + '</span></td><td>' + (row.signals == null ? '<span class="gd-na">—</span>' : row.signals)
      + '</td><td>' + (row.kind === "UNSUPPORTED" ? '<span class="gd-na">—</span>' : cell(row.winRate)) + '</td><td>'
      + (row.kind === "UNSUPPORTED" ? '<span class="gd-na">—</span>' : cell(row.expectancy)) + '</td><td>'
      + (row.kind === "UNSUPPORTED" ? '<span class="gd-na">—</span>' : cell(row.drawdown)) + '</td></tr>').join("")
    + '</tbody></table></div>';
  const unsupported = rows.filter(row => row.reason).map(row => '<p class="gd-note"><b>' + esc(row.name) + ' is unsupported.</b> ' + esc(row.reason) + '</p>').join("");
  const hist = historicalRows(report);
  const historical = hist.length ? '<details class="gd-bank-historical"><summary>' + esc(report.historical.label) + '</summary>'
    + '<p class="gd-note">Simulated on past MT5 data with spreads, commission, slippage and overnight financing. These are not live results and do not count toward the live statistics above.</p>'
    + '<div class="performance-table-wrap"><table class="performance-table"><thead><tr><th>#</th><th>STRATEGY</th><th>TRADES</th><th>WIN RATE</th><th>EXPECTANCY (95% CI)</th><th>VERDICT</th></tr></thead><tbody>'
    + hist.map(row => '<tr><td>' + row.n + '</td><td>' + esc(row.name) + '</td><td>' + (row.trades ?? "—") + '</td><td>' + (row.winRate ?? "—") + '</td><td>'
      + (row.expectancy ? esc(row.expectancy) + (row.ci ? ' <small>(' + esc(row.ci) + ')</small>' : '') : "—") + '</td><td>' + esc(row.verdict) + '</td></tr>').join("")
    + '</tbody></table></div></details>' : '<p class="gd-na">No historical backtest has been run yet.</p>';
  const notes = (report.notes || []).map(note => '<li>' + esc(note) + '</li>').join("");
  return live + unsupported + historical + (notes ? '<ul class="gd-lab-rules">' + notes + '</ul>' : '');
}
