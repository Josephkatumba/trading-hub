// TRADeden Garden view model. Pure functions only (no DOM), so they are unit-tested.
//
// The garden is a visual reading of the backend's lifecycle states. The backend
// lifecycle (DETECTED/DEVELOPING/CONFIRMING/CONFIRMED/ACTIVE/INVALIDATED/EXPIRED/
// RESOLVED) stays authoritative; nothing here changes or infers it. Every number
// shown comes from API data; anything missing becomes an explicit unavailable
// state rather than a guess.
import {currentWatchSetups, partitionSetupEpisodes} from "../radarLayout.mjs";
import {liveGardenRows, setupFamilyLabel, strategyBreakdown, strategyConflict, strategyIdOf, strategyMatrix, strategyTag} from "../strategyModel.mjs";

export const GARDEN_STAGES = Object.freeze({
  growing: {key: "growing", icon: "🌱", label: "Growing", description: "Setup is developing."},
  shaping: {key: "shaping", icon: "🌿", label: "Taking Shape", description: "Setup is approaching confirmation."},
  bloomed: {key: "bloomed", icon: "🌸", label: "Bloomed", description: "Setup has been confirmed."},
  active: {key: "active", icon: "🌳", label: "Active", description: "Setup is being tracked."},
  history: {key: "history", icon: "🍂", label: "History", description: "Setup has closed."},
});
export const STAGE_ORDER = ["bloomed", "active", "shaping", "growing", "history"];
const TERMINAL = new Set(["INVALIDATED", "EXPIRED", "RESOLVED"]);

const upper = value => String(value ?? "").trim().toUpperCase();
const finite = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));

/** Garden stage for a lifecycle state (episodes) or, when absent, a scanner state (markets). */
export function gardenStage(row) {
  const lifecycle = upper(row?.lifecycle_state);
  if (TERMINAL.has(lifecycle)) return "history";
  if (lifecycle === "ACTIVE") return "active";
  if (lifecycle === "CONFIRMED") return "bloomed";
  if (lifecycle === "CONFIRMING") return "shaping";
  if (lifecycle === "DETECTED" || lifecycle === "DEVELOPING") return "growing";
  const scanner = upper(row?.state);
  if (scanner === "CONFIRMING") return row?.strategy_valid === true ? "bloomed" : "shaping";
  return "growing";
}

export function direction(row) {
  const value = upper(row?.direction);
  return value === "LONG" || value === "SHORT" ? value : null;
}

/** Visual tone: confirmed long/short get green/red, closed is grey, everything else neutral. */
export function cardTone(stage, dir) {
  if (stage === "history") return "history";
  if (stage === "bloomed" || stage === "active") return dir === "LONG" ? "long" : dir === "SHORT" ? "short" : "confirmed";
  return "developing";
}

export function formatPrice(value) {
  if (!finite(value)) return null;
  const number = Number(value);
  const digits = Math.abs(number) >= 1000 ? 2 : Math.abs(number) >= 10 ? 3 : 5;
  return number.toLocaleString("en-US", {minimumFractionDigits: Math.min(2, digits), maximumFractionDigits: digits});
}

/** Reward:risk as "1:2.35" (reward per unit of risk); null when not calculable. */
export function formatRiskReward(rr) {
  if (!finite(rr) || Number(rr) <= 0) return null;
  return "1:" + Number(Number(rr).toFixed(2)).toString();
}

export function formatUtc(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const pad = n => String(n).padStart(2, "0");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return pad(date.getUTCHours()) + ":" + pad(date.getUTCMinutes()) + " UTC · " + date.getUTCDate() + " " + months[date.getUTCMonth()];
}

export function formatDuration(seconds) {
  if (!finite(seconds)) return null;
  const n = Math.max(0, Math.floor(Number(seconds)));
  if (n < 60) return n + "s";
  if (n < 3600) return Math.floor(n / 60) + " min";
  if (n < 86400) return Math.floor(n / 3600) + "h " + Math.floor((n % 3600) / 60) + "m";
  return Math.floor(n / 86400) + "d " + Math.floor((n % 86400) / 3600) + "h";
}

function sessionName(row) {
  const session = row?.session;
  if (session && typeof session === "object") return session.session || null;
  return session ? String(session) : null;
}

// Scanner reasons are "; "-joined clauses; present them as capitalised sentences.
function sentence(text) {
  const parts = String(text || "").split(";").map(part => part.trim()).filter(Boolean);
  if (!parts.length) return null;
  return parts.map(part => {
    const capital = part[0].toUpperCase() + part.slice(1);
    return /[.!?]$/.test(capital) ? capital : capital + ".";
  }).join(" ");
}

/**
 * The plan a confirmed setup was confirmed with (backend `confirmed_plan`, read
 * from the confirmation snapshot). It is immutable: later observations of an
 * active setup re-evaluate at the live price, so their entry/stop/R:R drift and
 * are the latest market observation, never the setup's plan.
 */
export function confirmedPlan(row) {
  const plan = row?.confirmed_plan;
  return plan && typeof plan === "object" ? plan : null;
}

/**
 * Trade levels, only when the engine produced a full plan (stop AND target).
 * Before that, "entry" is just the live price, so it is deliberately not shown
 * as an entry. A confirmed setup always shows its confirmed plan (basis
 * "confirmation"); anything else shows the latest observation (basis "latest").
 */
