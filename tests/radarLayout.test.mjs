import test from "node:test";
import assert from "node:assert/strict";
import {
  MAIN_SETUP_LIMIT,
  currentWatchSetups,
  partitionConfirmations,
  partitionSetupEpisodes,
  setupCountSummary,
  visibleSetupEntries,
} from "../src/radarLayout.mjs";

test("main setup grids show six entries by default and retain the rest for expansion", () => {
  const entries = Array.from({length: 9}, (_, index) => ({setup_id: `setup-${index}`}));

  assert.equal(MAIN_SETUP_LIMIT, 6);
  assert.equal(visibleSetupEntries(entries).length, 6);
  assert.equal(setupCountSummary(entries.length), "Showing 6 of 9");
  assert.equal(visibleSetupEntries(entries, true).length, 9);
  assert.equal(setupCountSummary(entries.length, true), "Showing 9 of 9");
  assert.equal(setupCountSummary(6), null);
});

test("WATCH candidates exclude confirmed, inactive, and no-setup markets", () => {
  const markets = [
    {symbol: "EURUSD", setup_id: "watch-1", state: "WATCHING", strategy_valid: false},
    {symbol: "GBPUSD", setup_id: "confirmed", state: "CONFIRMING", strategy_valid: true},
    {symbol: "USDJPY", setup_id: "inactive", state: "INVALIDATED", strategy_valid: false},
    {symbol: "XAUUSD", setup: "No setup", state: "WATCHING", strategy_valid: false},
    {symbol: "AUDUSD", setup_family: "TRENDLINE_BREAK", state: "DEVELOPING", strategy_valid: false},
  ];

  assert.deepEqual(currentWatchSetups(markets).map(market => market.symbol), ["EURUSD", "AUDUSD"]);
});

test("historical confirmation events never enter the current-confirmed grid", () => {
  const current = {event: {setup_id: "current"}, display: {currentlyConfirmed: true}};
  const historical = {event: {setup_id: "historical"}, display: {currentlyConfirmed: false}};
  const result = partitionConfirmations([historical, current]);

  assert.deepEqual(result.current, [current]);
  assert.deepEqual(result.historical, [historical]);
});

test("persistent setup episodes partition into current, confirmed, and closed buckets", () => {
  const rows = [
    {setup_id: "detected", lifecycle_state: "DETECTED"},
    {setup_id: "confirmed", lifecycle_state: "CONFIRMED", confirmation: {confirmed_at: "t"}},
    {setup_id: "active", lifecycle_state: "ACTIVE", confirmation: {confirmed_at: "t"}},
    {setup_id: "invalid", lifecycle_state: "INVALIDATED"},
    {setup_id: "expired", lifecycle_state: "EXPIRED"},
  ];
  const buckets = partitionSetupEpisodes(rows);
  assert.deepEqual(buckets.current.map(row => row.setup_id), ["detected"]);
  assert.deepEqual(buckets.confirmed.map(row => row.setup_id), ["confirmed", "active"]);
  assert.deepEqual(buckets.closed.map(row => row.setup_id), ["invalid", "expired"]);
});
