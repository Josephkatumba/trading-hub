// TRADeden Garden markup. Pure string renderers (no DOM access) over the view
// models in gardenModel.mjs. Unavailable values are always shown explicitly.
import {GARDEN_STAGES, LIFECYCLE_STEPS, formatPrice} from "./gardenModel.mjs";
import {STRATEGY_STATUS, gardenResearchEntries, normalizeRegistry, shadowResults, strategyPerformance, strategyTag} from "../strategyModel.mjs";
import {confirmationToastModel} from "../confirmationAlerts.mjs";

export const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[c]));
const orUnavailable = (value, text = "Unavailable") => value == null || value === "" ? '<span class="gd-na">' + text + '</span>' : esc(value);

export const NOT_ADVICE = "Not an entry recommendation. TRADeden observes and explains; you make the decisions.";

/** Confirmed-setup notification card: strategy, symbol, direction, setup, score, time, evidence. */
export function confirmationToastHtml(event) {
  const toast = confirmationToastModel(event);
  return '<article class="confirmation-toast-card" data-confirmation-toast="' + esc(String(event?.setup_id || "unknown")) + '" data-strategy="' + esc(toast.strategyId) + '">'
    + '<b>🌸 ' + esc(toast.title) + '</b><strong>' + esc(toast.headline) + '</strong>'
    + '<span>Setup · ' + esc(toast.setup) + '</span><span>Score · ' + esc(toast.score) + '</span>'
    + '<small>Confirmation time · ' + esc(toast.confirmedAt) + '</small>'
    + (toast.evidence ? '<small class="confirmation-toast-evidence">' + esc(toast.evidence) + '</small>' : '')
    + '<small class="confirmation-toast-note">' + esc(toast.note) + '</small></article>';
}

/** Per-strategy split of the live Garden counters ("TRENDLINE 3 · S/R 2 · TREND/MOM 4"). */
export function strategyBreakdownLine(breakdown) {
  if (!breakdown?.length) return "";
  return '<div class="gd-counter-breakdown" aria-label="Live setups by strategy">'
    + breakdown.map(item => '<span data-strategy="' + esc(item.id) + '">' + esc(item.tag) + ' <b>' + Number(item.count) + '</b></span>').join("")
    + '</div>';
}

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
    + '<b data-counter="' + key + '">' + (counters?.[key] == null ? "—" : esc(counters[key])) + '</b><span>' + esc(label) + '</span></div>').join("")
    + strategyBreakdownLine(counters?.byStrategy);
}

function level(label, value, extraClass = "") {
  return '<div class="gd-level ' + extraClass + '"><span>' + label + '</span><b>' + (value == null ? '<span class="gd-na">Not yet calculated</span>' : esc(value)) + '</b></div>';
}

/** Compact strategy identity chip ("TRENDLINE", "S/R", ...); its glyph and colour come from CSS by data-strategy. */
export function strategyChip(strategy, version = null) {
  if (!strategy) return "";
  return '<span class="gd-strategy-tag" data-strategy="' + esc(strategy.id) + '" title="Strategy: ' + esc(strategy.label) + (version ? ' · ' + esc(version) : '') + '">' + esc(strategy.tag) + '</span>';
}

