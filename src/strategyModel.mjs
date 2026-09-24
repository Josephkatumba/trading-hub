// Strategy identity for the TRADeden UI. Pure functions only (no DOM), unit-tested.
//
// The backend registry is authoritative: only strategies it reports as LIVE
// produce live results. Everything else in the catalog is a name the UI can
// display and filter on, never a source of setups. Records without strategy_id
// were all written by the trendline engine (backend read-time mapping).

export const LEGACY_STRATEGY_ID = "trendline";

// Display names for strategies the platform plans to support. Being listed here
// does NOT make a strategy active; the registry decides that.
export const STRATEGY_CATALOG = Object.freeze({
  trendline: Object.freeze({id: "trendline", tag: "TRENDLINE", label: "Trendline"}),
  support_resistance: Object.freeze({id: "support_resistance", tag: "S/R", label: "Support & Resistance"}),
  smc: Object.freeze({id: "smc", tag: "SMC", label: "Smart Money Concepts"}),
  crt: Object.freeze({id: "crt", tag: "CRT", label: "Candle Range Theory"}),
  ict: Object.freeze({id: "ict", tag: "ICT", label: "ICT"}),
});
export const STRATEGY_STATUS = Object.freeze({
  LIVE: "Live",
  SHADOW: "Shadow mode · review only",
  DISABLED: "Registered · disabled",
  UNAVAILABLE: "Not available yet",
});

/** The strategy a market, episode, confirmation or archive row belongs to. */
export function strategyIdOf(row) {
  const value = row?.strategy_id;
  return value ? String(value) : LEGACY_STRATEGY_ID;
}

export function strategyTag(id) {
  const key = String(id || LEGACY_STRATEGY_ID);
  return STRATEGY_CATALOG[key] || {id: key, tag: key.toUpperCase().replace(/_/g, " "), label: key};
}

/**
 * Registry entries from the API (`strategy_registry` / `/api/market/strategies`).
 * Without registry data (engine offline or older engine), only the trendline
 * strategy is assumed live — the only strategy that has ever produced setups.
 */
export function normalizeRegistry(list) {
  if (!Array.isArray(list) || !list.length) {
    return [{id: LEGACY_STRATEGY_ID, version: null, status: "LIVE", assumed: true}];
  }
  return list.filter(item => item?.strategy_id).map(item => ({
    id: String(item.strategy_id),
    version: item.version || null,
    status: ["LIVE", "SHADOW", "DISABLED"].includes(String(item.status).toUpperCase()) ? String(item.status).toUpperCase() : "DISABLED",
    assumed: false,
  }));
}

export function liveStrategyIds(registry) {
  return new Set(normalizeRegistry(registry).filter(item => item.status === "LIVE").map(item => item.id));
}

/** Registry status for any strategy id, including catalog names that are not registered. */
export function strategyStatus(id, registry) {
  return normalizeRegistry(registry).find(item => item.id === id)?.status || "UNAVAILABLE";
}

/**
 * Filter options: "All", every catalog strategy, and any other registered id.
 * `selectable` is false for strategies with nothing to show (not registered).
 */
export function strategyFilters(registry) {
  const entries = normalizeRegistry(registry);
  const ids = [...Object.keys(STRATEGY_CATALOG), ...entries.map(item => item.id).filter(id => !STRATEGY_CATALOG[id])];
  return [{key: "all", tag: "ALL", label: "All strategies", status: "LIVE", selectable: true},
    ...ids.map(id => {
      const status = entries.find(item => item.id === id)?.status || "UNAVAILABLE";
      const {tag, label} = strategyTag(id);
      return {key: id, tag, label, status, selectable: status !== "UNAVAILABLE"};
    })];
}

export function matchesStrategy(row, filter) {
  return !filter || filter === "all" || strategyIdOf(row) === filter;
}

export function filterByStrategy(rows, filter) {
  return (rows || []).filter(row => matchesStrategy(row, filter));
}

/**
 * Rows allowed in the live Garden (growing / bloomed): only setups of LIVE
 * strategies. Shadow, disabled or unknown strategies never appear as live setups.
 */