export function tradeLevels(row, analysis = null) {
  const plan = confirmedPlan(row);
  const risk = plan ? {} : (analysis?.risk_context || {});
  const features = row?.features || {};
  const pick = (fromPlan, ...rest) => plan ? (fromPlan ?? null) : (rest.find(value => value !== undefined && value !== null) ?? null);
  const stop = pick(plan?.stop_loss, risk.stop_loss, row?.proposed_stop_loss, row?.stop_loss);
  const target = pick(plan?.take_profit, risk.take_profit, row?.proposed_take_profit, row?.take_profit);
  const planned = finite(stop) && finite(target);
  const entry = planned ? pick(plan?.entry, risk.entry, row?.proposed_entry, row?.entry) : null;
  const rr = planned ? pick(plan?.rr, risk.rr, row?.rr, features.rr) : null;
  const invalidation = plan ? (plan.invalidation_price ?? plan.stop_loss ?? null)
    : (risk.invalidation ?? row?.invalidation_price ?? row?.rule_evidence?.invalidation_hint ?? row?.invalidation_hint ?? null);
  const distance = key => {
    const value = plan ? plan[key] : features[key];
    return finite(value) ? Number(value) : null;
  };
  return {
    planned,
    basis: plan ? "confirmation" : "latest",
    entry: formatPrice(entry),
    stop: formatPrice(stop),
    target: formatPrice(target),
    rr: formatRiskReward(rr),
    invalidation: formatPrice(invalidation),
    raw: planned ? {entry: finite(entry) ? Number(entry) : null, stop: Number(stop), target: Number(target),
      riskDistance: distance("risk_distance"), rewardDistance: distance("reward_distance")} : null,
  };
}

// Stop-quality labels, only ever read from backend stop evidence (Trend/Momentum v2).
export const RISK_QUALITY = Object.freeze({
  NORMAL_RISK: {label: "Normal risk", tone: "ok", help: "Stop distance inside the strategy's normal volatility envelope."},
  WIDE_STRUCTURE: {label: "Wide structure", tone: "wide", help: "Structural stop is valid but wider than normal."},
  RISK_REJECTED: {label: "Risk rejected", tone: "reject", help: "Structural invalidation requires excessive risk. Setup rejected."},
  STOP_TOO_TIGHT: {label: "Stop too tight", tone: "reject", help: "Entry sits inside normal noise of the structural stop. Not confirmed."},
  INVALID: {label: "Beyond stop", tone: "reject", help: "Price is already beyond the structural invalidation level."},
});

/** Backend stop evidence for the plan being shown (confirmed plan first), or null. */
export function stopEvidence(row) {
  const plan = confirmedPlan(row);
  const evidence = plan ? plan.stop_evidence : row?.strategy_evidence?.stop;
  return evidence && typeof evidence === "object" && evidence.risk_quality ? evidence : null;
}

/**
 * Geometry of the risk bar, from backend levels only: nothing is recalculated as a
 * plan. Segments are the backend risk/reward distances (or, for records that
 * predate them, the plain distances between the backend's own entry, stop and
 * target). `axis` runs low price -> high price, so a SHORT mirrors a LONG.
 */
export function riskModel(row, analysis = null) {
  const levels = tradeLevels(row, analysis);
  const dir = direction(row);
  if (!levels.planned || !levels.raw || levels.raw.entry == null || !dir) return null;
  const {entry, stop, target} = levels.raw;
  const risk = levels.raw.riskDistance ?? Math.abs(entry - stop);
  const reward = levels.raw.rewardDistance ?? Math.abs(target - entry);
  if (!(risk > 0) || !(reward > 0)) return null;
  const riskShare = risk / (risk + reward);
  const stopInfo = stopEvidence(row);
  const quality = stopInfo ? RISK_QUALITY[stopInfo.risk_quality] || null : null;
  const stopText = {key: "stop", label: "Stop", value: levels.stop};
  const entryText = {key: "entry", label: "Entry", value: levels.entry};
  const targetText = {key: "target", label: "Target", value: levels.target};
  return {
    direction: dir, basis: levels.basis, rr: levels.rr, riskShare, rewardShare: 1 - riskShare,
    axis: dir === "LONG" ? [stopText, entryText, targetText] : [targetText, entryText, stopText],
    segments: dir === "LONG" ? ["risk", "reward"] : ["reward", "risk"],
    quality: quality ? {key: stopInfo.risk_quality, ...quality} : null,
    structural: stopInfo?.basis === "STRUCTURAL",
    stopAtr: finite(stopInfo?.stop_distance_atr_h1) ? Number(stopInfo.stop_distance_atr_h1) : null,
    rejection: stopInfo?.rejection_reason || null,
  };
}

// The lifecycle as TRADeden shows it. CLOSED stands for any terminal state.
export const LIFECYCLE_STEPS = ["WATCHING", "DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE", "CLOSED"];

/**
 * Lifecycle rail from the backend's own lifecycle events and current state:
 * reached steps (with event times), the current step, and the terminal state a
 * closed setup ended in. Nothing is inferred beyond what the events record.
 */
export function lifecycleRail(row) {
  const events = Array.isArray(row?.lifecycle_events) ? row.lifecycle_events : [];
  const current = upper(row?.lifecycle_state) || (upper(row?.state) === "WATCHING" ? "WATCHING" : "");
  const terminal = TERMINAL.has(current) ? current : null;
  const reachedAt = new Map([["WATCHING", null]]);
  for (const event of events) {
    const to = upper(event?.to_state);
    const step = TERMINAL.has(to) ? "CLOSED" : to;
    if (LIFECYCLE_STEPS.includes(step) && !reachedAt.has(step)) reachedAt.set(step, event.occurred_at || null);
  }
  const currentStep = terminal ? "CLOSED" : LIFECYCLE_STEPS.includes(current) ? current : "WATCHING";
  if (!reachedAt.has(currentStep)) reachedAt.set(currentStep, null);
  return {
    current: currentStep, terminal,
    steps: LIFECYCLE_STEPS.map(step => ({step, label: step === "CLOSED" && terminal ? terminal : step,
      reached: reachedAt.has(step), current: step === currentStep, time: formatUtc(reachedAt.get(step))})),
  };
}

