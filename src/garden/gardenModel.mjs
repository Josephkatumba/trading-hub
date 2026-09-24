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

/** Rule-based analyst view for one selected setup or market. */
export function analystModel(row, analysis = null) {
  if (!row) return null;
  const levels = tradeLevels(row, analysis);
  const claims = items => (items || []).map(item => item?.claim).filter(Boolean);
  const invalidates = [];
  if (levels.invalidation) invalidates.push("A move through " + levels.invalidation + " invalidates the setup.");
  else if (levels.stop) invalidates.push("The calculated stop at " + levels.stop + " marks where the setup is wrong.");
  invalidates.push(...claims(analysis?.conflicts).map(text => "Conflict: " + text));
  const trigger = row?.trigger || row?.rule_evidence?.trigger;
  return {
    symbol: row.symbol || "Unknown symbol",
    stage: gardenStage(row),
    direction: direction(row),
    happening: sentence(analysis?.summary) || sentence(row.insight) || sentence(row.reason || row?.rule_evidence?.reason) || null,
    matters: sentence(row.reason || row?.rule_evidence?.reason) || null,
    confirms: claims(analysis?.confirmations).slice(0, 6),
    stillNeeded: claims(analysis?.missing_confirmations).slice(0, 4),
    watchingFor: sentence(trigger),
    invalidates,
    levels,
    analystVersion: analysis?.analyst_version || null,
    analysisLoaded: Boolean(analysis),
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

// ----- plant layout -------------------------------------------------------
function hash(text) {
  let h = 2166136261;
  for (const char of String(text)) { h ^= char.charCodeAt(0); h = Math.imul(h, 16777619); }
  return (h >>> 0) / 4294967295;
}

const ZONES = {           // x range, z range (z grows toward the viewer; the view narrows at the front)
  history: {x: [-8, 8], z: [-5.0, -2.8]},
  growing: {x: [-6.8, 6.8], z: [-2.3, 0.4]},
  shaping: {x: [-5.8, 5.8], z: [-1.2, 1.0]},
  active: {x: [-4.8, 4.8], z: [0.3, 1.9]},
  bloomed: {x: [-3.6, 3.6], z: [2.0, 3.5]},
};
export const MAX_PLANTS = {history: 14, growing: 16, shaping: 10, bloomed: 10, active: 8};

/**
 * Plants for the garden scene. Positions are a pure function of setup id and
 * stage, so plants do not jump between refreshes; a small relaxation pass keeps
 * neighbours from overlapping.
 */
export function plantLayout(cards, selectedId = null) {
  const counts = {};
  const plants = [];
  for (const card of cards) {
    if (!card?.key) continue;
    counts[card.stage] = (counts[card.stage] || 0) + 1;
    if (counts[card.stage] > (MAX_PLANTS[card.stage] || 10)) continue;
    const zone = ZONES[card.stage] || ZONES.growing;
    plants.push({
      id: card.key, symbol: card.symbol, stage: card.stage, direction: card.direction,
      score: card.score, selected: card.key === selectedId,
      x: zone.x[0] + hash(card.key + ":x") * (zone.x[1] - zone.x[0]),
      z: zone.z[0] + hash(card.key + ":z") * (zone.z[1] - zone.z[0]),
      phase: hash(card.key + ":p") * Math.PI * 2,
    });
  }
  for (let pass = 0; pass < 6; pass++) {
    for (let i = 0; i < plants.length; i++) {
      for (let j = i + 1; j < plants.length; j++) {
        const a = plants[i], b = plants[j];
        const dx = b.x - a.x, dz = b.z - a.z, distance = Math.hypot(dx, dz) || 0.001;
        if (distance < 1.1) {
          const push = (1.1 - distance) / 2, ux = dx / distance, uz = dz / distance;
          a.x -= ux * push; a.z -= uz * push * 0.5; b.x += ux * push; b.z += uz * push * 0.5;
        }
      }
    }
  }
  for (const plant of plants) {           // keep each plant inside its (framed) zone
    const zone = ZONES[plant.stage] || ZONES.growing;
    plant.x = Math.max(zone.x[0] - 0.5, Math.min(zone.x[1] + 0.5, plant.x));
    plant.z = Math.max(zone.z[0] - 0.4, Math.min(zone.z[1] + 0.4, plant.z));
  }
  return plants;
}