export function liveGardenRows(rows, registry) {
  const live = liveStrategyIds(registry);
  return (rows || []).filter(row => live.has(strategyIdOf(row)));
}

const ACTIONABLE = new Set(["DEVELOPING", "CONFIRMING"]);

/**
 * Per-strategy results for one market (`markets[i].strategies[]`). A market from
 * an engine without that field is its trendline result.
 */
export function strategyMatrix(market, registry) {
  const entries = Array.isArray(market?.strategies) ? market.strategies
    : market ? [{strategy_id: LEGACY_STRATEGY_ID, status: "OK", state: market.state, direction: market.direction,
      confirmed: market.strategy_valid === true, setup_family: market.setup_family, setup_id: market.setup_id}] : [];
  return entries.map(entry => {
    const id = strategyIdOf(entry);
    const direction = ["LONG", "SHORT"].includes(String(entry.direction || "").toUpperCase()) ? String(entry.direction).toUpperCase() : null;
    const mode = strategyStatus(id, registry);
    return {...strategyTag(id), status: entry.status === "ERROR" ? "ERROR" : "OK", live: mode === "LIVE",
      mode: mode === "UNAVAILABLE" ? String(entry.mode || "LIVE").toUpperCase() : mode,
      state: entry.state ? String(entry.state).toUpperCase() : null, direction, confirmed: entry.confirmed === true,
      setupFamily: entry.setup_family || null, setupId: entry.setup_id || null};
  });
}

/**
 * A strategy conflict: two LIVE strategies with a developing/confirming (or
 * confirmed) setup in opposite directions on the same market. Shown side by
 * side; neither result is suppressed. null when there is no disagreement.
 */
export function strategyConflict(market, registry) {
  const sides = strategyMatrix(market, registry).filter(entry =>
    entry.live && entry.status === "OK" && entry.direction && (entry.confirmed || ACTIONABLE.has(entry.state)));
  const directions = new Set(sides.map(entry => entry.direction));
  if (directions.size < 2) return null;
  return {symbol: market?.symbol || null, sides: sides.map(({id, tag, label, direction, confirmed, state}) => ({id, tag, label, direction, confirmed, state}))};
}

/**
 * Per-strategy performance from the backend's `by_strategy` groups (4h primary
 * horizon, verified MarketOutcome labels only). Counts are passed through, never
 * derived; null when the report has no group for this strategy.
 */
export function strategyPerformance(report, strategyId) {
  const day = report?.daily?.[0] || report?.summary || null;
  const group = day?.by_strategy?.[strategyId];
  if (!group) return null;
  const count = key => Number(group[key] || 0);
  return {strategyId, ...strategyTag(strategyId), horizon: report?.primary_horizon || day?.primary_horizon || "4h",
    win: count("win"), loss: count("loss"), pending: count("pending"), noHit: count("no_hit"), ambiguous: count("ambiguous")};
}

/**
 * Current results of SHADOW strategies across markets, for the Strategy Lab
 * only (never the Garden). One row per market and shadow strategy.
 */
export function shadowResults(markets, registry) {
  const rows = [];
  for (const market of markets || []) {
    for (const entry of strategyMatrix(market, registry)) {
      if (entry.mode !== "SHADOW") continue;
      rows.push({symbol: market?.symbol || "Unknown", strategy: entry.id, tag: entry.tag, status: entry.status,
        state: entry.state, direction: entry.direction, confirmed: entry.confirmed, setupFamily: entry.setupFamily});
    }
  }
  const order = {CONFIRMING: 0, DEVELOPING: 1, WATCHING: 2};
  return rows.sort((a, b) => (Number(b.confirmed) - Number(a.confirmed)) || ((order[a.state] ?? 9) - (order[b.state] ?? 9)) || a.symbol.localeCompare(b.symbol));
}

/** Group any rows by strategy id (e.g. archive entries); insertion order is first appearance. */
export function groupByStrategy(rows) {
  const groups = new Map();
  for (const row of rows || []) {
    const id = strategyIdOf(row);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(row);
  }
  return groups;
}
