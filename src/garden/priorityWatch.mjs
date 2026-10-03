// TRADeden Priority Watch: which markets deserve attention right now.
// Pure functions only (no DOM), unit-tested.
//
// This is an ATTENTION ORDER, never a trade prediction. It reads only facts the
// engine already returned: lifecycle states and their event times, the engine's
// own setup scores and each live strategy's direction. Nothing is estimated.
//
// Two separate ideas:
//   lifecycle  = what a setup IS (Active stays Active for as long as it is active);
//   freshness  = how long ago something meaningful HAPPENED on the market.
// Freshness only changes the ORDER; it never changes a lifecycle.
//
// Order (see attentionGroup):
//   1. current setups (Detected..Active) with a meaningful event in the last hour
//   2. current setups whose latest meaningful event was 1-4 hours ago
//   3. current setups with older (or unknown) events: still shown, never hidden
//   4. watching markets   5. recently closed markets   6. no setup
// Within a group: lifecycle tier, then freshness band, then the engine's setup
// score, then strategy agreement, then event recency, then symbol (deterministic).
// Core status never changes this order.
import {gardenStage} from "./gardenModel.mjs";
import {strategyIdOf, strategyMatrix, strategyTag} from "../strategyModel.mjs";

export const PRIORITY_TIERS = Object.freeze({
  CONFIRMED: 6, ACTIVE: 6,
  CONFIRMING: 5,
  DEVELOPING: 4,
  DETECTED: 3,
  WATCHING: 2,
  INVALIDATED: 1, EXPIRED: 1, RESOLVED: 1,
});
export const MEANINGFUL_TIER = PRIORITY_TIERS.DETECTED;     // a current setup exists
const CLOSED = new Set(["INVALIDATED", "EXPIRED", "RESOLVED"]);

/**
 * Markets TRADeden keeps visible regularly. Core means "we always care about this
 * market", NOT "this is a better trade": it never outranks a stronger setup.
 * US100 and NAS100 are aliases for the same index; whichever the broker uses counts.
 */
