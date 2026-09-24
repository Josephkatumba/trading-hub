// TRADeden Garden markup. Pure string renderers (no DOM access) over the view
// models in gardenModel.mjs. Unavailable values are always shown explicitly.
import {GARDEN_STAGES} from "./gardenModel.mjs";

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
  facts.push(["Session", card.session], ["Status", card.status]);
  if (card.bucket !== "history") facts.push(["Observed for", card.duration]);
  const factRows = facts.map(([label, value]) => '<div><span>' + label + '</span><b>' + orUnavailable(value) + '</b></div>').join("");
  const evidence = !expanded ? "" : '<div class="gd-evidence" id="evidence-' + id + '">'
    + (evidenceHtml || '<p class="gd-na">' + (evidenceState === "loading" ? "Loading recorded evidence…" : "No recorded analyst evidence for this setup.") + '</p>') + '</div>';
  return '<article class="gd-card gd-tone-' + card.tone + ' gd-stage-' + card.stage + (selected ? ' is-selected' : '') + (card.tracked ? ' is-tracked' : '')
    + '" data-key="' + esc(card.key || "") + '" data-setup-id="' + id + '" tabindex="0" aria-selected="' + selected + '">'
    + '<header class="gd-card-head"><div class="gd-card-title"><h3>' + esc(card.symbol) + '</h3>'
    + '<span class="gd-stage-chip"><span aria-hidden="true">' + card.stageIcon + '</span> ' + esc(card.headline) + '</span></div>'
    + '<div class="gd-score" aria-label="Setup score">' + (card.score == null ? '<b class="gd-na">—</b>' : '<b>' + card.score + '</b>') + '<span>/ 100</span></div></header>'
    + '<div class="gd-card-sub">' + directionBadge(card) + '<span>' + orUnavailable(card.setupType, "Setup type unavailable") + (card.timeframe ? ' · ' + esc(card.timeframe) : '') + '</span>'
    + (card.tracked ? '<span class="gd-tracked-flag">Tracking</span>' : '') + '</div>'
    + '<div class="gd-levels">' + level("Entry", card.levels.entry) + level("Stop", card.levels.stop, "gd-level-stop")
    + level("Target", card.levels.target, "gd-level-target") + level("R:R", card.levels.rr) + '</div>'
    + '<div class="gd-why"><span>Why TRADeden sees it</span><p>' + (card.why ? esc(card.why) : '<span class="gd-na">No explanation was recorded for this observation.</span>') + '</p></div>'
    + '<div class="gd-facts">' + factRows + '</div>'
    + evidence
    + '<footer class="gd-card-foot"><div class="gd-actions">'
    + '<button type="button" data-action="view-setup">View setup</button>'
    + '<button type="button" data-action="view-evidence" aria-expanded="' + expanded + '"' + (card.id ? '' : ' disabled') + '>' + (expanded ? 'Hide evidence' : 'View evidence') + '</button>'
    + '<button type="button" data-action="view-analysis">View analysis</button>'
    + (trackable ? '<button type="button" data-action="track" aria-pressed="' + card.tracked + '">' + (card.tracked ? 'Tracking ✓' : 'Track setup') + '</button>' : '')
    + '</div><small class="gd-disclaimer">Not an entry recommendation.</small>' + extraFoot + '</footer>'
    + '</article>';
}

export function emptyArea(title, text) {
  return '<div class="gd-empty"><b>' + esc(title) + '</b><p>' + esc(text) + '</p></div>';
}

export function marketOverview(rows) {
  if (!rows.length) return emptyArea("No market data", "The engine has not returned any instruments.");
  return '<div class="gd-market-head" aria-hidden="true"><span>Market</span><span>Price</span><span>Bias · state</span><span>Setup</span></div>'
    + rows.map(row => '<button type="button" class="gd-market-row" data-symbol="' + esc(row.symbol) + '">'
      + '<b>' + esc(row.symbol) + '</b>'
      + '<span class="gd-market-price">' + orUnavailable(row.price) + '<small class="gd-' + row.changeTone + '">' + (row.change ? esc(row.change) : '') + '</small></span>'
      + '<span class="gd-market-bias"><span class="gd-market-dir gd-dir-text-' + esc(String(row.direction || "none").toLowerCase()) + '">' + orUnavailable(row.direction, "—") + '</span>'
      + '<small class="gd-market-state">' + orUnavailable(row.state, "—") + '</small></span>'
      + '<span class="gd-market-setup">' + (row.stage ? GARDEN_STAGES[row.stage].icon + ' ' : '') + esc(row.setupStatus) + '</span>'
      + '</button>').join("");
}

function list(items, emptyText) {
  return items.length ? '<ul>' + items.map(item => '<li>' + esc(item) + '</li>').join("") + '</ul>' : '<p class="gd-na">' + esc(emptyText) + '</p>';
}

export function analystPanel(model, {loading = false, simulated = false} = {}) {
  if (!model) {
    return '<div class="gd-analyst-empty"><span aria-hidden="true">🧠</span><b>Select a setup</b><p>Choose any card or plant to see how TRADeden reads it.</p></div>';
  }
  const stage = GARDEN_STAGES[model.stage];
  const levels = model.levels;
  const rr = [["Entry", levels.entry], ["Stop", levels.stop], ["Target", levels.target], ["Reward : risk", levels.rr]];
  return '<div class="gd-analyst-head"><div><span class="gd-eyebrow">🧠 TRADeden Analyst</span><h3>' + esc(model.symbol) + ' <small>' + stage.icon + ' ' + esc(stage.label)
    + (model.direction ? ' · ' + esc(model.direction) : '') + '</small></h3></div></div>'
    + (simulated ? '<p class="gd-analyst-sim">Simulated fixture — not market data.</p>' : '')
    + '<section><h4>What is happening</h4><p>' + (model.happening ? esc(model.happening) : '<span class="gd-na">No summary recorded.</span>') + '</p></section>'
    + '<section><h4>Why it matters</h4><p>' + (model.matters ? esc(model.matters) : '<span class="gd-na">No scanner reasoning recorded.</span>') + '</p></section>'
    + '<section><h4>What confirms it</h4>' + (loading ? '<p class="gd-na">Loading recorded evidence…</p>' : list(model.confirms, model.analysisLoaded ? "No confirming evidence recorded yet." : "Evidence unavailable for this item."))
    + (model.stillNeeded.length ? '<h5>Still missing</h5>' + list(model.stillNeeded, "") : '')
    + (model.watchingFor ? '<h5>Watching for</h5><p>' + esc(model.watchingFor) + '</p>' : '') + '</section>'
    + '<section><h4>What invalidates it</h4>' + list(model.invalidates, "No invalidation level has been calculated yet.") + '</section>'
    + '<section><h4>Risk / reward structure</h4><div class="gd-analyst-levels">'
    + rr.map(([label, value]) => '<div><span>' + label + '</span><b>' + (value == null ? '<span class="gd-na">Not yet calculated</span>' : esc(value)) + '</b></div>').join("")
    + '</div>' + (levels.planned ? '' : '<p class="gd-note">Levels appear only once the engine calculates both a stop and a target.</p>') + '</section>'
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
    + '<span class="gd-arch-symbol"><b>' + esc(entry.symbol) + '</b><small>' + (entry.direction ? esc(entry.direction) : 'No direction') + (entry.confirmed ? ' · confirmed' : ' · not confirmed') + '</small></span>'
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