/** Why the setup exists: the reason recorded at confirmation for a confirmed setup, else the latest one. */
export function setupReason(row) {
  return confirmedPlan(row)?.reason || row?.reason || row?.rule_evidence?.reason || row?.insight || null;
}

/** The observation the analyst should explain: a confirmed setup's confirmation snapshot. */
export function analysisObservationId(row) {
  return row?.confirmation?.observation_id || row?.observation_id || null;
}

const CONTEXT_TYPES = new Set(["WATCHING", "GENERAL"]);

/**
 * Setup type of an episode. A confirmed episode keeps the type it was confirmed
 * as (the confirmation event), even when its latest observation has since become
 * directional context: the latest observation is reported separately.
 */
export function setupTypeOf(row) {
  return row?.confirmation?.setup_type || row?.setup_type || row?.setup_family || row?.setup || null;
}

/** "Directional context" when a confirmed episode's latest observation is context-only, else null. */
export function latestObservationNote(row) {
  if (!row?.confirmation) return null;
  const latest = upper(row?.setup_type);
  return CONTEXT_TYPES.has(latest) && latest !== upper(row.confirmation.setup_type) ? "Directional context" : null;
}

/** Everything a setup card shows, with explicit null for unavailable values. */
export function setupCardModel(row, {bucket = null, analysis = null, tracked = false, simulated = false} = {}) {
  const stage = gardenStage(row);
  const dir = direction(row);
  const confirmedAt = row?.confirmation?.confirmed_at || row?.confirmation_time || row?.confirmed_at || null;
  const closed = row?.closed_event || null;
  const reason = setupReason(row);
  const stageInfo = GARDEN_STAGES[stage];
  const headline = stage === "bloomed" || stage === "active"
    ? (upper(row?.lifecycle_state) || "CONFIRMED") + (dir ? " " + dir : "")
    : stage === "history"
      ? (upper(row?.lifecycle_state) || "CLOSED") + (dir ? " · " + dir : "")
      : stageInfo.label.toUpperCase() + (dir ? " · " + dir : "");
  const levels = tradeLevels(row, analysis);
  const plan = confirmedPlan(row);
  return {
    id: row?.setup_id || null,
    key: row?.setup_id || (row?.symbol ? "mkt-" + row.symbol : null),
    symbol: row?.symbol || "Unknown symbol",
    direction: dir,
    stage,
    stageIcon: stageInfo.icon,
    stageLabel: stageInfo.label,
    headline,
    tone: cardTone(stage, dir),
    bucket: bucket || (stage === "history" ? "history" : stage === "bloomed" || stage === "active" ? "bloomed" : "growing"),
    // A confirmed setup keeps the score it was confirmed with; the latest observation's score drifts.
    score: finite(plan?.score ?? row?.score) ? Math.round(Number(plan?.score ?? row.score)) : null,
    setupType: setupFamilyLabel(setupTypeOf(row), dir),
    latestObservation: latestObservationNote(row),
    strategy: strategyTag(strategyIdOf(row)),
    strategyVersion: row?.confirmation?.strategy_version || row?.strategy_version || null,
    timeframe: row?.timeframe || null,
    levels,
    risk: riskModel(row, analysis),
    rail: lifecycleRail(row),
    watching: stage === "growing" && ["DETECTED", "WATCHING"].includes(upper(row?.lifecycle_state || row?.state)),
    // A confirmed setup whose latest observation re-planned at the live price.
    planDrift: Boolean(plan && finite(row?.proposed_entry) && finite(plan.entry) && Number(row.proposed_entry) !== Number(plan.entry)),
    why: sentence(reason) || sentence(analysis?.summary) || null,
    confirmationTime: formatUtc(confirmedAt),
    detectedTime: formatUtc(row?.detected_at || row?.observed_at || row?.timestamp),
    lastObserved: formatUtc(row?.observed_at || row?.timestamp),
    duration: formatDuration(row?.duration_seconds),
    session: sessionName(row),
    status: upper(row?.lifecycle_state || row?.state) || null,
    closedReason: closed ? (closed.reason || closed.reason_code || null) : null,
    closedTime: closed ? formatUtc(closed.occurred_at) : null,
    tracked: Boolean(tracked),
    simulated: Boolean(simulated || row?.simulated),
  };
}

/**
 * Split episodes into the three garden areas. Falls back to live scanner
 * markets only when the engine has no persisted episodes at all (same rule as
 * the previous radar). The live areas (growing, bloomed) hold only setups of
 * strategies the registry reports as LIVE; shadow or disabled strategies never
 * appear as live setups. History keeps every recorded setup.
 */
export function gardenAreas(episodes, markets = [], {registry = null} = {}) {
  // One entry per episode: a setup_id listed in more than one bucket keeps its last
  // (most advanced) copy, so no episode is shown or counted twice.
  const bySetup = new Map();
  const loose = [];
  for (const row of [...(episodes?.current || []), ...(episodes?.confirmed || []), ...(episodes?.closed || [])]) {
    if (row?.setup_id) {
      bySetup.delete(String(row.setup_id));
      bySetup.set(String(row.setup_id), row);
    } else {
      loose.push(row);
    }
  }
  const all = [...bySetup.values(), ...loose];
  const parts = partitionSetupEpisodes(all);
  let growing = parts.current;
  if (!all.length) growing = currentWatchSetups(markets);
  const rank = row => STAGE_ORDER.indexOf(gardenStage(row));
  const byStageThenScore = (a, b) => rank(a) - rank(b) || (Number(b.score) || 0) - (Number(a.score) || 0);
  return {
    growing: liveGardenRows(growing, registry).sort(byStageThenScore),
    bloomed: liveGardenRows(parts.confirmed, registry).sort(byStageThenScore),
    history: parts.closed,
  };
}

