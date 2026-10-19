// Strategy Bank views. Pure functions over /api/strategy-bank; no DOM access.
// Live columns show ONLY recorded signals and outcomes ("Pending" until a signal has resolved).
// Historical backtest results are shown separately and labelled as simulated, never as live results.
import {esc} from "./gardenCards.mjs";

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
    n: row.n, key: row.key, name: row.name, status: bankStatus(row, worker), kind: row.status,
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

export function bankPanel(report) {
  if (!report) return '<p class="gd-na">Strategy Bank unavailable (engine offline).</p>';
  const rows = bankRows(report);
  const cell = value => value == null ? pending : esc(value);
  const live = '<div class="performance-table-wrap"><table class="performance-table gd-bank-table"><thead><tr><th>#</th><th>STRATEGY</th><th>STATUS</th><th>SIGNALS</th><th>WIN RATE</th><th>EXPECTANCY</th><th>MAX DD</th></tr></thead><tbody>'
    + rows.map(row => '<tr data-bank-strategy="' + esc(row.key) + '" class="gd-bank-' + esc(row.kind.toLowerCase()) + '"><td>' + row.n + '</td><td>' + esc(row.name)
      + '</td><td>' + esc(row.status) + '</td><td>' + (row.signals == null ? '<span class="gd-na">—</span>' : row.signals)
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
