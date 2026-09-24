// TRADeden Garden markup. Pure string renderers (no DOM access) over the view
// models in gardenModel.mjs. Unavailable values are always shown explicitly.
import {GARDEN_STAGES} from "./gardenModel.mjs";
import {STRATEGY_STATUS, gardenResearchEntries, normalizeRegistry, shadowResults, strategyPerformance, strategyTag} from "../strategyModel.mjs";

export const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[c]));
const orUnavailable = (value, text = "Unavailable") => value == null || value === "" ? '<span class="gd-na">' + text + '</span>' : esc(value);

export const NOT_ADVICE = "Not an entry recommendation. TRADeden observes and explains; you make the decisions.";

export function counterTiles(counters) {
  const tiles = [
    ["watched", "Markets watched", "◎", "Instruments the engine scanned in its latest pass"],
    ["growing", "Growing", GARDEN_STAGES.growing.icon, GARDEN_STAGES.growing.description],
    ["confirming", "Taking shape", GARDEN_STAGES.shaping.icon, GARDEN_STAGES.shaping.description],
    ["bloomed", "Bloomed", GARDEN_STAGES.bloomed.icon, GARDEN_STAGES.bloomed.description],
    ["active", "Active", GARDEN_STAGES.active.icon, GARDEN_STAGES.active.description],
  ];
  return tiles.map(([key, label, icon, help]) =>
    '<div class="gd-counter gd-counter-' + key + '" title="' + esc(help) + '"><span class="gd-counter-icon" aria-hidden="true">' + icon + '</span>'
    + '<b data-counter="' + key + '">' + (counters?.[key] == null ? "—" : esc(counters[key])) + '</b><span>' + esc(label) + '</span></div>').join("");
}

function level(label, value, extraClass = "") {
  return '<div class="gd-level ' + extraClass + '"><span>' + label + '</span><b>' + (value == null ? '<span class="gd-na">Not yet calculated</span>' : esc(value)) + '</b></div>';
}

/** Compact strategy identity chip ("TRENDLINE", "S/R", ...). */
export function strategyChip(strategy) {
  if (!strategy) return "";
  return '<span class="gd-strategy-tag" data-strategy="' + esc(strategy.id) + '" title="Strategy: ' + esc(strategy.label) + '">' + esc(strategy.tag) + '</span>';
}

function directionBadge(card) {
  if (!card.direction) return '<span class="gd-dir gd-dir-none">No direction</span>';
  return '<span class="gd-dir gd-dir-' + card.direction.toLowerCase() + '">' + (card.direction === "LONG" ? "▲ LONG" : "▼ SHORT") + '</span>';
}

/**
 * One setup card. `evidenceHtml` is the (already rendered) analyst evidence for
 * the "View Evidence" section; pass null while it is loading or unavailable.
 */