/** Live hero counters. null means "unavailable" (engine offline), never a fake 0. */
export function gardenCounters({markets = [], episodes = null, mode = "LIVE", registry = null} = {}) {
  if (mode === "OFFLINE") return {watched: null, watching: null, developing: null, confirmed: null, growing: null, confirming: null, bloomed: null, active: null, byStrategy: null};
  const areas = gardenAreas(episodes, markets, {registry});
  const live = [...areas.growing, ...areas.bloomed];
  const count = stage => live.filter(row => gardenStage(row) === stage).length;
  const watching = live.filter(row => gardenStage(row) === "growing" && ["DETECTED", "WATCHING", ""].includes(upper(row?.lifecycle_state || row?.state))).length;
  return {
    watched: markets.length,
    watching,
    developing: count("growing") - watching + count("shaping"),
    confirmed: count("bloomed") + count("active"),
    growing: count("growing"),
    confirming: count("shaping"),
    bloomed: count("bloomed"),
    active: count("active"),
    byStrategy: strategyBreakdown(live),
  };
}

/**
 * The compact Garden header: LIVE strategies with their versions, instruments
 * monitored, confirmed / developing / watching setups (each setup_id once), the
 * last scan and the engine status. null values mean "unavailable", never 0.
 */
export function gardenHeaderModel({markets = [], episodes = null, mode = "LIVE", registry = null, lastScan = null} = {}) {
  const counters = gardenCounters({markets, episodes, mode, registry});
  const live = (Array.isArray(registry) ? registry : []).filter(item => String(item?.status).toUpperCase() === "LIVE")
    .map(item => ({...strategyTag(item.strategy_id), version: item.version || null}));
  return {
    mode,
    engine: {LIVE: "Engine live", ENGINE_NO_DATA: "Engine online · no market data", OFFLINE: "Engine offline", DEMO: "Demo · not scanning"}[mode] || mode,
    strategies: live,
    instruments: mode === "OFFLINE" ? null : markets.length,
    confirmed: counters.confirmed, developing: counters.developing, watching: counters.watching,
    lastScan: mode === "OFFLINE" ? null : formatUtc(lastScan),
    byStrategy: counters.byStrategy,
  };
}

/**
 * Rule-based analyst view for one selected setup or market. The wording follows
 * the setup's real lifecycle: live (developing/confirming), confirmed (bloomed/
 * active) or history (closed). History is presented as a record, never as live
 * analysis; `archive` is the archiveEntry for closed setups.
 */
export function analystModel(row, analysis = null, archive = null) {
  if (!row) return null;
  const stage = gardenStage(row);
  const context = stage === "history" ? "history" : stage === "bloomed" || stage === "active" ? "confirmed" : "live";
  const levels = tradeLevels(row, analysis);
  const claims = items => (items || []).map(item => item?.claim).filter(Boolean);
  const conflicts = claims(analysis?.conflicts).map(text => "Conflict: " + text);
  const trigger = row?.trigger || row?.rule_evidence?.trigger;
  const reasoning = sentence(confirmedPlan(row)?.reason || row.reason || row?.rule_evidence?.reason);
  const base = {
    symbol: row.symbol || "Unknown symbol", stage, context, direction: direction(row), levels,
    strategy: strategyTag(strategyIdOf(row)), strategyVersion: row?.confirmation?.strategy_version || row?.strategy_version || null,
    risk: riskModel(row, analysis), stop: stopEvidence(row), rail: lifecycleRail(row), setupId: row?.setup_id || null,
    analystVersion: analysis?.analyst_version || null, analysisLoaded: Boolean(analysis),
    stillNeeded: [], watchingFor: null, outcome: null,
  };
  if (context === "history") {
    const closed = row?.closed_event || {};
    const lifecycle = upper(row?.lifecycle_state) || "CLOSED";
    const confirmed = Boolean(row?.confirmation);
    const when = formatUtc(closed.occurred_at);
    const confirmedAt = formatUtc(row?.confirmation?.confirmed_at || row?.confirmation_time);
    const happened = confirmed
      ? "Confirmed" + (confirmedAt ? " at " + confirmedAt : "") + ", then " + lifecycle.toLowerCase() + (when ? " at " + when : "") + "."
      : lifecycle.charAt(0) + lifecycle.slice(1).toLowerCase() + " before confirmation" + (when ? " at " + when : "") + ".";
    const invalidates = [];
    const closeReason = closed.reason || closed.reason_code;
    if (closeReason) invalidates.push(sentence(closeReason));
    invalidates.push(...conflicts);
    return {...base,
      titles: {happening: "What happened", matters: "Why the setup formed", confirms: "What confirmed it", invalidates: "What invalidated it"},
      happening: happened,
      matters: reasoning,
      neverConfirmed: !confirmed,
      confirms: confirmed ? claims(analysis?.confirmations).slice(0, 6) : [],
      confirmsEmpty: confirmed ? "No confirming evidence was recorded." : "It never passed the confirmation rules, so it was not a TRADeden setup to act on.",
      invalidates,
      invalidatesEmpty: "No closing reason was recorded.",
      outcome: archive ? {icon: archive.icon, label: archive.label, horizon: archive.horizon, rText: archive.rText, confirmed: archive.confirmed, kind: archive.kind} : null,
    };
  }
  const invalidates = [];
  if (levels.invalidation) invalidates.push("A move through " + levels.invalidation + (context === "confirmed" ? " would invalidate the setup." : " invalidates the setup."));
  else if (levels.stop) invalidates.push("The calculated stop at " + levels.stop + " marks where the setup is wrong.");
  invalidates.push(...conflicts);
  return {...base,
    titles: context === "confirmed"
      ? {happening: "What is happening", matters: "Why it matters", confirms: "What confirmed it", invalidates: "What would invalidate it"}
      : {happening: "What is happening", matters: "Why it matters", confirms: "What confirms it", invalidates: "What invalidates it"},
    happening: sentence(analysis?.summary) || sentence(row.insight) || reasoning || null,
    matters: reasoning,
    confirms: claims(analysis?.confirmations).slice(0, 6),
    confirmsEmpty: analysis ? "No confirming evidence recorded yet." : "Evidence unavailable for this item.",
    stillNeeded: context === "live" ? claims(analysis?.missing_confirmations).slice(0, 4) : [],
    watchingFor: context === "live" ? sentence(trigger) : null,
    invalidates,
    invalidatesEmpty: "No invalidation level has been calculated yet.",
  };
}

