export const MAIN_SETUP_LIMIT = 6;

const CURRENT_WATCH_STATES = new Set(["WATCHING", "DEVELOPING", "CONFIRMING"]);

export function currentWatchSetups(markets) {
  return (markets || []).filter(market => {
    const state = String(market?.state || "WATCHING").toUpperCase();
    const setupLabel = String(market?.setup || "").toLowerCase();
    const hasSetup = Boolean(market?.setup_id || market?.setup_family ||
      (setupLabel && !setupLabel.includes("no setup")));
    return market?.strategy_valid !== true && CURRENT_WATCH_STATES.has(state) && hasSetup;
  });
}

export function visibleSetupEntries(entries, expanded = false) {
  const rows = entries || [];
  return expanded ? rows : rows.slice(0, MAIN_SETUP_LIMIT);
}

export function setupCountSummary(total, expanded = false) {
  if (total <= MAIN_SETUP_LIMIT) return null;
  return expanded
    ? `Showing ${total} of ${total}`
    : `Showing ${MAIN_SETUP_LIMIT} of ${total}`;
}

export function partitionConfirmations(entries) {
  const current = [];
  const historical = [];
  for (const entry of entries || []) {
    (entry?.display?.currentlyConfirmed ? current : historical).push(entry);
  }
  return {current, historical};
}

export function partitionSetupEpisodes(episodes) {
  const rows = Array.isArray(episodes) ? episodes : [];
  const terminal = new Set(["INVALIDATED", "EXPIRED", "RESOLVED"]);
  return {
    current: rows.filter(row => !row?.confirmation &&
      !terminal.has(String(row?.lifecycle_state || "").toUpperCase())),
    confirmed: rows.filter(row => Boolean(row?.confirmation) &&
      !terminal.has(String(row?.lifecycle_state || "").toUpperCase())),
    closed: rows.filter(row => terminal.has(String(row?.lifecycle_state || "").toUpperCase()))
  };
}