export function setupCard(card, {selected = false, expanded = false, evidenceHtml = null, evidenceState = "idle", extraFoot = ""} = {}) {
  const id = esc(card.id || "");
  const trackable = Boolean(card.id) && !card.simulated;
  const facts = [];
  if (card.bucket === "history") {
    facts.push(["Closed", card.closedTime], ["Reason", card.closedReason]);
  } else {
    facts.push(["Confirmation", card.confirmationTime || (card.stage === "bloomed" || card.stage === "active" ? null : "Not confirmed yet")]);
  }
  if (card.latestObservation) facts.push(["Latest observation", card.latestObservation]);
  facts.push(["Session", card.session], ["Status", card.status]);
  if (card.bucket !== "history") facts.push(["Observed for", card.duration]);
  const factRows = facts.map(([label, value]) => '<div><span>' + label + '</span><b>' + orUnavailable(value) + '</b></div>').join("");
  const evidence = !expanded ? "" : '<div class="gd-evidence" id="evidence-' + id + '">'
    + (evidenceHtml || '<p class="gd-na">' + (evidenceState === "loading" ? "Loading recorded evidence…" : "No recorded analyst evidence for this setup.") + '</p>') + '</div>';
  return '<article class="gd-card gd-tone-' + card.tone + ' gd-stage-' + card.stage + (selected ? ' is-selected' : '') + (card.tracked ? ' is-tracked' : '')
    + '" data-key="' + esc(card.key || "") + '" data-setup-id="' + id + '" tabindex="0" aria-selected="' + selected + '">'
    + '<header class="gd-card-head"><div class="gd-card-title"><h3><i class="gd-swatch gd-swatch-' + card.stage + ' gd-swatch-' + String(card.direction || "none").toLowerCase() + '" aria-hidden="true"></i>' + esc(card.symbol) + '</h3>'
    + '<span class="gd-stage-chip"><span aria-hidden="true">' + card.stageIcon + '</span> ' + esc(card.headline) + '</span></div>'
    + '<div class="gd-score" aria-label="Setup score">' + (card.score == null ? '<b class="gd-na">—</b>' : '<b>' + card.score + '</b>') + '<span>/ 100</span></div></header>'
    + '<div class="gd-card-sub">' + strategyChip(card.strategy) + directionBadge(card) + '<span>' + orUnavailable(card.setupType, "Setup type unavailable") + (card.timeframe ? ' · ' + esc(card.timeframe) : '') + '</span>'
    + (card.tracked ? '<span class="gd-tracked-flag">Tracking</span>' : '') + '</div>'
    + (card.levels.planned
      ? '<div class="gd-levels">' + level("Entry", card.levels.entry) + level("Stop", card.levels.stop, "gd-level-stop")
        + level("Target", card.levels.target, "gd-level-target") + level("R:R", card.levels.rr) + '</div>'
      : '<p class="gd-levels-pending">Entry, stop, target and R:R appear once the engine calculates a stop and a target.</p>')
    + '<div class="gd-why"><span>Why TRADeden sees it</span><p>' + (card.why ? esc(card.why) : '<span class="gd-na">No explanation was recorded for this observation.</span>') + '</p></div>'
    + '<div class="gd-facts">' + factRows + '</div>'
    + evidence
    + '<footer class="gd-card-foot"><div class="gd-actions">'
    + '<button type="button" data-action="view-setup">View setup</button>'
    + '<button type="button" data-action="view-evidence" aria-expanded="' + expanded + '"' + (card.id ? '' : ' disabled') + '>' + (expanded ? 'Hide evidence' : 'View evidence') + '</button>'
    + '<button type="button" data-action="view-analysis">View analysis</button>'
    + (trackable ? '<button type="button" data-action="track" aria-pressed="' + card.tracked + '">' + (card.tracked ? 'Tracking ✓' : 'Track setup') + '</button>' : '')
    + '</div><small class="gd-disclaimer">Not an entry recommendation. The trader makes the final decision.</small>' + extraFoot + '</footer>'
    + '</article>';
}

export function emptyArea(title, text) {
  return '<div class="gd-empty"><b>' + esc(title) + '</b><p>' + esc(text) + '</p></div>';
}

export function marketOverview(rows) {
  if (!rows.length) return emptyArea("No market data", "The engine has not returned any instruments.");
  return '<div class="gd-market-head" aria-hidden="true"><span>Market</span><span>Price</span><span>Bias · state</span><span>Setup</span></div>'
    + rows.map(row => '<button type="button" class="gd-market-row' + (row.conflict ? ' has-conflict' : '') + '" data-symbol="' + esc(row.symbol) + '">'
      + '<b>' + esc(row.symbol) + '</b>'
      + '<span class="gd-market-price">' + orUnavailable(row.price) + '<small class="gd-' + row.changeTone + '">' + (row.change ? esc(row.change) : '') + '</small></span>'
      + '<span class="gd-market-bias"><span class="gd-market-dir gd-dir-text-' + esc(String(row.direction || "none").toLowerCase()) + '">' + orUnavailable(row.direction, "—") + '</span>'
      + '<small class="gd-market-state">' + orUnavailable(row.state, "—") + '</small></span>'
      + '<span class="gd-market-setup">' + (row.stage ? GARDEN_STAGES[row.stage].icon + ' ' : '') + esc(row.setupStatus) + '</span>'
      + strategyMatrixLine(row) + researchLine(row)
      + '</button>').join("");
}

/**
 * Per-strategy results under a market row, only when more than one strategy
 * reported (with the single trendline strategy the row itself is its result).
 * A conflict shows both sides; neither is hidden.
 */