// ----- market research: the deeper, read-only view of one setup or market ----------
// Each research section lists recorded scanner fields and the analyst evidence of
// the matching categories. Nothing is derived: a missing field is simply absent,
// and an empty section renders as "Not available".
const RESEARCH_FIELDS = Object.freeze({
  structure: [["structure", "Structure"], ["price_action_state", "Price action state"], ["price_action", "Price action"]],
  trend: [["higher_timeframe_bias", "Higher-timeframe bias"], ["market_bias", "Market bias"], ["trendline", "Trendline"],
    ["trendline_state", "Trendline state"], ["ema20", "EMA 20"], ["ema50", "EMA 50"]],
  momentum: [["momentum", "Momentum"], ["rsi", "RSI"]],
  levels: [["nearest_level_type", "Nearest level"], ["nearest_level", "Level price"], ["nearest_level_atr", "Distance to level"], ["atr", "ATR"]],
});
const RESEARCH_CATEGORY = Object.freeze({structure: "structure", price_action: "structure", higher_timeframe: "trend", trendline: "trend",
  momentum: "momentum", support_resistance: "levels"});
const PRICE_FIELDS = new Set(["ema20", "ema50", "nearest_level", "atr"]);

function researchValue(key, value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "object") return null;                 // e.g. trendline_line geometry: not a display fact
  if (PRICE_FIELDS.has(key)) return formatPrice(value);
  if (key === "rsi") return finite(value) ? Number(value).toFixed(1) : null;
  if (key === "nearest_level_atr") return finite(value) ? Number(value).toFixed(2) + " ATR" : null;
  return String(value);
}

// Strategies that keep their own recorded context in `strategy_evidence` (S/R and
// Trend/Momentum). Paths into that record, per research section, with a display format.
const STRATEGY_RESEARCH = Object.freeze({
  trend_momentum: {
    structure: [["trend.h4.structure", "H4 structure", "text"], ["pullback.retracement", "Pullback retracement", "percent"],
      ["pullback.controlled", "Pullback controlled", "bool"], ["pullback.pullback_bars", "Pullback bars", "number"]],
    trend: [["trend.h4.direction", "H4 trend", "text"], ["trend.h4.ema50_slope_atr", "H4 EMA50 slope", "atr"], ["trend.d1.status", "D1 context", "text"],
      ["trend.h1.aligned", "H1 aligned", "bool"], ["trend.h1.ema20", "H1 EMA 20", "price"], ["trend.h1.ema50", "H1 EMA 50", "price"]],
    momentum: [["momentum.impulse_atr", "Impulse", "atr"], ["momentum.efficiency", "Efficiency ratio", "ratio"], ["momentum.impulse_bars", "Impulse bars", "number"],
      ["trigger.resumption", "Resumption trigger", "bool"]],
    levels: [["trend.h4.last_swing_highs", "H4 swing highs", "prices"], ["trend.h4.last_swing_lows", "H4 swing lows", "prices"],
      ["trigger.break_level", "Trigger break level", "price"], ["plan.structure_invalidation", "Structural invalidation", "price"]],
  },
  support_resistance: {
    structure: [["family", "Setup family", "text"], ["touch.clean_test", "Clean test of the level", "bool"], ["rejection.confirmed", "Rejection confirmed", "bool"]],
    trend: [],
    momentum: [["confirmation.rules.momentum", "Momentum rule", "bool"]],
    levels: [["level.type", "Level", "text"], ["level.price", "Level price", "price"], ["level.zone_low", "Zone low", "price"], ["level.zone_high", "Zone high", "price"],
      ["level.reactions", "Reactions", "number"], ["level.strength", "Strength", "number"], ["level.role_reversal", "Role reversal", "bool"],
      ["level.higher_timeframe_confluence", "Higher-timeframe confluence", "bool"], ["distance_atr_h1", "Distance to level", "atr"]],
  },
});
const humanize = text => { const s = String(text).replace(/_/g, " ").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); };
const atPath = (object, path) => path.split(".").reduce((value, key) => (value == null ? undefined : value[key]), object);
function formatEvidence(value, kind) {
  if (value === null || value === undefined || value === "") return null;
  if (kind === "bool") return typeof value === "boolean" ? (value ? "Yes" : "No") : null;
  if (kind === "prices") return Array.isArray(value) && value.length ? value.map(formatPrice).filter(Boolean).join(", ") || null : null;
  if (typeof value === "object") return null;
  if (kind === "price") return formatPrice(value);
  if (kind === "atr") return finite(value) ? Number(value).toFixed(2) + " ATR" : null;
  if (kind === "percent") return finite(value) ? (Number(value) * 100).toFixed(1) + "%" : null;
  if (kind === "ratio") return finite(value) ? Number(value).toFixed(2) : null;
  if (kind === "number") return finite(value) ? String(Number(value)) : null;
  return /^[A-Z0-9_]+$/.test(String(value)) ? humanize(value) : String(value);
}