export const CORE_MARKETS = Object.freeze(["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US100", "US500", "GER40", "XAGUSD", "ETHUSD"]);
const CORE_SET = new Set(CORE_MARKETS);
const normalize = symbol => String(symbol || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
export const isCoreMarket = symbol => CORE_SET.has(normalize(symbol));

/** Familiar names shown beside the symbol (the symbol stays the data identity). */
export const MARKET_NAMES = Object.freeze({
  XAUUSD: "Gold", XAGUSD: "Silver", BTCUSD: "Bitcoin", ETHUSD: "Ethereum",
  NAS100: "Nasdaq 100", US100: "Nasdaq 100", US500: "S&P 500", US30: "Dow 30", GER40: "DAX 40", UK100: "FTSE 100", JPN225: "Nikkei 225",
});
export const marketName = symbol => MARKET_NAMES[normalize(symbol)] || null;

const upper = value => String(value ?? "").trim().toUpperCase();
const numberOrNull = value => value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
const timeOf = value => { const t = value ? Date.parse(value) : NaN; return Number.isFinite(t) ? t : null; };
const directionOf = value => { const v = upper(value); return v === "LONG" || v === "SHORT" ? v : null; };
const latest = times => times.reduce((best, t) => (t != null && (best == null || t > best) ? t : best), null);

// ----- attention freshness ---------------------------------------------------------
const MINUTE = 60 * 1000;
/** Age limits of each band. STALE also covers "no event time is known". */
export const FRESHNESS = Object.freeze([
  {key: "very-fresh", label: "Very fresh", maxAge: 15 * MINUTE, rank: 3},
  {key: "fresh", label: "Fresh", maxAge: 60 * MINUTE, rank: 2},
  {key: "recent", label: "Recent", maxAge: 4 * 60 * MINUTE, rank: 1},
  {key: "stale", label: "Stale", maxAge: Infinity, rank: 0},
]);
export function freshnessOf(eventTime, now = Date.now()) {
  if (eventTime == null) return FRESHNESS[3];
  const age = Math.max(0, now - eventTime);
  return FRESHNESS.find(band => age < band.maxAge);
}

/**
 * The latest MEANINGFUL event of a recorded episode: its lifecycle transitions,
 * detection, confirmation and closing. Deliberately not `observed_at`, which moves
 * on every scan (price updates must not keep resetting attention).
 */
export function episodeEventTime(row) {
  const events = Array.isArray(row?.lifecycle_events) ? row.lifecycle_events.map(event => timeOf(event?.occurred_at)) : [];
  return latest([...events, timeOf(row?.detected_at), timeOf(row?.confirmation?.confirmed_at), timeOf(row?.confirmation_time), timeOf(row?.closed_event?.occurred_at)]);
}

/**
 * Live strategy scans carry no timestamps, so the Garden notes when a strategy's
 * scan state, direction or setup id CHANGES while it is open. A state already
 * present on the first scan gets no time (it is not known when it began).
 * Score movements are not events, and a change must hold for two consecutive scans
 * before it counts (a one-scan flicker never resets attention); it is then dated to
 * the scan where it first appeared.
 * Returns the next memory: key -> {signature, since, pending}.
 */
export function trackScanEvents(previous, markets = [], registry = null, now = Date.now()) {
  const next = new Map();
  for (const market of markets) {
    if (!market?.symbol) continue;
    for (const entry of strategyMatrix(market, registry)) {
      if (!entry.live) continue;
      const key = market.symbol + "|" + entry.id;
      const signature = [entry.confirmed ? "CONFIRMED" : entry.state, entry.direction, entry.setupId].join("|");
      const before = previous?.get(key);
      if (!previous) next.set(key, {signature, since: null, pending: null});
      else if (!before) next.set(key, {signature: null, since: null, pending: {signature, at: now}});
      else if (before.signature === signature) next.set(key, {...before, pending: null});
      else if (before.pending?.signature === signature) next.set(key, {signature, since: before.pending.at, pending: null});
      else next.set(key, {...before, pending: {signature, at: now}});
    }
  }
  return next;
}

/** One market's reads: its live setups (episodes) and each live strategy's current scan. */
function marketReads(market, liveRows, registry, recorded, scanEvents) {
  const reads = [];
  for (const row of liveRows) {
    if (row?.symbol !== market.symbol) continue;
    const state = upper(row.lifecycle_state || row.state);
    reads.push({state, tier: PRIORITY_TIERS[state] ?? 0, strategy: strategyIdOf(row), direction: directionOf(row.direction),
      score: numberOrNull(row.confirmed_plan?.score ?? row.score), time: episodeEventTime(row), key: row.setup_id || null, source: "setup"});
  }
  for (const entry of strategyMatrix(market, registry)) {
    if (!entry.live || entry.status === "ERROR") continue;
    // A scan result for a setup with a recorded episode: the recorded lifecycle is
    // authoritative (a live episode is already read above; a closed one no longer counts).
    if (entry.setupId && recorded.has(entry.setupId)) continue;
    const state = entry.confirmed ? "CONFIRMED" : upper(entry.state);
    reads.push({state, tier: PRIORITY_TIERS[state] ?? 0, strategy: entry.id, direction: entry.direction, score: entry.score ?? null,
      time: scanEvents?.get(market.symbol + "|" + entry.id)?.since ?? null, key: entry.setupId || null, source: "scan"});
  }
  // The market's own latest episode state (a closed setup ranks low, but above "nothing").
  const own = upper(market.lifecycle_state);
  if (CLOSED.has(own)) reads.push({state: own, tier: PRIORITY_TIERS[own], strategy: strategyIdOf(market), direction: directionOf(market.direction),
    score: numberOrNull(market.score), time: episodeEventTime(recorded.get(market.setup_id)), key: market.setup_id || null, source: "market"});
  return reads;
}

const byStrength = (a, b) => b.tier - a.tier || (b.score ?? -1) - (a.score ?? -1) || (b.time ?? 0) - (a.time ?? 0);

/** Attention group of an entry (higher first); see the header comment. */
export function attentionGroup(tier, freshness) {
  if (tier >= MEANINGFUL_TIER) return freshness.rank >= 2 ? 6 : freshness.rank === 1 ? 5 : 4;
  if (tier === PRIORITY_TIERS.WATCHING) return 3;
  if (tier > 0) return 2;
  return 1;
}

/**
 * Attention entry for one market. `lead` is the read with the most advanced
 * lifecycle; the displayed lifecycle, direction and score are its own recorded
 * values. Freshness is the market's latest meaningful event (a current setup's
 * event when there is one), which only affects the order.
 */
export function priorityEntry(market, liveRows = [], registry = null, {recorded = new Map(), scanEvents = null, now = Date.now()} = {}) {
  const reads = marketReads(market, liveRows, registry, recorded, scanEvents).sort(byStrength);
  // Without a current setup, a market whose latest setup just closed ranks as closed:
  // the scanner going back to WATCHING does not hide an invalidation or expiry.
  const closedRead = reads.find(read => read.source === "market");
  const lead = (reads[0]?.tier ?? 0) < MEANINGFUL_TIER && closedRead ? closedRead : reads[0] || null;
  const tier = lead?.tier ?? 0;
  const direction = lead?.direction || (tier >= MEANINGFUL_TIER ? null : directionOf(market.direction));
  // Strategy agreement: distinct live strategies currently pointing the lead's way.
  const pointing = side => new Set(reads.filter(read => read.direction === side && read.tier >= PRIORITY_TIERS.WATCHING).map(read => read.strategy));
  const agreement = direction ? pointing(direction).size : 0;
  const opposite = direction ? pointing(direction === "LONG" ? "SHORT" : "LONG").size : 0;
  // One signal per live strategy: its strongest read.
  const signals = [];
  for (const read of reads) {
    if (read.source === "market" || signals.some(signal => signal.strategy === read.strategy)) continue;
    signals.push({strategy: read.strategy, tag: strategyTag(read.strategy).tag, direction: read.direction, state: read.state || null});
  }
  const eventTime = tier >= MEANINGFUL_TIER ? latest(reads.filter(read => read.tier >= MEANINGFUL_TIER).map(read => read.time)) : lead?.time ?? null;
  const freshness = freshnessOf(eventTime, now);
  const move = numberOrNull(market.change_pct);
  return {
    symbol: market.symbol, name: marketName(market.symbol), core: isCoreMarket(market.symbol),
    tier, lifecycle: lead?.state || null, stage: lead && lead.tier >= MEANINGFUL_TIER ? gardenStage({lifecycle_state: lead.state}) : null,
    direction, score: lead?.score ?? numberOrNull(market.score), agreement, conflict: opposite > 0 && agreement > 0,
    eventTime, freshness: freshness.key, freshnessRank: freshness.rank, ageMs: eventTime == null ? null : Math.max(0, now - eventTime),
    group: attentionGroup(tier, freshness),
    leadStrategy: lead?.strategy || null, leadKey: lead?.key || null,
    // Where the displayed state comes from: a recorded lifecycle (an episode) or a live
    // strategy scan with no recorded episode yet. Presentation only; ranking ignores it.
    basis: !lead ? null : lead.source === "scan" ? "scan" : "recorded",
    signals, price: numberOrNull(market.price), change: move,
  };
}

/** Deterministic attention order over every scanned market. */
export function comparePriority(a, b) {
  return b.group - a.group
    || b.tier - a.tier
    || b.freshnessRank - a.freshnessRank
    || (b.score ?? -1) - (a.score ?? -1)
    || b.agreement - a.agreement
    || (b.eventTime ?? 0) - (a.eventTime ?? 0)
    || String(a.symbol).localeCompare(String(b.symbol));
}
/**
 * `liveRows`: the Garden's live setups (current + confirmed, live strategies only).
 * `episodes`: every recorded episode (any bucket): recognises setups whose lifecycle
 * is recorded (so a scan state never overrides it) and dates closed setups.
 * `scanEvents`: trackScanEvents memory. `now`: the clock (injectable for tests).
 */
export function rankMarkets(markets = [], liveRows = [], registry = null, {episodes = [], scanEvents = null, now = Date.now()} = {}) {
  const recorded = new Map([...episodes, ...liveRows].filter(row => row?.setup_id).map(row => [row.setup_id, row]));
  return markets.filter(market => market?.symbol).map(market => priorityEntry(market, liveRows, registry, {recorded, scanEvents, now})).sort(comparePriority);
}

/**
 * The four visible slots: the three highest-priority markets (core markets compete
 * normally), then the strongest core market not already shown. Without such a core
 * market the fourth slot goes to the next market in the order. No symbol twice.
 */
export function priorityWatchSlots(ranked, size = 4) {
  const priority = ranked.slice(0, Math.max(0, size - 1));
  const shown = new Set(priority.map(entry => entry.symbol));
  const core = ranked.find(entry => entry.core && !shown.has(entry.symbol)) || null;
  if (!core) {
    const next = ranked.find(entry => !shown.has(entry.symbol));
    if (next) priority.push(next);
  }
  return {priority, core};
}

/**
 * The full Market Watch (View all), grouped over the same ranking:
 * top priority = the top 3 ranked markets (the compact panel's priority slots);
 * core = core markets not already in the top 3; recently closed = markets whose
 * latest setup was invalidated/expired; other = everything else. Each market once.
 */
export function marketWatchGroups(ranked, top = 3) {
  const groups = {priority: ranked.slice(0, top), core: [], other: [], closed: []};
  for (const entry of ranked.slice(top)) {
    if (entry.core) groups.core.push(entry);
    else if (entry.tier === PRIORITY_TIERS.INVALIDATED) groups.closed.push(entry);
    else groups.other.push(entry);
  }
  return groups;
}