export function strategyMatrixLine(row) {
  // Live strategies only: shadow-mode results are reviewed in the Strategy Lab, never here.
  const entries = (row?.strategies || []).filter(entry => entry.live);
  if (entries.length < 2 && !row?.conflict) return "";
  const cell = entry => '<span class="gd-matrix-cell' + (entry.live ? '' : ' is-not-live') + '">' + esc(entry.tag) + ' '
    + (entry.status === "ERROR" ? 'unavailable' : entry.direction ? (entry.direction === "LONG" ? "▲ BUY" : "▼ SELL") : '—') + '</span>';
  return '<span class="gd-market-matrix">'
    + (row.conflict ? '<b class="gd-conflict-badge" title="Live strategies disagree on direction; both are shown.">Strategy conflict</b>' : '')
    + entries.map(cell).join("") + '</span>';
}

/**
 * Research (SHADOW) results a strategy opted in to show here, on their own labelled line:
 * RESEARCH badge, strategy tag, direction, state and score. Not setups, not alerts.
 */
export function researchLine(row) {
  const entries = gardenResearchEntries(row?.strategies);
  if (!entries.length) return "";
  return '<span class="gd-market-research" title="Research strategy: recorded for measurement only. Not a live setup, not an alert, not a trade signal.">'
    + '<span class="gd-shadow-badge">RESEARCH</span>'
    + entries.map(entry => '<span class="gd-matrix-cell is-research" data-strategy="' + esc(entry.id) + '"'
      + (entry.plan ? ' title="' + esc('Entry ' + entry.plan.entry + ' · Stop ' + entry.plan.stop + ' · Target ' + entry.plan.target) + '"' : '') + '>' + esc(entry.tag) + ' '
      + (entry.direction === "LONG" ? "▲ LONG" : "▼ SHORT") + ' · ' + esc(entry.state) + (entry.confirmed ? ' · research confirmed' : '')
      + (entry.score == null ? '' : ' · ' + esc(entry.score)) + '</span>').join("")
    + '</span>';
}

/** Strategy filter buttons; strategies that are not registered cannot be selected. */
export function strategyFilterBar(filters, selected = "all") {
  return '<div class="gd-strategy-filters" role="group" aria-label="Filter by strategy"><span class="gd-strategy-filters-label">Strategy</span>'
    + filters.map(filter => '<button type="button" data-strategy-filter="' + esc(filter.key) + '" aria-pressed="' + (filter.key === selected) + '"'
      + (filter.selectable ? '' : ' disabled')
      + ' title="' + esc(filter.label + (filter.key === "all" ? "" : " · " + (STRATEGY_STATUS[filter.status] || filter.status))) + '">'
      + esc(filter.key === "all" ? "All" : filter.tag)
      + (filter.key !== "all" && filter.status !== "LIVE" ? '<small>' + (filter.status === "SHADOW" ? "shadow" : "not live") + '</small>' : '')
      + '</button>').join("") + '</div>';
}

/**
 * Strategy Lab: every registered strategy and its status. Shadow-mode results
 * (none exist yet) are reviewed here only and never shown as live Garden setups.
 */