/** A strategy's own confirmation rules as recorded (passed / not passed), or []. */
export function strategyRules(row) {
  const table = row?.strategy_evidence?.confirmation?.rules;
  if (!table || typeof table !== "object") return [];
  return Object.entries(table).filter(([, passed]) => typeof passed === "boolean").map(([rule, passed]) => ({rule: humanize(rule), passed}));
}

/**
 * Everything the Market Research drawer shows for one row (an episode or a live
 * market). Setup facts come from what the setup recorded: snapshot `features`
 * (trendline) or the strategy's own `strategy_evidence` (S/R, Trend/Momentum).
 * `market` (the latest scan of the same symbol) fills a section only when the
 * setup recorded nothing for it, and only for setups that are still open; those
 * facts are marked as scan context.
 */
export function researchModel(row, {analysis = null, archive = null, simulated = false, market = null} = {}) {
  if (!row) return null;
  const features = row.features && typeof row.features === "object" ? row.features : {};
  const hasFeatures = RESEARCH_FIELDS.structure.concat(RESEARCH_FIELDS.trend, RESEARCH_FIELDS.momentum).some(([key]) => features[key] != null);
  const own = row.setup_id ? features : row;             // a bare market row carries its fields at the top level
  const strategyFields = STRATEGY_RESEARCH[strategyIdOf(row)] || null;
  const evidenceRecord = row.strategy_evidence && typeof row.strategy_evidence === "object" ? row.strategy_evidence : null;
  const closed = gardenStage(row) === "history";
  const scan = !closed && row.setup_id && market && market !== row ? market : null;
  const evidenceIn = (list, tone) => (list || []).filter(item => item?.claim).map(item => ({tone, claim: item.claim, category: item.category || null}));
  const supporting = evidenceIn(analysis?.confirmations, "support");
  const opposing = evidenceIn(analysis?.conflicts, "oppose");
  const missing = evidenceIn(analysis?.missing_confirmations, "missing");
  const fromFields = (source, fields) => fields.map(([key, label]) => ({label, value: researchValue(key, source?.[key])})).filter(fact => fact.value != null);
  const sections = {};
  for (const [name, fields] of Object.entries(RESEARCH_FIELDS)) {
    const facts = fromFields(own, fields);
    if (strategyFields && evidenceRecord) {
      for (const [path, label, kind] of strategyFields[name] || []) {
        const value = formatEvidence(atPath(evidenceRecord, path), kind);
        if (value != null) facts.push({label, value});
      }
    }
    sections[name] = {
      facts,
      scan: facts.length || !scan ? [] : fromFields(scan, fields),
      evidence: [...supporting, ...opposing].filter(item => RESEARCH_CATEGORY[item.category] === name),
    };
  }
  return {
    card: setupCardModel(row, {analysis, simulated}),
    analyst: analystModel(row, analysis, archive),
    sections,
    rules: strategyRules(row),
    evidence: {supporting, opposing, missing},
    basis: !row.setup_id ? "live" : hasFeatures || evidenceRecord ? "recorded" : "live",
    analysisLoaded: Boolean(analysis),
    hasSetup: Boolean(row.setup_id),
  };
}

export function marketOverviewRow(market, registry = null) {
  const move = finite(market?.change_pct) ? Number(market.change_pct) : null;
  const bias = upper(market?.direction) || upper(market?.market_bias) || null;
  return {
    symbol: market?.symbol || "Unknown",
    price: formatPrice(market?.price),
    change: move == null ? null : (move >= 0 ? "+" : "") + move.toFixed(2) + "%",
    changeTone: move == null ? "flat" : move >= 0 ? "up" : "down",
    direction: bias,
    state: upper(market?.state) || null,
    lifecycle: upper(market?.lifecycle_state) || upper(market?.state) || null,
    setupStatus: market?.lifecycle_state ? GARDEN_STAGES[gardenStage(market)].label : "No setup",
    stage: market?.lifecycle_state ? gardenStage(market) : null,
    score: finite(market?.score) ? Math.round(Number(market.score)) : null,
    // Per-strategy results; the top-level fields above stay the trendline result.
    strategies: strategyMatrix(market, registry),
    conflict: strategyConflict(market, registry),
  };
}

// ----- constellation layout ---------------------------------------------------
function hash(text) {
  let h = 2166136261;
  for (const char of String(text)) { h ^= char.charCodeAt(0); h = Math.imul(h, 16777619); }
  return (h >>> 0) / 4294967295;
}

// Concentric lifecycle bands on the constellation plane: what matters most sits
// nearest the centre; closed setups settle on a faint outer archive ring.
export const BANDS = Object.freeze({
  bloomed: {r: [0.9, 2.2], y: [0.6, 1.2], min: 1.25},
  active: {r: [1.3, 2.6], y: [0.5, 1.1], min: 1.3},
  shaping: {r: [2.6, 3.6], y: [0.4, 1.15], min: 1.0},
  growing: {r: [3.5, 4.6], y: [0.3, 1.25], min: 0.85},
  history: {r: [5.3, 6.1], y: [0.05, 0.3], min: 0.5},
});
export const MAX_ORBS = {history: 18, growing: 18, shaping: 10, bloomed: 10, active: 8};

