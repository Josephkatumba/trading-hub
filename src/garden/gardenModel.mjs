// TRADeden Garden view model. Pure functions only (no DOM), so they are unit-tested.
//
// The garden is a visual reading of the backend's lifecycle states. The backend
// lifecycle (DETECTED/DEVELOPING/CONFIRMING/CONFIRMED/ACTIVE/INVALIDATED/EXPIRED/
// RESOLVED) stays authoritative; nothing here changes or infers it. Every number
// shown comes from API data; anything missing becomes an explicit unavailable
// state rather than a guess.
import {currentWatchSetups, partitionSetupEpisodes} from "../radarLayout.mjs";

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
 * Trade levels, only when the engine produced a full plan (stop AND target).
 * Before that, "entry" is just the live price, so it is deliberately not shown
 * as an entry.
 */
export function tradeLevels(row, analysis = null) {
  const risk = analysis?.risk_context || {};
  const features = row?.features || {};
  const stop = risk.stop_loss ?? row?.proposed_stop_loss ?? row?.stop_loss ?? null;
  const target = risk.take_profit ?? row?.proposed_take_profit ?? row?.take_profit ?? null;
  const planned = finite(stop) && finite(target);
  const entry = planned ? (risk.entry ?? row?.proposed_entry ?? row?.entry ?? null) : null;
  const rr = planned ? (risk.rr ?? row?.rr ?? features.rr ?? null) : null;
  const invalidation = risk.invalidation ?? row?.invalidation_price ?? row?.rule_evidence?.invalidation_hint ?? row?.invalidation_hint ?? null;
  return {
    planned,
    entry: formatPrice(entry),
    stop: formatPrice(stop),
    target: formatPrice(target),
    rr: formatRiskReward(rr),
    invalidation: formatPrice(invalidation),
  };
}

/** Everything a setup card shows, with explicit null for unavailable values. */
export function setupCardModel(row, {bucket = null, analysis = null, tracked = false, simulated = false} = {}) {
  const stage = gardenStage(row);
  const dir = direction(row);
  const confirmedAt = row?.confirmation?.confirmed_at || row?.confirmation_time || row?.confirmed_at || null;
  const closed = row?.closed_event || null;
  const reason = row?.reason || row?.rule_evidence?.reason || row?.insight || null;
  const stageInfo = GARDEN_STAGES[stage];
  const headline = stage === "bloomed" || stage === "active"
    ? (upper(row?.lifecycle_state) || "CONFIRMED") + (dir ? " " + dir : "")
    : stage === "history"
      ? (upper(row?.lifecycle_state) || "CLOSED") + (dir ? " · " + dir : "")
      : stageInfo.label.toUpperCase() + (dir ? " · " + dir : "");
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
    score: finite(row?.score) ? Math.round(Number(row.score)) : null,
    setupType: row?.setup_type || row?.setup_family || row?.setup || null,
    timeframe: row?.timeframe || null,
    levels: tradeLevels(row, analysis),
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
 * the previous radar).
 */
export function gardenAreas(episodes, markets = []) {
  const all = [...(episodes?.current || []), ...(episodes?.confirmed || []), ...(episodes?.closed || [])];
  const parts = partitionSetupEpisodes(all);
  let growing = parts.current;
  if (!all.length) growing = currentWatchSetups(markets);
  const rank = row => STAGE_ORDER.indexOf(gardenStage(row));
  const byStageThenScore = (a, b) => rank(a) - rank(b) || (Number(b.score) || 0) - (Number(a.score) || 0);
  return {
    growing: [...growing].sort(byStageThenScore),
    bloomed: [...parts.confirmed].sort(byStageThenScore),
    history: parts.closed,
  };
}

/** Live hero counters. null means "unavailable" (engine offline), never a fake 0. */
export function gardenCounters({markets = [], episodes = null, mode = "LIVE"} = {}) {
  if (mode === "OFFLINE") return {watched: null, growing: null, confirming: null, bloomed: null, active: null};
  const areas = gardenAreas(episodes, markets);
  const live = [...areas.growing, ...areas.bloomed];
  const count = stage => live.filter(row => gardenStage(row) === stage).length;
  return {
    watched: markets.length,
    growing: count("growing"),
    confirming: count("shaping"),
    bloomed: count("bloomed"),
    active: count("active"),
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
  const reasoning = sentence(row.reason || row?.rule_evidence?.reason);
  const base = {
    symbol: row.symbol || "Unknown symbol", stage, context, direction: direction(row), levels,
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

export function marketOverviewRow(market) {
  const move = finite(market?.change_pct) ? Number(market.change_pct) : null;
  const bias = upper(market?.direction) || upper(market?.market_bias) || null;
  return {
    symbol: market?.symbol || "Unknown",
    price: formatPrice(market?.price),
    change: move == null ? null : (move >= 0 ? "+" : "") + move.toFixed(2) + "%",
    changeTone: move == null ? "flat" : move >= 0 ? "up" : "down",
    direction: bias,
    state: upper(market?.state) || null,
    setupStatus: market?.lifecycle_state ? GARDEN_STAGES[gardenStage(market)].label : "No setup",
    stage: market?.lifecycle_state ? gardenStage(market) : null,
    score: finite(market?.score) ? Math.round(Number(market.score)) : null,
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
    const angle = hash(card.key + ":a") * Math.PI * 2;
    const radius = band.r[0] + hash(card.key + ":r") * (band.r[1] - band.r[0]);
    orbs.push({
      id: card.key, symbol: card.symbol, stage: card.stage, direction: card.direction,
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
    for (const orb of orbs) {                 // stay inside the lifecycle band
      const band = BANDS[orb.stage], radius = Math.hypot(orb.x, orb.z) || 0.001;
      const clamped = Math.max(band.r[0], Math.min(band.r[1], radius));
      orb.x *= clamped / radius; orb.z *= clamped / radius;
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
  return {
    key: episode?.setup_id || null,
    symbol: episode?.symbol || "Unknown",
    direction: direction(episode),
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