export function strategyLabPanel(registry, {markets = [], performance = null} = {}) {
  const entries = normalizeRegistry(registry);
  const shadow = entries.filter(entry => entry.status === "SHADOW");
  const results = shadowResults(markets, registry);
  const cell = value => value == null || value === "" ? '<span class="gd-na">—</span>' : esc(value);
  const table = !shadow.length ? '' : '<div class="gd-lab-shadow"><h4><span class="gd-shadow-badge">SHADOW</span> Current shadow results</h4>'
    + '<p class="gd-note">Evaluated on every scan and recorded for research. Not live setups, not alerts, not trade signals.</p>'
    + (results.length ? '<div class="performance-table-wrap"><table class="performance-table gd-lab-table"><thead><tr><th>MARKET</th><th>STRATEGY</th><th>STATE</th><th>DIRECTION</th><th>SHADOW CONFIRMED</th></tr></thead><tbody>'
      + results.map(row => '<tr><th>' + esc(row.symbol) + '</th><td>' + esc(row.tag) + '</td><td>' + (row.status === "ERROR" ? 'unavailable' : cell(row.state)) + '</td><td>'
        + cell(row.direction) + '</td><td>' + (row.confirmed ? 'yes' : 'no') + '</td></tr>').join("") + '</tbody></table></div>'
      : '<p class="gd-na">No shadow results in the latest scan.</p>')
    + shadow.map(entry => {
      const perf = strategyPerformance(performance, entry.id);
      return perf ? '<p class="gd-note"><b>' + esc(perf.tag) + ' research, ' + esc(perf.horizon) + ' market outcome:</b> ' + perf.win + ' target first · ' + perf.loss
        + ' stop first · ' + perf.pending + ' pending · ' + perf.noHit + ' no hit · ' + perf.ambiguous + ' ambiguous (shadow confirmations only; never mixed with live results)</p>' : '';
    }).join("") + '</div>';
  return '<ul class="gd-lab-list">' + entries.map(entry => {
    const {tag, label} = strategyTag(entry.id);
    return '<li class="gd-lab-item gd-lab-' + esc(entry.status.toLowerCase()) + '"><b>' + esc(tag) + '</b><span>' + esc(label) + '</span>'
      + '<em>' + esc(STRATEGY_STATUS[entry.status] || entry.status) + (entry.assumed ? ' (engine offline, assumed)' : '') + '</em>'
      + (entry.version ? '<small>' + esc(entry.version) + '</small>' : '') + '</li>';
  }).join("") + '</ul>' + table
    + '<p class="gd-note">' + (shadow.length
      ? 'Shadow-mode strategies are evaluated for review only. Their results never appear as Garden setups.'
      : 'No shadow-mode strategies are registered. Future strategies are reviewed here before they can produce live Garden setups.') + '</p>';
}

/** Per-strategy market-outcome counts, straight from the backend report (no derived rates). */
export function strategyPerformanceBlock(perf, strategy, {shadow = false} = {}) {
  const label = shadow ? '<p class="gd-note"><span class="gd-shadow-badge">SHADOW</span> Research only: this strategy runs in shadow mode. Not live results.</p>' : '';
  if (!perf) return label + '<div class="macro-empty"><b>No confirmed ' + esc(strategy.label) + ' setups in this period</b><span>Only this strategy&#039;s confirmations are counted here.</span></div>';
  return label + '<div class="performance-headline"><b>' + perf.win + 'W / ' + perf.loss + 'L</b><span>' + esc(perf.tag) + ' only · ' + esc(perf.horizon) + ' market outcome</span></div>'
    + '<div class="performance-table-wrap"><table class="performance-table"><thead><tr><th>STRATEGY</th><th>W</th><th>L</th><th>PENDING</th><th>NO HIT</th><th>AMBIGUOUS</th></tr></thead><tbody>'
    + '<tr><th>' + esc(perf.tag) + '</th><td>' + perf.win + '</td><td>' + perf.loss + '</td><td>' + perf.pending + '</td><td>' + perf.noHit + '</td><td>' + perf.ambiguous + '</td></tr></tbody></table></div>'
    + '<small>Per-strategy view shows the ' + esc(perf.horizon) + ' primary horizon only. Strategies are never combined here.</small>';
}

function list(items, emptyText) {
  return items.length ? '<ul>' + items.map(item => '<li>' + esc(item) + '</li>').join("") + '</ul>' : '<p class="gd-na">' + esc(emptyText) + '</p>';
}