// Each live strategy grows in its own sector ("branch") of the garden, so strategy
// identity is visible in the constellation itself. Unknown strategies share a sector.
export const STRATEGY_SECTORS = Object.freeze({trendline: 0, trendline_v5: 0, support_resistance: 1, trend_momentum: 2});
const SECTOR_WIDTH = (Math.PI * 2) / 3;
const SECTOR_SPREAD = SECTOR_WIDTH * 0.42;          // half-width used by orbs (a gap between sectors)
export function sectorAngle(strategyId) {
  const index = STRATEGY_SECTORS[strategyId];
  return (index === undefined ? 3.5 : index) * SECTOR_WIDTH - Math.PI / 2;
}
const wrap = angle => Math.atan2(Math.sin(angle), Math.cos(angle));
// Strategy identity colours: muted, distinct from the long/short/stage colours.
export const STRATEGY_COLORS = Object.freeze({trendline: "#4f86a8", trendline_v5: "#4f86a8", support_resistance: "#b3843a", trend_momentum: "#7c6bbf"});
export const OTHER_STRATEGY_COLOR = "#8fa396";

/** Sector labels and trunks for the strategies that have orbs (for either renderer). */
export function strategySectors(orbs) {
  const ids = [...new Set(orbs.filter(orb => orb.stage !== "history").map(orb => orb.strategy))];
  return ids.map(id => ({id, tag: strategyTag(id).tag, label: strategyTag(id).label, angle: sectorAngle(id),
    color: STRATEGY_COLORS[id] || OTHER_STRATEGY_COLOR}));
}

/**
 * Branch geometry in layout units: a trunk from the centre along the strategy's
 * sector, and a curve from the trunk to each live orb. Purely visual structure.
 */
export function branchCurves(orbs) {
  return orbs.filter(orb => orb.stage !== "history").map(orb => {
    const radius = Math.hypot(orb.x, orb.z);
    const hub = {x: Math.cos(orb.centre) * 0.7, z: Math.sin(orb.centre) * 0.7};
    const control = {x: Math.cos(orb.centre) * radius * 0.62, z: Math.sin(orb.centre) * radius * 0.62};
    return {id: orb.id, strategy: orb.strategy, stage: orb.stage, color: STRATEGY_COLORS[orb.strategy] || OTHER_STRATEGY_COLOR,
      hub, control, end: {x: orb.x, y: orb.y, z: orb.z}};
  });
}

/**
 * Orb positions for the garden visual. A pure function of setup key and stage,
 * so orbs never jump between refreshes; a relaxation pass keeps orbs apart and a
 * final clamp keeps each one inside its lifecycle band.
 */
export function constellationLayout(cards, selectedId = null) {
  const counts = {};
  const orbs = [];
  for (const card of cards) {
    if (!card?.key) continue;
    counts[card.stage] = (counts[card.stage] || 0) + 1;
    if (counts[card.stage] > (MAX_ORBS[card.stage] || 10)) continue;
    const band = BANDS[card.stage] || BANDS.growing;
    const strategy = card.strategy?.id || null;
    const centre = sectorAngle(strategy);
    const angle = centre + (hash(card.key + ":a") * 2 - 1) * SECTOR_SPREAD;
    const radius = band.r[0] + hash(card.key + ":r") * (band.r[1] - band.r[0]);
    orbs.push({
      id: card.key, symbol: card.symbol, stage: card.stage, direction: card.direction, strategy, centre,
      score: card.score, selected: card.key === selectedId, outcome: card.outcome || null,
      x: Math.cos(angle) * radius, z: Math.sin(angle) * radius,
      y: band.y[0] + hash(card.key + ":y") * (band.y[1] - band.y[0]),
      phase: hash(card.key + ":p") * Math.PI * 2,
    });
  }
  for (let pass = 0; pass < 8; pass++) {
    for (let i = 0; i < orbs.length; i++) {
      for (let j = i + 1; j < orbs.length; j++) {
        const a = orbs[i], b = orbs[j];
        const need = Math.max(BANDS[a.stage].min, BANDS[b.stage].min);
        const dx = b.x - a.x, dz = b.z - a.z, distance = Math.hypot(dx, dz) || 0.001;
        if (distance < need) {
          const push = (need - distance) / 2, ux = dx / distance, uz = dz / distance;
          a.x -= ux * push; a.z -= uz * push; b.x += ux * push; b.z += uz * push;
        }
      }
    }
    for (const orb of orbs) {                 // stay inside the lifecycle band and the strategy's sector
      const band = BANDS[orb.stage], radius = Math.hypot(orb.x, orb.z) || 0.001;
      const clamped = Math.max(band.r[0], Math.min(band.r[1], radius));
      const offset = Math.max(-SECTOR_SPREAD, Math.min(SECTOR_SPREAD, wrap(Math.atan2(orb.z, orb.x) - orb.centre)));
      orb.x = Math.cos(orb.centre + offset) * clamped; orb.z = Math.sin(orb.centre + offset) * clamped;
    }
  }
  return orbs;
}

// ----- archive: what happened to the setups TRADeden surfaced --------------------
export const ARCHIVE_KINDS = Object.freeze({
  target: {icon: "🎯", label: "Target hit", tone: "target"},
  stop: {icon: "🛑", label: "Stop hit", tone: "stop"},
  no_hit: {icon: "◌", label: "No barrier hit", tone: "neutral"},
  ambiguous: {icon: "◐", label: "Ambiguous candle", tone: "neutral"},
  unverified: {icon: "…", label: "Outcome unverified", tone: "unverified"},
  pending: {icon: "⌛", label: "Outcome pending", tone: "unverified"},
  invalidated: {icon: "⚠️", label: "Invalidated", tone: "invalidated"},
  expired: {icon: "⏳", label: "Expired", tone: "expired"},
  closed: {icon: "·", label: "Closed", tone: "expired"},
});
const HORIZONS = ["15m", "1h", "4h", "24h"];