/** Score as a ring: the arc is the backend score out of 100 (null: an empty dashed ring). */
export function scoreRing(score, size = 46) {
  const r = size / 2 - 4, c = 2 * Math.PI * r;
  const arc = score == null ? 0 : Math.max(0, Math.min(100, Number(score))) / 100 * c;
  return '<svg class="gd-ring" viewBox="0 0 ' + size + ' ' + size + '" width="' + size + '" height="' + size + '" aria-hidden="true">'
    + '<circle class="gd-ring-track" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '"/>'
    + (score == null ? '' : '<circle class="gd-ring-arc" cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r + '" stroke-dasharray="' + arc.toFixed(2) + ' ' + c.toFixed(2) + '" transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')"/>')
    + '</svg>';
}

/**
 * Stop -> risk -> entry -> potential move -> target on a low-to-high price axis
 * (a SHORT is the mirror). Widths are the backend's own risk and reward
 * distances, so a stop sitting beside the entry shows as a hairline.
 */
export function riskBar(risk, {compact = false} = {}) {
  if (!risk) return "";
  const share = key => (key === "risk" ? risk.riskShare : risk.rewardShare);
  const segment = key => '<span class="gd-risk-seg gd-risk-' + key + '" style="flex-grow:' + share(key).toFixed(4) + '">'
    + '<em>' + (key === "risk" ? "risk" : "potential move") + '</em></span>';
  const [first, second] = risk.segments;
  const meta = [risk.rr ? 'R:R <b>' + esc(risk.rr) + '</b>' : null,
    risk.structural ? 'Structural stop' : null,
    risk.stopAtr != null ? esc(risk.stopAtr.toFixed(2)) + ' ATR(H1)' : null].filter(Boolean);
  return '<div class="gd-risk' + (compact ? ' is-compact' : '') + '" data-direction="' + esc(risk.direction) + '" aria-label="Risk and reward on the price axis">'
    + '<div class="gd-risk-track">' + segment(first) + '<i class="gd-risk-entry" aria-hidden="true"></i>' + segment(second) + '</div>'
    + '<div class="gd-risk-axis">' + risk.axis.map(point => '<span class="gd-risk-' + point.key + '-label"><small>' + point.label + '</small>' + esc(point.value) + '</span>').join("") + '</div>'
    + '<div class="gd-risk-meta">' + meta.map(item => '<span>' + item + '</span>').join("")
    + (risk.quality ? '<span class="gd-quality gd-quality-' + esc(risk.quality.tone) + '" title="' + esc(risk.quality.help) + '">' + esc(risk.quality.label) + '</span>' : '')
    + '<span class="gd-risk-basis">' + (risk.basis === "confirmation" ? "Confirmed plan" : "Latest observation") + '</span></div>'
    + '</div>';
}

/** WATCHING -> ... -> CLOSED, from the backend's lifecycle events. */
export function lifecycleRailHtml(rail) {
  if (!rail) return "";
  return '<ol class="gd-rail" aria-label="Lifecycle">' + rail.steps.map(step => '<li class="gd-rail-step'
    + (step.reached ? ' is-reached' : '') + (step.current ? ' is-current' : '') + (step.step === "CLOSED" && rail.terminal ? ' is-closed' : '') + '"'
    + (step.time ? ' title="' + esc(step.label + ' · ' + step.time) + '"' : '') + '><i aria-hidden="true"></i><span>' + esc(step.label) + '</span></li>').join("") + '</ol>';
}

function directionBadge(card) {
  if (!card.direction) return '<span class="gd-dir gd-dir-none">No direction</span>';
  return '<span class="gd-dir gd-dir-' + card.direction.toLowerCase() + '">' + (card.direction === "LONG" ? "▲ LONG" : "▼ SHORT") + '</span>';
}

/**
 * One setup card. `evidenceHtml` is the (already rendered) analyst evidence for
 * the "View Evidence" section; pass null while it is loading or unavailable.
 */
export function setupCard(card, {selected = false, expanded = false, evidenceHtml = null, evidenceState = "idle", extraFoot = "", compact = false} = {}) {
  if (compact && card.watching) return seedRow(card, {selected});
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
    + '" data-key="' + esc(card.key || "") + '" data-setup-id="' + id + '" data-strategy="' + esc(card.strategy?.id || "") + '" tabindex="0" aria-selected="' + selected + '">'
    + '<header class="gd-card-head"><div class="gd-node" aria-hidden="true"><i class="gd-swatch gd-swatch-' + card.stage + ' gd-swatch-' + String(card.direction || "none").toLowerCase() + '"></i></div>'
    + '<div class="gd-card-title"><h3>' + esc(card.symbol) + '</h3>'
    + '<span class="gd-stage-chip"><span aria-hidden="true">' + card.stageIcon + '</span> ' + esc(card.headline) + '</span></div>'
    + '<div class="gd-score" aria-label="Setup score">' + scoreRing(card.score) + (card.score == null ? '<b class="gd-na">—</b>' : '<b>' + card.score + '</b>') + '<span>/ 100</span></div></header>'
    + '<div class="gd-card-sub">' + strategyChip(card.strategy, card.strategyVersion) + directionBadge(card) + '<span>' + orUnavailable(card.setupType, "Setup type unavailable") + (card.timeframe ? ' · ' + esc(card.timeframe) : '') + '</span>'
    + (card.strategyVersion ? '<small class="gd-version">' + esc(card.strategyVersion) + '</small>' : '')
    + (card.tracked ? '<span class="gd-tracked-flag">Tracking</span>' : '') + '</div>'
    + lifecycleRailHtml(card.rail)
    + (card.levels.planned
      ? '<div class="gd-levels">' + level("Entry", card.levels.entry) + level("Stop", card.levels.stop, "gd-level-stop")
        + level("Target", card.levels.target, "gd-level-target") + level("R:R", card.levels.rr) + '</div>' + riskBar(card.risk)
        + (card.planDrift ? '<p class="gd-plan-note">Confirmed plan shown. The latest observation re-evaluates at the live price and does not change it.</p>' : '')
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

/** A watching (detected) setup: a quiet seed, one line, until it develops. */
export function seedRow(card, {selected = false} = {}) {
  return '<button type="button" class="gd-seed' + (selected ? ' is-selected' : '') + '" data-key="' + esc(card.key || "") + '" data-seed="1" data-strategy="' + esc(card.strategy?.id || "") + '">'
    + '<i class="gd-seed-dot gd-seed-' + String(card.direction || "none").toLowerCase() + '" aria-hidden="true"></i>'
    + '<b>' + esc(card.symbol) + '</b>' + strategyChip(card.strategy, card.strategyVersion)
    + '<span>' + (card.direction ? esc(card.direction) : 'No direction') + ' · watching' + (card.setupType ? ' · ' + esc(card.setupType) : '') + '</span>'
    + '<em>' + (card.score == null ? '—' : card.score) + '</em></button>';
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

/**
 * Strategy filter buttons. Only registered strategies appear: names that are not
 * registered (SMC, CRT, ICT) are not part of the Garden at all.
 */
export function strategyFilterBar(filters, selected = "all") {
  return '<div class="gd-strategy-filters" role="group" aria-label="Filter by strategy"><span class="gd-strategy-filters-label">Strategy</span>'
    + filters.filter(filter => filter.status !== "UNAVAILABLE").map(filter => '<button type="button" data-strategy-filter="' + esc(filter.key) + '" aria-pressed="' + (filter.key === selected) + '" data-strategy="' + esc(filter.key) + '"'
      + (filter.selectable ? '' : ' disabled')
      + ' title="' + esc(filter.label + (filter.key === "all" ? " · combined view" : " · " + (STRATEGY_STATUS[filter.status] || filter.status) + (filter.version ? " · " + filter.version : ""))) + '">'
      + (filter.key === "all" ? "All" : '<i class="gd-glyph" aria-hidden="true"></i>' + esc(filter.tag))
      + (filter.key !== "all" && filter.status === "LIVE" ? '<small class="gd-live">LIVE</small>' : '')
      + (filter.key !== "all" && filter.status !== "LIVE" ? '<small>' + (filter.status === "SHADOW" ? "shadow" : "not live") + '</small>' : '')
      + '</button>').join("") + '</div>';
}

/** Header: the LIVE strategies, each with its live-setup count. */
export function headerStrategies(model) {
  const strategies = model.strategies.length ? model.strategies.map(strategy => '<span class="gd-hstrategy" data-strategy="' + esc(strategy.id) + '" title="' + esc(strategy.label + (strategy.version ? ' · ' + strategy.version : '')) + '">'
    + '<i class="gd-glyph" aria-hidden="true"></i><span><small class="gd-live">LIVE</small>' + esc(strategy.label) + (strategy.version ? '<em>' + esc(strategy.version) + '</em>' : '') + '</span>'
    + '<b class="gd-hcount" title="Live setups" data-stat="strategy-' + esc(strategy.id) + '">' + esc((model.byStrategy || []).find(item => item.id === strategy.id)?.count ?? 0) + '</b></span>').join("")
    : '<span class="gd-na">Strategy registry unavailable</span>';
  return '<div class="gd-hstrategies" aria-label="Live strategies">' + strategies + '</div>';
}

/** Header: the numbers that matter (null is "unavailable", never 0). */
export function headerStats(model) {
  const stat = (key, value, label, cls) => '<span class="gd-hstat ' + cls + '"><b data-stat="' + key + '">' + (value == null ? '—' : esc(value)) + '</b>' + label + '</span>';
  return '<div class="gd-hstats" aria-label="Garden status">'
    + stat("instruments", model.instruments, 'instruments', 'is-instruments') + stat("confirmed", model.confirmed, 'confirmed', 'is-confirmed')
    + stat("developing", model.developing, 'developing', 'is-developing') + stat("watching", model.watching, 'watching', 'is-watching')
    + '<span class="gd-hstat is-scan"><b>' + (model.lastScan ? esc(model.lastScan) : '—') + '</b>last scan</span></div>';
}

/** The compact Garden header: identity, LIVE strategies and the few numbers that matter. */
export function gardenHeader(model) {
  return headerStrategies(model) + headerStats(model);
}

// ----- shared chip helpers ------------------------------------------------------------
const dirKey = value => {
  const v = String(value || "").toUpperCase();
  return v === "LONG" || v === "BULLISH" ? "long" : v === "SHORT" || v === "BEARISH" ? "short" : "none";
};
const lifeKey = value => String(value || "none").toLowerCase().replace(/[^a-z]+/g, "-");

// ----- Priority Watch: the 4-market attention window + the full market view ----------
const signedPct = value => value == null ? null : (value >= 0 ? "+" : "") + value.toFixed(2) + "%";
/** Compact age of the latest meaningful event ("now", "12m", "3h", "2d"). */
export function eventAge(ms) {
  if (ms == null) return null;
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return minutes + "m";
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? hours + "h" : Math.floor(hours / 24) + "d";
}
const PRIORITY_NOTE = "Attention order, not a trade ranking: lifecycle stage first, then the engine's setup score, strategy agreement and recency. Core markets stay in view but never outrank a setup.";

/** One market in the Priority Watch (compact) or the full Market Watch (`full`). */
export function priorityWatchRow(entry, {rank = null, selected = false, entering = false, full = false} = {}) {
  const signals = entry.signals.filter(signal => full || signal.direction);
  const life = entry.lifecycle || (entry.tier ? "WATCHING" : null);
  // Disagreeing strategies are never summarised as one direction: the row goes neutral.
  const side = entry.conflict ? "conflict" : dirKey(entry.direction);
  const basis = life && entry.basis ? entry.basis : null;
  const age = eventAge(entry.ageMs);
  const basisHelp = basis === "scan" ? "Live scan: a strategy's current evaluation. No recorded episode yet, so the Garden's setup sections may not show it."
    : "Recorded: the setup's recorded lifecycle, as shown in the Garden.";
  return '<button type="button" class="gd-pw-row gd-market-row' + (selected ? ' is-selected' : '') + (entering ? ' is-entering' : '') + (entry.core ? ' is-core' : '') + '"'
    + ' data-symbol="' + esc(entry.symbol) + '"' + (entry.leadKey ? ' data-key="' + esc(entry.leadKey) + '"' : '') + ' data-dir="' + side + '" data-tier="' + entry.tier + '" data-fresh="' + esc(entry.freshness || "stale") + '"'
    + ' aria-pressed="' + selected + '" aria-label="' + esc(entry.symbol + (entry.name ? ' ' + entry.name : '') + ' · ' + (entry.conflict ? 'strategy conflict' : entry.direction || 'no direction') + ' · ' + (basis === "scan" ? 'live scan ' : basis ? 'recorded ' : '') + (life || 'no setup') + (entry.core ? ' · core market' : '')) + '">'
    + '<span class="gd-pw-top">' + (rank != null ? '<span class="gd-pw-rank" aria-hidden="true">' + rank + '</span>' : '')
    + '<b class="gd-pw-symbol">' + esc(entry.symbol) + '</b>' + (entry.name ? '<small class="gd-pw-name">' + esc(entry.name) + '</small>' : '')
    + (age ? '<small class="gd-pw-age" title="' + esc('Latest meaningful event ' + (age === "now" ? 'just now' : age + ' ago') + ' (lifecycle change, confirmation, close, or a strategy scan change seen while open). Attention only; the lifecycle is unchanged.') + '">'
      + (entry.freshness === "very-fresh" ? '<i class="gd-fresh-dot" aria-hidden="true"></i>' : '') + esc(age) + '</small>' : '')
    + '<span class="gd-pw-price">' + (entry.price == null ? '<span class="gd-na">—</span>' : esc(formatPrice(entry.price)))
    + (entry.change == null ? '' : '<small class="gd-' + (entry.change >= 0 ? 'up' : 'down') + '">' + esc(signedPct(entry.change)) + '</small>') + '</span></span>'
    + '<span class="gd-pw-meta">' + (entry.conflict
      ? '<span class="gd-bias gd-conflict" data-dir="conflict" title="Live strategies disagree on direction. Each strategy\'s direction is shown below.">Conflict</span>'
      : '<span class="gd-bias" data-dir="' + side + '">' + esc(entry.direction || "No direction") + '</span>')
    + '<span class="gd-life" data-life="' + esc(lifeKey(life)) + '"' + (basis ? ' data-basis="' + basis + '" title="' + esc(basisHelp) + '"' : '') + '>'
    + (basis ? '<small class="gd-basis">' + (basis === "scan" ? "Live scan" : "Recorded") + ' ·</small> ' : '')
    + (entry.stage ? GARDEN_STAGES[entry.stage].icon + ' ' : '') + esc(life || "No setup") + '</span>'
    + (entry.core ? '<span class="gd-core-badge" title="Core market: always kept in view. Not a better trade.">⭐ Core</span>' : '')
    + '<span class="gd-pw-score" title="The engine\'s setup score">' + (entry.score == null ? '—' : esc(Math.round(entry.score))) + '</span></span>'
    + (signals.length ? '<span class="gd-watch-signals">'
      + signals.map(signal => '<span class="gd-signal" data-strategy="' + esc(signal.strategy) + '" data-dir="' + dirKey(signal.direction) + '" title="' + esc(signal.tag + (signal.state ? ' · ' + signal.state : '')) + '">'
        + '<i class="gd-glyph" aria-hidden="true"></i>' + esc(signal.tag) + ' ' + (signal.direction ? '<b>' + (signal.direction === "LONG" ? "▲ BUY" : "▼ SELL") + '</b>' : '<em>—</em>') + '</span>').join("") + '</span>' : '')
    + '</button>';
}

/** The small panel: three priority slots and one core slot (see priorityWatchSlots). */
export function priorityWatch(slots, {selectedSymbol = null, entering = new Set()} = {}) {
  if (!slots.priority.length && !slots.core) return emptyArea("No market data", "The engine has not returned any instruments.");
  const row = (entry, rank) => priorityWatchRow(entry, {rank, selected: entry.symbol === selectedSymbol, entering: entering.has(entry.symbol)});
  return '<div class="gd-pw-group"><span class="gd-pw-label">🔥 Priority</span>' + slots.priority.map((entry, index) => row(entry, index + 1)).join("") + '</div>'
    + (slots.core ? '<div class="gd-pw-group is-core"><span class="gd-pw-label">⭐ Core</span>' + row(slots.core, null) + '</div>' : '');
}

/** The full Market Watch (opened with "View all"): every scanned market, grouped. */
export function marketWatchAll(groups, {total = 0, selectedSymbol = null} = {}) {
  const section = (title, note, entries) => !entries.length ? '' : '<section class="gd-wa-group"><h3>' + title + ' <span>' + entries.length + '</span></h3>'
    + (note ? '<p class="gd-note">' + note + '</p>' : '') + '<div class="gd-wa-list">'
    + entries.map(entry => priorityWatchRow(entry, {selected: entry.symbol === selectedSymbol, full: true})).join("") + '</div></section>';
  return '<header class="gd-rs-head gd-wa-head"><div class="gd-rs-title"><span class="gd-eyebrow">Market watch</span>'
    + '<h2 id="gardenWatchAllTitle">All ' + total + ' scanned markets</h2><p class="gd-note">' + esc(PRIORITY_NOTE) + '</p></div>'
    + '<button type="button" class="gd-rs-close" data-watch-action="close" aria-label="Close market watch">×</button></header>'
    + '<div class="gd-rs-body gd-wa-body">'
    + (total ? '<p class="gd-note gd-wa-legend"><b>Recorded</b> states come from a setup\'s recorded lifecycle (as in the Garden). <b>Live scan</b> states are a strategy\'s current evaluation with no recorded episode yet, so the Garden may not show them.</p>'
      + section("🔥 Top priority", "The three highest-ranked markets, as in the priority watch.", groups.priority)
      + section("⭐ Core markets", "Core markets not in the top three. Always kept in view; core is not a signal.", groups.core)
      + section("👁 Other markets", "", groups.other)
      + section("🍂 Recently closed", "The latest setup was invalidated or expired.", groups.closed)
      : emptyArea("No market data", "The engine has not returned any instruments."))
    + '</div>';
}
export const PRIORITY_WATCH_NOTE = PRIORITY_NOTE;

// ----- compact setup cards (Developing / Confirmed) ------------------------------------
/**
 * Medium-height setup card: the summary only. Clicking it opens Market Research.
 * `variant` "confirmed" adds the stop, confirmation time and session.
 */
export function compactCard(card, {selected = false, variant = "developing"} = {}) {
  const confirmed = variant === "confirmed";
  const cell = (label, value, cls = "") => '<div class="' + cls + '"><dt>' + label + '</dt><dd>' + (value == null ? '<span class="gd-na">—</span>' : esc(value)) + '</dd></div>';
  const levels = card.levels.planned
    ? '<dl class="gd-mini-levels' + (confirmed ? ' is-four' : '') + '">' + cell("Entry", card.levels.entry) + (confirmed ? cell("Stop", card.levels.stop, "is-stop") : '')
      + cell("Target", card.levels.target, "is-target") + cell("R:R", card.levels.rr) + '</dl>'
    : '<p class="gd-mini-pending">Levels appear once a stop and target are calculated.</p>';
  const meta = confirmed
    ? [card.confirmationTime ? 'Confirmed ' + card.confirmationTime : null, card.session ? card.session + ' session' : null]
    : [card.session ? card.session + ' session' : null, card.duration ? 'Observed ' + card.duration : null];
  return '<article class="gd-mini gd-mini-' + variant + (selected ? ' is-selected' : '') + (card.tracked ? ' is-tracked' : '') + '" data-key="' + esc(card.key || "") + '" data-setup-id="' + esc(card.id || "")
    + '" data-strategy="' + esc(card.strategy?.id || "") + '" data-dir="' + dirKey(card.direction) + '" data-stage="' + card.stage + '" tabindex="0" role="button"'
    + ' aria-label="' + esc(card.symbol + ' · ' + (card.direction || 'no direction') + ' · open market research') + '">'
    + '<header class="gd-mini-head"><i class="gd-swatch gd-swatch-' + card.stage + ' gd-swatch-' + String(card.direction || "none").toLowerCase() + '" aria-hidden="true"></i>'
    + '<div class="gd-mini-title"><h3>' + esc(card.symbol) + '</h3>' + directionBadge(card) + '</div>'
    + '<div class="gd-mini-score" aria-label="Setup score">' + scoreRing(card.score, 40) + '<b>' + (card.score == null ? '—' : card.score) + '</b></div></header>'
    + '<div class="gd-mini-sub">' + strategyChip(card.strategy, card.strategyVersion) + '<span>' + orUnavailable(card.setupType, "Setup type unavailable")
    + (card.timeframe ? ' · ' + esc(card.timeframe) : '') + '</span>' + (card.tracked ? '<span class="gd-tracked-flag">Tracking</span>' : '') + '</div>'
    + levels
    + '<footer class="gd-mini-foot"><span class="gd-life" data-life="' + esc(lifeKey(card.status)) + '">' + card.stageIcon + ' ' + orUnavailable(card.status, "—") + '</span>'
    + '<span class="gd-mini-meta">' + esc(meta.filter(Boolean).join(" · ")) + '</span><span class="gd-mini-cta" aria-hidden="true">Research →</span></footer>'
    + '</article>';
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

/**
 * What happened to earlier confirmed setups of the same strategy that shared each
 * of this setup's recorded conditions (backend /similar). Each condition is its own
 * bubble; nothing is combined into a score. No rate below the verified minimum.
 */
export function evidenceBubbles(similar, {state = "idle"} = {}) {
  if (!similar) {
    return '<p class="gd-na">' + (state === "loading" ? "Loading historical evidence…" : state === "error" ? "Historical evidence unavailable." : "Select a recorded setup to see its history.") + '</p>';
  }
  const totals = similar.strategy_totals || {};
  const insufficient = totals.status !== "SUFFICIENT";
  const bubble = row => {
    const n = Number(row.confirmed) || 0, decisive = Number(row.verified_decisive) || 0;
    const size = Math.round(34 + Math.min(34, Math.sqrt(n) * 6));
    const sufficient = row.status === "SUFFICIENT" && row.target_share != null;
    return '<li class="gd-bubble' + (sufficient ? ' is-sufficient' : ' is-insufficient') + (n ? '' : ' is-empty') + '" style="--b:' + size + 'px">'
      + '<span class="gd-bubble-orb" aria-hidden="true"' + (sufficient ? ' style="--share:' + (Number(row.target_share) * 100).toFixed(1) + '%"' : '') + '><b>' + n + '</b></span>'
      + '<span class="gd-bubble-text"><small>' + esc(row.label) + '</small><strong>' + esc(row.value) + '</strong>'
      + '<em>' + (sufficient ? esc(Math.round(Number(row.target_share) * 100)) + '% target first of ' + decisive + ' verified'
        : decisive + ' verified · ' + (Number(row.verified_target) || 0) + ' target · ' + (Number(row.verified_stop) || 0) + ' stop') + '</em></span></li>';
  };
  return (insufficient ? '<p class="gd-insufficient">INSUFFICIENT VERIFIED DATA</p>' : '')
    + '<p class="gd-note">' + esc(Number(totals.confirmed) || 0) + ' earlier confirmed ' + esc(strategyTag(similar.strategy_id).label) + ' setups · '
    + esc(Number(totals.verified_decisive) || 0) + ' with a verified target/stop outcome (a rate needs ' + esc(similar.min_verified) + ').'
    + ' Pending ' + esc(Number(totals.pending) || 0) + ' · unverified ' + esc(Number(totals.unverified) || 0) + ' · quarantined ' + esc(Number(totals.quarantined) || 0) + '.</p>'
    + '<ul class="gd-bubbles">' + (similar.conditions || []).map(bubble).join("") + '</ul>'
    + '<p class="gd-note">Bubble size: earlier confirmed setups sharing that condition. Only verified outcomes count as evidence; history describes, it does not predict.</p>';
}

/** Strategy Lab: verified outcomes by recorded condition, one strategy at a time (backend /evaluation). */
export function evaluationPanel(report, {selected = null} = {}) {
  if (!report) return '<p class="gd-na">Historical evaluation unavailable (engine offline).</p>';
  const strategies = report.strategies || [];
  const current = strategies.find(item => item.strategy_id === selected) || strategies[0];
  if (!current) return '<p class="gd-na">No strategies registered.</p>';
  const tag = strategyTag(current.strategy_id);
  const totals = current.totals || {};
  const cluster = ([name, table]) => '<div class="gd-cluster"><h5>' + esc(table.label) + '</h5><ul class="gd-bubbles is-cluster">'
    + Object.entries(table.values || {}).map(([value, row]) => {
      const n = Number(row.confirmed) || 0;
      const sufficient = row.status === "SUFFICIENT" && row.target_share != null;
      return '<li class="gd-bubble' + (sufficient ? ' is-sufficient' : ' is-insufficient') + '" style="--b:' + Math.round(26 + Math.min(30, Math.sqrt(n) * 4)) + 'px" title="'
        + esc(value + ': ' + n + ' confirmed, ' + (row.verified_decisive || 0) + ' verified target/stop' + (sufficient ? ', ' + Math.round(row.target_share * 100) + '% target first' : ' — insufficient verified data')) + '">'
        + '<span class="gd-bubble-orb" aria-hidden="true"' + (sufficient ? ' style="--share:' + (row.target_share * 100).toFixed(1) + '%"' : '') + '><b>' + n + '</b></span>'
        + '<span class="gd-bubble-text"><strong>' + esc(value) + '</strong><em>' + (row.verified_decisive || 0) + ' verified</em></span></li>';
    }).join("") + '</ul></div>';
  return '<div class="gd-eval"><div class="gd-lab-tabs" role="group" aria-label="Evaluation strategy">' + strategies.map(item =>
      '<button type="button" data-eval-strategy="' + esc(item.strategy_id) + '" aria-pressed="' + (item === current) + '">' + esc(strategyTag(item.strategy_id).tag) + '</button>').join("") + '</div>'
    + '<p class="gd-eval-head"><b>' + esc(tag.label) + '</b> · ' + (Number(totals.confirmed) || 0) + ' confirmed · ' + (Number(totals.verified_target) || 0) + ' verified target · '
    + (Number(totals.verified_stop) || 0) + ' verified stop · ' + (Number(totals.verified_other) || 0) + ' verified other · ' + (Number(totals.pending) || 0) + ' pending · '
    + (Number(totals.unverified) || 0) + ' unverified · ' + (Number(totals.quarantined) || 0) + ' quarantined</p>'
    + (totals.status !== "SUFFICIENT" ? '<p class="gd-insufficient">INSUFFICIENT VERIFIED DATA</p>' : '')
    + '<div class="gd-clusters">' + Object.entries(current.conditions || {}).map(cluster).join("") + '</div>'
    + '<p class="gd-note">' + esc(report.rules || "") + '</p></div>';
}

function stopSection(stop) {
  if (!stop) return "";
  const rows = [["Structural invalidation", stop.structural_invalidation, stop.structure_source], ["Buffer", stop.buffer, stop.buffer_rule],
    ["Final stop", stop.stop, null], ["Stop distance", stop.stop_distance, stop.stop_distance_atr_h1 != null ? stop.stop_distance_atr_h1 + ' ATR(H1)' : null],
    ["Permitted", stop.min_stop_distance != null ? formatNumber(stop.min_stop_distance) + ' – ' + formatNumber(stop.max_stop_distance) : null, "stop distance range"]];
  return '<section class="gd-stop"><h4>Stop evidence</h4><dl class="gd-stop-list">' + rows.map(([label, value, note]) => '<div><dt>' + label + '</dt><dd>'
    + (value == null ? '<span class="gd-na">Not recorded</span>' : esc(typeof value === "number" ? formatNumber(value) : value)) + (note ? '<small>' + esc(note) + '</small>' : '') + '</dd></div>').join("")
    + '</dl>' + (stop.rejection_reason ? '<p class="gd-stop-reject">' + esc(stop.rejection_reason) + '</p>' : '') + '</section>';
}
const formatNumber = value => {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toLocaleString("en-US", {maximumFractionDigits: Math.abs(number) >= 100 ? 2 : Math.abs(number) >= 1 ? 4 : 6});
};

export function analystPanel(model, {loading = false, simulated = false, similar = null, similarState = "idle"} = {}) {
  if (!model) {
    return '<div class="gd-analyst-empty"><span class="gd-area-node gd-area-node-analyst" aria-hidden="true"></span><b>Select a setup</b><p>Choose any card or orb to see how TRADeden reads it.</p></div>';
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
  return '<div class="gd-analyst-head"><div><span class="gd-eyebrow">TRADeden Analyst' + (history ? ' · record' : '') + '</span><h3>' + esc(model.symbol) + ' <small>' + stage.icon + ' ' + esc(stage.label)
    + (model.direction ? ' · ' + esc(model.direction) : '') + '</small></h3>'
    + (model.strategy ? '<div class="gd-analyst-strategy">' + strategyChip(model.strategy, model.strategyVersion) + '<span>' + esc(model.strategy.label) + '</span>'
      + (model.strategyVersion ? '<small class="gd-version">' + esc(model.strategyVersion) + '</small>' : '') + '</div>' : '')
    + '</div></div>' + lifecycleRailHtml(model.rail)
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
      + '</div>' + riskBar(model.risk)
      + (levels.basis === "confirmation" ? '<p class="gd-note">The plan recorded at confirmation. Later observations re-evaluate at the live price and never change it.</p>' : '')
      + (levels.planned ? '' : '<p class="gd-note">Levels appear only once the engine calculates both a stop and a target.</p>') + '</section>')
    + stopSection(model.stop)
    + (model.setupId && !simulated ? '<section class="gd-history-evidence"><h4>What happened to similar setups</h4>' + evidenceBubbles(similar, {state: similarState}) + '</section>' : '')
    + '<p class="gd-analyst-method">Rule-based analysis' + (model.analystVersion ? ' (' + esc(model.analystVersion) + ')' : '')
    + ' — it restates recorded scanner evidence. It is not an AI or machine-learning prediction and does not forecast outcomes.</p>'
    + '<p class="gd-disclaimer-strong">' + esc(NOT_ADVICE) + '</p>';
}

export function stageLegend() {
  return Object.values(GARDEN_STAGES).map(stage => '<span class="gd-legend-item gd-legend-' + stage.key + '"><i class="gd-legend-dot" aria-hidden="true"></i>' + esc(stage.label) + '</span>').join("")
    + '<span class="gd-legend-item gd-legend-dir"><i class="gd-legend-dot gd-dot-long" aria-hidden="true"></i>Long <i class="gd-legend-dot gd-dot-short" aria-hidden="true"></i>Short</span>'
    + '<span class="gd-legend-item gd-legend-dir"><i class="gd-legend-dot gd-dot-target" aria-hidden="true"></i>Target <i class="gd-legend-dot gd-dot-stop" aria-hidden="true"></i>Stop <i class="gd-legend-dot gd-dot-invalidated" aria-hidden="true"></i>Invalidated</span>';
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

/** Selected-market overlay inside the garden world: shown only while something is selected. */
export function focusPanel(card) {
  if (!card) return "";
  const levels = card.levels?.planned
    ? '<dl class="gd-focus-levels"><div><dt>Entry</dt><dd>' + esc(card.levels.entry) + '</dd></div><div><dt>Stop</dt><dd class="is-stop">' + esc(card.levels.stop)
      + '</dd></div><div><dt>Target</dt><dd class="is-target">' + esc(card.levels.target) + '</dd></div><div><dt>R:R</dt><dd>' + (card.levels.rr ? esc(card.levels.rr) : '—') + '</dd></div></dl>'
    : '<p class="gd-focus-meta">Entry, stop and target not calculated yet.</p>';
  const meta = [card.status ? 'Lifecycle ' + card.status : null, card.session ? card.session + ' session' : 'Session unavailable',
    card.confirmationTime ? 'confirmed ' + card.confirmationTime : null].filter(Boolean);
  return '<div class="gd-focus-head" data-dir="' + dirKey(card.direction) + '"><i class="gd-swatch gd-swatch-' + card.stage + ' gd-swatch-' + String(card.direction || "none").toLowerCase() + '" aria-hidden="true"></i>'
    + '<div><b>' + esc(card.symbol) + '</b><span>' + card.stageIcon + ' ' + esc(card.headline) + '</span></div>'
    + (card.score == null ? '' : '<strong>' + card.score + '<small>/100</small></strong>')
    + '<button type="button" class="gd-focus-close" data-focus-action="close" aria-label="Clear selection" title="Clear selection">×</button></div>'
    + '<div class="gd-focus-sub">' + strategyChip(card.strategy, card.strategyVersion) + directionBadge(card)
    + '<span>' + orUnavailable(card.setupType, "Setup type unavailable") + (card.timeframe ? ' · ' + esc(card.timeframe) : '') + '</span></div>'
    + (card.simulated ? '<p class="gd-analyst-sim">Simulated fixture — not market data.</p>' : '')
    + levels
    + '<p class="gd-focus-meta">' + esc(meta.join(" · ")) + '</p>'
    + '<div class="gd-focus-actions"><button type="button" class="is-primary" data-focus-action="research">View market research</button>'
    + (card.id ? '<button type="button" data-focus-action="view-setup">Locate card</button>' : '') + '</div>';
}

// ----- Market Research: the microscope -------------------------------------------------
function researchFacts(section) {
  const scan = section.scan || [];
  if (!section.facts.length && !scan.length && !section.evidence.length) return '<p class="gd-na">Not available for this setup.</p>';
  const facts = rows => '<dl class="gd-rs-facts">' + rows.map(fact => '<div><dt>' + esc(fact.label) + '</dt><dd>' + esc(fact.value) + '</dd></div>').join("") + '</dl>';
  return (section.facts.length ? facts(section.facts) : '')
    + (scan.length ? '<h5 class="gd-rs-scan" title="Not recorded by this setup: the latest scanner pass on the same market.">Latest market scan</h5>' + facts(scan) : '')
    + (section.evidence.length ? '<ul class="gd-rs-claims">' + section.evidence.map(item => '<li class="is-' + item.tone + '">' + esc(item.claim) + '</li>').join("") + '</ul>' : '');
}
function claimList(items, emptyText, tone) {
  return items.length ? '<ul class="gd-rs-claims">' + items.map(item => '<li class="is-' + tone + '">' + esc(item.claim) + '</li>').join("") + '</ul>'
    : '<p class="gd-na">' + esc(emptyText) + '</p>';
}

/**
 * The research drawer for one setup or market (researchModel). Every line is a
 * recorded scanner field, a recorded analyst claim, or an explicit "Not available".
 */
export function researchPanel(model, {loading = false, similar = null, similarState = "idle", tracked = false} = {}) {
  if (!model) return '<div class="gd-analyst-empty"><b>Nothing selected</b><p>Choose a market, card or node to open its research.</p></div>';
  const {card, analyst, sections} = model;
  const history = analyst.context === "history";
  const levels = card.levels;
  const outcome = analyst.outcome;
  const kind = history ? "Closed setup record" : !model.hasSetup ? "Live market scan" : analyst.context === "confirmed" ? "Confirmed setup" : "Developing setup";
  const section = (title, body, cls = "") => '<section class="gd-rs-section ' + cls + '"><h4>' + title + '</h4>' + body + '</section>';
  const plan = levels.planned
    ? '<dl class="gd-rs-plan"><div><dt>Entry</dt><dd>' + esc(levels.entry ?? "—") + '</dd></div><div class="is-stop"><dt>Stop</dt><dd>' + esc(levels.stop) + '</dd></div>'
      + '<div class="is-target"><dt>Target</dt><dd>' + esc(levels.target) + '</dd></div><div><dt>R:R</dt><dd>' + (levels.rr ? esc(levels.rr) : '—') + '</dd></div></dl>' + riskBar(analyst.risk)
      + (levels.basis === "confirmation" ? '<p class="gd-note">The plan recorded at confirmation. Later observations never change it.</p>' : '')
    : '<p class="gd-na">Not available: the engine has not calculated both a stop and a target.</p>';
  const trackable = Boolean(card.id) && !card.simulated && !history;
  return '<header class="gd-rs-head" data-dir="' + dirKey(card.direction) + '" data-stage="' + card.stage + '">'
    + '<div class="gd-rs-title"><span class="gd-eyebrow">Market research · ' + esc(kind) + '</span>'
    + '<h2 id="gardenResearchTitle">' + esc(card.symbol) + ' ' + directionBadge(card) + '</h2>'
    + '<div class="gd-rs-sub">' + strategyChip(card.strategy, card.strategyVersion) + (card.strategy ? '<span>' + esc(card.strategy.label) + '</span>' : '')
    + (card.strategyVersion ? '<small class="gd-version">' + esc(card.strategyVersion) + '</small>' : '') + '<span>' + orUnavailable(card.setupType, "Setup type unavailable") + (card.timeframe ? ' · ' + esc(card.timeframe) : '') + '</span></div></div>'
    + '<div class="gd-rs-score" aria-label="Setup score">' + scoreRing(card.score, 54) + '<b>' + (card.score == null ? '—' : card.score) + '</b></div>'
    + '<button type="button" class="gd-rs-close" data-research-action="close" aria-label="Close market research">×</button></header>'
    + '<div class="gd-rs-body">'
    + lifecycleRailHtml(card.rail)
    + '<p class="gd-rs-status"><span class="gd-life" data-life="' + esc(lifeKey(card.status)) + '">' + card.stageIcon + ' ' + orUnavailable(card.status, "—") + '</span>'
    + '<span>' + (card.session ? esc(card.session) + ' session' : '<span class="gd-na">Session unavailable</span>') + '</span>'
    + (card.confirmationTime ? '<span>Confirmed ' + esc(card.confirmationTime) + '</span>' : '') + (card.closedTime ? '<span>Closed ' + esc(card.closedTime) + '</span>' : '')
    + (card.duration && !history ? '<span>Observed ' + esc(card.duration) + '</span>' : '') + '</p>'
    + (card.simulated ? '<p class="gd-analyst-sim">Simulated fixture — not market data.</p>' : '')
    + (history ? '<p class="gd-analyst-record">This setup has closed. What follows is the recorded analysis, not a live read of the market.</p>' : '')
    + '<p class="gd-note gd-rs-basis">' + (model.basis === "recorded" ? 'Facts recorded by the strategy on the setup\'s latest observation.' : 'Facts from the latest scanner pass.') + '</p>'
    + '<div class="gd-rs-grid">'
    + section("Market structure", researchFacts(sections.structure))
    + section("Trend", researchFacts(sections.trend))
    + section("Momentum", researchFacts(sections.momentum))
    + section("Support &amp; resistance", researchFacts(sections.levels))
    + '</div>'
    + section("Strategy evidence", loading ? '<p class="gd-na">Loading recorded evidence…</p>'
      : !model.hasSetup ? '<p class="gd-na">Not available: this market has no recorded setup to evaluate.</p>'
      : '<div class="gd-rs-evidence"><div><h5>Supporting</h5>' + claimList(model.evidence.supporting, model.analysisLoaded ? "None recorded." : "Not available.", "support") + '</div>'
        + '<div><h5>Opposing</h5>' + claimList(model.evidence.opposing, model.analysisLoaded ? "None recorded." : "Not available.", "oppose") + '</div></div>'
        + (model.evidence.missing.length ? '<h5>Still missing</h5>' + claimList(model.evidence.missing, "", "missing") : '')
        + (model.rules?.length ? '<h5>' + esc(card.strategy?.label || "Strategy") + ' rules · latest observation</h5>'
          + (analyst.context === "confirmed" ? '<p class="gd-note">Re-evaluated at the live price after confirmation. The confirmation itself is a historical event and does not change.</p>' : '')
          + '<ul class="gd-rs-rules">'
          + model.rules.map(rule => '<li class="' + (rule.passed ? 'is-support' : 'is-missing') + '">' + esc(rule.rule) + '</li>').join("") + '</ul>' : ''), "gd-rs-wide")
    + section(history ? "Planned risk / reward" : "Current plan", plan + stopSection(analyst.stop), "gd-rs-wide")
    + section("Why TRADeden sees it", '<p>' + (analyst.happening ? esc(analyst.happening) : '<span class="gd-na">No summary recorded.</span>') + '</p>'
      + (analyst.matters && analyst.matters !== analyst.happening ? '<h5>' + esc(analyst.titles.matters) + '</h5><p>' + esc(analyst.matters) + '</p>' : '')
      + (analyst.watchingFor ? '<h5>Watching for</h5><p>' + esc(analyst.watchingFor) + '</p>' : ''), "gd-rs-wide")
    + section(history ? "What invalidated it" : "What could invalidate it", list(analyst.invalidates, analyst.invalidatesEmpty), "gd-rs-wide")
    + section("Historical context", (outcome ? '<p class="gd-outcome-line gd-outcome-' + esc(outcome.kind) + '"><b>' + outcome.icon + ' ' + esc(outcome.label) + '</b>'
        + (outcome.horizon ? ' within ' + esc(outcome.horizon) : '') + (outcome.rText ? ' · ' + esc(outcome.rText) : '') + '</p>' : '')
      + (model.hasSetup && !card.simulated ? evidenceBubbles(similar, {state: similarState}) : '<p class="gd-na">Not available: no recorded setup history for this view.</p>'), "gd-rs-wide gd-history-evidence")
    + '<footer class="gd-rs-foot">' + (trackable ? '<button type="button" data-research-action="track" aria-pressed="' + tracked + '">' + (tracked ? 'Tracking ✓' : 'Track setup') + '</button>' : '')
    + '<p class="gd-analyst-method">Rule-based analysis' + (analyst.analystVersion ? ' (' + esc(analyst.analystVersion) + ')' : '')
    + ' — it restates recorded scanner evidence. It is not an AI or machine-learning prediction and does not forecast outcomes.</p>'
    + '<p class="gd-disclaimer-strong">' + esc(NOT_ADVICE) + '</p></footer>'
    + '</div>';
}