export function analystPanel(model, {loading = false, simulated = false} = {}) {
  if (!model) {
    return '<div class="gd-analyst-empty"><span aria-hidden="true">🧠</span><b>Select a setup</b><p>Choose any card or orb to see how TRADeden reads it.</p></div>';
  }
  const stage = GARDEN_STAGES[model.stage];
  const levels = model.levels;
  const history = model.context === "history";
  const rr = [["Entry", levels.entry], ["Stop", levels.stop], ["Target", levels.target], ["Reward : risk", levels.rr]];
  const outcome = model.outcome;
  const outcomeBlock = !history ? '' : '<section class="gd-analyst-outcome"><h4>Outcome</h4>' + (outcome
    ? '<p class="gd-outcome-line gd-outcome-' + esc(outcome.kind) + '"><b>' + outcome.icon + ' ' + esc(outcome.label) + '</b>'
      + (outcome.horizon ? ' within ' + esc(outcome.horizon) : '') + (outcome.rText ? ' · ' + esc(outcome.rText) : '') + '</p>'
      + '<p class="gd-note">' + (outcome.confirmed
        ? (outcome.kind === "unverified" || outcome.kind === "pending"
          ? 'No outcome is shown as known until its timestamps pass TRADeden\'s data-integrity checks.'
          : 'Market path after confirmation, labelled target-before-stop. Not a trade result.')
        : 'Not a trade: the setup closed before confirmation.') + '</p>'
    : '<p class="gd-na">Outcome unavailable.</p>') + '</section>';
  return '<div class="gd-analyst-head"><div><span class="gd-eyebrow">🧠 TRADeden Analyst' + (history ? ' · record' : '') + '</span><h3>' + esc(model.symbol) + ' <small>' + stage.icon + ' ' + esc(stage.label)
    + (model.direction ? ' · ' + esc(model.direction) : '') + '</small></h3></div></div>'
    + (simulated ? '<p class="gd-analyst-sim">Simulated fixture — not market data.</p>' : '')
    + (history ? '<p class="gd-analyst-record">This setup has closed. What follows is the recorded analysis, not a live read of the market.</p>' : '')
    + '<section><h4>' + esc(model.titles.happening) + '</h4><p>' + (model.happening ? esc(model.happening) : '<span class="gd-na">No summary recorded.</span>') + '</p></section>'
    + '<section><h4>' + esc(model.titles.matters) + '</h4><p>' + (model.matters ? esc(model.matters) : '<span class="gd-na">No scanner reasoning recorded.</span>') + '</p></section>'
    + '<section><h4>' + esc(model.titles.confirms) + '</h4>' + (loading && !model.neverConfirmed ? '<p class="gd-na">Loading recorded evidence…</p>' : list(model.confirms, model.confirmsEmpty))
    + (model.stillNeeded.length ? '<h5>Still missing</h5>' + list(model.stillNeeded, "") : '')
    + (model.watchingFor ? '<h5>Watching for</h5><p>' + esc(model.watchingFor) + '</p>' : '') + '</section>'
    + '<section><h4>' + esc(model.titles.invalidates) + '</h4>' + list(model.invalidates, model.invalidatesEmpty) + '</section>'
    + outcomeBlock
    + (history && !levels.planned ? '' : '<section><h4>' + (history ? 'Planned risk / reward' : 'Risk / reward structure') + '</h4><div class="gd-analyst-levels">'
      + rr.map(([label, value]) => '<div><span>' + label + '</span><b>' + (value == null ? '<span class="gd-na">Not yet calculated</span>' : esc(value)) + '</b></div>').join("")
      + '</div>' + (levels.planned ? '' : '<p class="gd-note">Levels appear only once the engine calculates both a stop and a target.</p>') + '</section>')
    + '<p class="gd-analyst-method">Rule-based analysis' + (model.analystVersion ? ' (' + esc(model.analystVersion) + ')' : '')
    + ' — it restates recorded scanner evidence. It is not an AI or machine-learning prediction and does not forecast outcomes.</p>'
    + '<p class="gd-disclaimer-strong">' + esc(NOT_ADVICE) + '</p>';
}

export function stageLegend() {
  return Object.values(GARDEN_STAGES).map(stage => '<span class="gd-legend-item gd-legend-' + stage.key + '"><i class="gd-legend-dot" aria-hidden="true"></i>' + esc(stage.label) + '</span>').join("")
    + '<span class="gd-legend-item gd-legend-dir"><i class="gd-legend-dot gd-dot-long" aria-hidden="true"></i>Long <i class="gd-legend-dot gd-dot-short" aria-hidden="true"></i>Short</span>';
}

export const ARCHIVE_FILTERS = [["all", "All"], ["confirmed", "Confirmed"], ["target", "🎯 Target hit"], ["stop", "🛑 Stop hit"], ["invalidated", "⚠️ Invalidated"], ["expired", "⏳ Expired"]];
export function archiveMatches(entry, filter) {
  if (filter === "all") return true;
  if (filter === "confirmed") return entry.confirmed;
  return entry.kind === filter;
}