/**
 * Record-level mirror of backend ml_dataset._outcome_quarantine_reasons: an
 * outcome is only "known" when its timestamps are verified and its candle
 * chronology is proven. Legacy records without these fields stay unverified.
 */
export function isValidatedOutcome(outcome) {
  const validation = outcome?.outcome_time_validation || {};
  return outcome?.label_definition === "target-invalidation-first-v1"
    && outcome?.timestamp_quality === "VERIFIED"
    && outcome?.data_quality?.timestamp_quality === "VERIFIED"
    && outcome?.outcome_time_validity === "OUTCOME_TIME_VALID"
    && validation.outcome_time_validity === "OUTCOME_TIME_VALID"
    && validation.every_candidate_strictly_after_observation === true
    && validation.candidate_candles_chronological === true;
}

const num = value => (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) ? null : Number(value);

/**
 * R multiple for a verified barrier hit, only when the barriers the outcome was
 * labelled against are provably the planned stop and target of the confirmation
 * snapshot. Otherwise null (never estimated).
 */
export function outcomeR(kind, snapshot) {
  if (!snapshot || (kind !== "target" && kind !== "stop")) return null;
  const stop = num(snapshot.proposed_stop_loss), target = num(snapshot.proposed_take_profit);
  const reference = num(snapshot.reference_price ?? snapshot.proposed_entry);
  const invalidation = num(snapshot.invalidation_price);
  if (stop == null || target == null || reference == null) return null;
  if (invalidation != null && Math.abs(invalidation - stop) > 1e-9) return null;   // labelled against another barrier
  const risk = Math.abs(reference - stop), reward = Math.abs(target - reference);
  if (!(risk > 0)) return null;
  return kind === "stop" ? -1 : Number((reward / risk).toFixed(2));
}

/**
 * One archive entry for a closed episode.
 * `outcomes`: market_outcome records (any, unfiltered) for this setup.
 * `confirmationSnapshot`: the snapshot the confirmation was recorded on, if loaded.
 */
export function archiveEntry(episode, outcomes = [], confirmationSnapshot = null) {
  const lifecycle = String(episode?.lifecycle_state || "").toUpperCase();
  const confirmed = Boolean(episode?.confirmation);
  const confirmationObservation = episode?.confirmation?.observation_id || null;
  let kind, horizon = null, verifiedCount = 0, unverifiedCount = 0;
  if (!confirmed) {
    kind = lifecycle === "INVALIDATED" ? "invalidated" : lifecycle === "EXPIRED" ? "expired" : "closed";
  } else {
    const own = outcomes.filter(o => o?.setup_id === episode.setup_id && (!confirmationObservation || o.observation_id === confirmationObservation));
    const verified = own.filter(isValidatedOutcome);
    verifiedCount = verified.length;
    unverifiedCount = own.length - verified.length;
    const byHorizon = h => verified.find(o => o.horizon === h);
    // Barrier windows are nested (15m inside 1h inside ...), so the shortest
    // decisive horizon is when the first barrier was touched.
    const decisive = HORIZONS.map(byHorizon).find(o => o && (o.label === "WIN" || o.label === "LOSS"));
    const longest = [...HORIZONS].reverse().map(byHorizon).find(Boolean);
    if (decisive) { kind = decisive.label === "WIN" ? "target" : "stop"; horizon = decisive.horizon; }
    else if (longest) { kind = longest.label === "AMBIGUOUS" ? "ambiguous" : "no_hit"; horizon = longest.horizon; }
    else kind = own.length ? "unverified" : "pending";
  }
  const r = outcomeR(kind, confirmationSnapshot);
  const closedAt = episode?.closed_event?.occurred_at || episode?.observed_at || null;
  const strategyId = strategyIdOf(episode);
  return {
    key: episode?.setup_id || null,
    symbol: episode?.symbol || "Unknown",
    direction: direction(episode),
    strategy_id: strategyId,
    strategy: strategyTag(strategyId),
    setupType: setupTypeOf(episode),
    confirmed,
    kind,
    ...ARCHIVE_KINDS[kind],
    horizon,
    r,
    rText: r == null ? null : (r > 0 ? "+" : "") + r.toFixed(1) + "R",
    verifiedCount,
    unverifiedCount,
    lifecycle,
    closedAt,
    closedTime: formatUtc(closedAt),
    closedReason: episode?.closed_event?.reason || episode?.closed_event?.reason_code || null,
    score: num(episode?.score),
  };
}

/** Counts for the archive header. No win rate: only verified confirmed outcomes are "known". */
export function archiveSummary(entries) {
  const count = kind => entries.filter(entry => entry.kind === kind).length;
  const confirmed = entries.filter(entry => entry.confirmed);
  return {
    observed: entries.length,
    confirmed: confirmed.length,
    target: count("target"),
    stop: count("stop"),
    verifiedOutcomes: confirmed.filter(entry => entry.verifiedCount > 0).length,
    unverified: count("unverified") + count("pending"),
    invalidated: count("invalidated"),
    expired: count("expired"),
  };
}

/**
 * A confirmation bloom is a one-time reaction to a real lifecycle transition
 * observed while the garden is open: never on the first paint (replayed state),
 * never under reduced motion, never for an orb that was already bloomed.
 */
export function shouldBloom({previousStage, nextStage, firstUpdate, animate}) {
  return Boolean(animate && !firstUpdate && nextStage === "bloomed" && previousStage !== "bloomed");
}