/** Compact archive of closed setups and what happened to them. */
export function archivePanel(entries, summary, {filter = "all", selectedKey = null, expanded = false, limit = 14} = {}) {
  const shown = entries.filter(entry => archiveMatches(entry, filter));
  const visible = expanded ? shown : shown.slice(0, limit);
  const stat = (value, label, cls = "") => '<span class="gd-arch-stat ' + cls + '"><b>' + value + '</b>' + label + '</span>';
  const note = summary.confirmed && !summary.verifiedOutcomes
    ? '<p class="gd-arch-note">Outcomes of confirmed setups stay <b>unverified</b> until their timestamps pass TRADeden\'s data-integrity checks. Nothing is counted as a target or stop hit before that.</p>' : '';
  const rows = visible.map(entry => '<button type="button" class="gd-arch-row gd-arch-' + entry.tone + (entry.key === selectedKey ? ' is-selected' : '') + '" data-archive-key="' + esc(entry.key || "") + '">'
    + '<span class="gd-arch-symbol"><b>' + esc(entry.symbol) + '</b>' + strategyChip(entry.strategy) + '<small>' + (entry.direction ? esc(entry.direction) : 'No direction') + (entry.confirmed ? ' · confirmed' : ' · not confirmed') + '</small></span>'
    + '<span class="gd-arch-badge"><i aria-hidden="true">' + entry.icon + '</i>' + esc(entry.label) + (entry.horizon ? '<small>within ' + esc(entry.horizon) + '</small>' : '') + '</span>'
    + '<span class="gd-arch-r">' + (entry.rText ? esc(entry.rText) : '') + '</span>'
    + '<span class="gd-arch-time">' + (entry.closedTime ? esc(entry.closedTime) : '<span class="gd-na">Time unavailable</span>') + '</span>'
    + '</button>').join("");
  return '<div class="gd-arch-summary">'
    + stat(summary.observed, 'setups observed')
    + stat(summary.confirmed, 'confirmed', 'is-confirmed')
    + stat(summary.target, '🎯 target hit', 'is-target')
    + stat(summary.stop, '🛑 stop hit', 'is-stop')
    + stat(summary.unverified, 'outcome unverified')
    + stat(summary.invalidated, '⚠️ invalidated before confirmation')
    + stat(summary.expired, '⏳ expired')
    + '</div>' + note
    + '<div class="gd-arch-filters" role="group" aria-label="Filter the archive">' + ARCHIVE_FILTERS.map(([key, label]) =>
      '<button type="button" data-archive-filter="' + key + '" aria-pressed="' + (key === filter) + '">' + label + '</button>').join("") + '</div>'
    + (shown.length ? '<div class="gd-arch-list">' + rows + '</div>' : '<div class="gd-empty"><b>Nothing here</b><p>No closed setups match this filter.</p></div>')
    + (shown.length > limit ? '<button type="button" class="gd-link gd-arch-more" data-toggle="history" aria-expanded="' + expanded + '">' + (expanded ? 'Show fewer' : 'Show all ' + shown.length) + '</button>' : '');
}

/** Compact focus panel shown inside the garden world for the selected orb/card. */
export function focusPanel(card) {
  if (!card) return "";
  const levels = card.levels?.planned
    ? '<dl class="gd-focus-levels"><div><dt>Entry</dt><dd>' + esc(card.levels.entry) + '</dd></div><div><dt>Stop</dt><dd>' + esc(card.levels.stop)
      + '</dd></div><div><dt>Target</dt><dd>' + esc(card.levels.target) + '</dd></div><div><dt>R:R</dt><dd>' + (card.levels.rr ? esc(card.levels.rr) : '—') + '</dd></div></dl>'
    : '';
  return '<div class="gd-focus-head"><i class="gd-swatch gd-swatch-' + card.stage + ' gd-swatch-' + String(card.direction || "none").toLowerCase() + '" aria-hidden="true"></i>'
    + '<div><b>' + esc(card.symbol) + '</b><span>' + card.stageIcon + ' ' + esc(card.headline) + '</span></div>'
    + (card.score == null ? '' : '<strong>' + card.score + '<small>/100</small></strong>') + '</div>'
    + (card.simulated ? '<p class="gd-analyst-sim">Simulated fixture — not market data.</p>' : '')
    + levels
    + '<p class="gd-focus-meta">' + (card.session ? esc(card.session) + ' session' : 'Session unavailable') + (card.confirmationTime ? ' · confirmed ' + esc(card.confirmationTime) : '') + '</p>'
    + '<div class="gd-focus-actions"><button type="button" data-focus-action="view-setup">View setup</button><button type="button" data-focus-action="view-analysis">View analysis</button></div>';
}
