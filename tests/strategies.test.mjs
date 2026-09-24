import test from "node:test";
import assert from "node:assert/strict";
import {
  LEGACY_STRATEGY_ID, filterByStrategy, groupByStrategy, liveGardenRows, normalizeRegistry, strategyConflict,
  strategyFilters, strategyIdOf, strategyMatrix, strategyPerformance, strategyTag,
} from "../src/strategyModel.mjs";
import {archiveEntry, archiveSummary, gardenAreas, gardenCounters, marketOverviewRow, setupCardModel} from "../src/garden/gardenModel.mjs";
import {archivePanel, marketOverview, setupCard, strategyFilterBar, strategyLabPanel, strategyPerformanceBlock} from "../src/garden/gardenCards.mjs";

const TRENDLINE_ONLY = [{strategy_id: "trendline", version: "trendline-first-v3", status: "LIVE"}];
const WITH_SHADOW = [...TRENDLINE_ONLY, {strategy_id: "support_resistance", version: "sr-v0", status: "SHADOW"},
  {strategy_id: "smc", version: "smc-v0", status: "DISABLED"}];
const TWO_LIVE = [...TRENDLINE_ONLY, {strategy_id: "smc", version: "smc-v0", status: "LIVE"}];

const episode = (over = {}) => ({setup_id: "s1", symbol: "XAUUSD", direction: "LONG", lifecycle_state: "DEVELOPING",
  setup_type: "BREAK", score: 70, ...over});
// A trendline episode confirmed as BREAK whose latest snapshot became directional context, then expired.
const confirmedThenContext = (over = {}) => episode({setup_id: "c1", lifecycle_state: "EXPIRED", setup_type: "WATCHING",
  proposed_stop_loss: null, proposed_take_profit: null,
  confirmation: {setup_id: "c1", observation_id: "o1", confirmed_at: "2026-09-24T09:00:00Z", setup_type: "BREAK"},
  closed_event: {occurred_at: "2026-09-24T12:00:00Z", to_state: "EXPIRED", reason_code: "INACTIVITY_TIMEOUT"}, ...over});

test("strategy tags: catalog names, unknown ids and old records", () => {
  assert.deepEqual(["trendline", "support_resistance", "smc", "crt", "ict"].map(id => strategyTag(id).tag),
    ["TRENDLINE", "S/R", "SMC", "CRT", "ICT"]);
  assert.equal(strategyTag("new_thing").tag, "NEW THING");
  assert.equal(strategyIdOf({setup_type: "BREAK"}), LEGACY_STRATEGY_ID, "old record without strategy_id");
  assert.equal(strategyIdOf({strategy_id: "smc"}), "smc");
  const card = setupCardModel(episode());
  assert.equal(card.strategy.tag, "TRENDLINE");
  assert.match(setupCard(card), /class="gd-strategy-tag" data-strategy="trendline"[^>]*>TRENDLINE</);
  assert.equal(setupCardModel(episode({strategy_id: "smc"})).strategy.tag, "SMC");
});

test("strategy filters: only registered strategies are selectable; catalog names are not live", () => {
  const filters = strategyFilters(TRENDLINE_ONLY);
  assert.deepEqual(filters.map(f => f.key), ["all", "trendline", "support_resistance", "smc", "crt", "ict"]);
  assert.deepEqual(filters.filter(f => f.selectable).map(f => f.key), ["all", "trendline"]);
  assert.equal(filters.find(f => f.key === "smc").status, "UNAVAILABLE");
  const bar = strategyFilterBar(filters, "trendline");
  assert.match(bar, /data-strategy-filter="trendline" aria-pressed="true"/);
  assert.match(bar, /data-strategy-filter="smc" aria-pressed="false" disabled/);
  assert.match(bar, /S\/R<small>not live<\/small>/);
  const shadow = strategyFilters(WITH_SHADOW);
  assert.equal(shadow.find(f => f.key === "support_resistance").status, "SHADOW");
  assert.equal(shadow.find(f => f.key === "support_resistance").selectable, true, "shadow results can be reviewed");
  assert.match(strategyFilterBar(shadow), /S\/R<small>shadow<\/small>/);
  // Without registry data only trendline is assumed live.
  assert.deepEqual(normalizeRegistry(null).map(e => [e.id, e.status, e.assumed]), [["trendline", "LIVE", true]]);
  const rows = [episode({setup_id: "a"}), episode({setup_id: "b", strategy_id: "smc"}), episode({setup_id: "c", strategy_id: "trendline"})];
  assert.deepEqual(filterByStrategy(rows, "trendline").map(r => r.setup_id), ["a", "c"]);
  assert.deepEqual(filterByStrategy(rows, "smc").map(r => r.setup_id), ["b"]);
  assert.equal(filterByStrategy(rows, "all").length, 3);
});

test("archive: entries carry strategy_id, filter by strategy and never mix counts", () => {
  const closed = [
    confirmedThenContext(),                                                     // old record: trendline
    episode({setup_id: "t2", lifecycle_state: "INVALIDATED", strategy_id: "trendline"}),
    episode({setup_id: "s1", lifecycle_state: "INVALIDATED", strategy_id: "smc",
      confirmation: {observation_id: "x", setup_type: "OB"}}),
  ];
  const entries = closed.map(row => archiveEntry(row, []));
  assert.deepEqual(entries.map(e => e.strategy_id), ["trendline", "trendline", "smc"]);
  const byStrategy = groupByStrategy(entries);
  assert.deepEqual([...byStrategy.keys()], ["trendline", "smc"]);
  const trendline = archiveSummary(filterByStrategy(entries, "trendline"));
  const smc = archiveSummary(filterByStrategy(entries, "smc"));
  assert.deepEqual([trendline.observed, trendline.confirmed, smc.observed, smc.confirmed], [2, 1, 1, 1]);
  const html = archivePanel(filterByStrategy(entries, "smc"), smc);
  assert.match(html, />SMC</);
  assert.doesNotMatch(html, />TRENDLINE</);
});

test("confirmed episode whose latest snapshot is WATCHING keeps its confirmed identity", () => {
  const row = confirmedThenContext({lifecycle_state: "ACTIVE", closed_event: null});
  const card = setupCardModel(row);
  // Stage comes from the lifecycle state, the setup type from the confirmation event,
  // and the latest observation is reported separately — nothing is merged.
  assert.equal(card.stage, "active");
  assert.equal(card.setupType, "BREAK");
  assert.equal(card.latestObservation, "Directional context");
  assert.match(setupCard(card), /<span>Latest observation<\/span><b>Directional context<\/b>/);
  assert.equal(gardenAreas({confirmed: [row]}, [], {registry: TRENDLINE_ONLY}).bloomed.length, 1, "still a confirmed setup");
  // Closed: in the archive as confirmed, labelled with the confirmed setup type.
  const closed = confirmedThenContext();
  const areas = gardenAreas({closed: [closed]}, [], {registry: TRENDLINE_ONLY});
  assert.deepEqual([areas.bloomed.length, areas.history.length], [0, 1]);
  const entry = archiveEntry(closed, []);
  assert.deepEqual([entry.confirmed, entry.setupType, entry.kind], [true, "BREAK", "pending"]);
  // Unconfirmed context episodes are unchanged: no note, their own type.
  const context = setupCardModel(episode({setup_type: "WATCHING"}));
  assert.deepEqual([context.setupType, context.latestObservation], ["WATCHING", null]);
});

test("shadow, disabled and unknown strategies never appear as live Garden setups", () => {
  const episodes = {
    current: [episode({setup_id: "t"}), episode({setup_id: "sr", strategy_id: "support_resistance"}),
      episode({setup_id: "x", strategy_id: "unknown"})],
    confirmed: [episode({setup_id: "tc", lifecycle_state: "CONFIRMED", confirmation: {observation_id: "o"}}),
      episode({setup_id: "smc", strategy_id: "smc", lifecycle_state: "CONFIRMED", confirmation: {observation_id: "o"}})],
    closed: [episode({setup_id: "srh", strategy_id: "support_resistance", lifecycle_state: "EXPIRED"})],
  };
  const areas = gardenAreas(episodes, [], {registry: WITH_SHADOW});
  assert.deepEqual(areas.growing.map(r => r.setup_id), ["t"]);
  assert.deepEqual(areas.bloomed.map(r => r.setup_id), ["tc"]);
  assert.deepEqual(areas.history.map(r => r.setup_id), ["srh"], "recorded history stays visible");
  assert.deepEqual(liveGardenRows(episodes.current, null).map(r => r.setup_id), ["t"], "offline: trendline only");
  const counters = gardenCounters({episodes, registry: WITH_SHADOW});
  assert.deepEqual([counters.growing, counters.bloomed], [1, 1]);
  // Once a strategy is LIVE its setups do appear.
  assert.deepEqual(gardenAreas(episodes, [], {registry: TWO_LIVE}).bloomed.map(r => r.setup_id).sort(), ["smc", "tc"]);
  assert.match(strategyLabPanel(WITH_SHADOW), /Shadow mode · review only/);
  assert.match(strategyLabPanel(WITH_SHADOW), /never appear as Garden setups/);
  assert.match(strategyLabPanel(TRENDLINE_ONLY), /No shadow-mode strategies are registered/);
});

test("markets[i].strategies[] propagates; conflicts need two live strategies disagreeing", () => {
  const market = {symbol: "XAUUSD", state: "CONFIRMING", direction: "LONG", strategy_valid: true, setup_id: "t1",
    strategies: [{strategy_id: "trendline", status: "OK", state: "CONFIRMING", direction: "LONG", confirmed: true, setup_id: "t1"}]};
  assert.deepEqual(strategyMatrix(market, TRENDLINE_ONLY).map(e => [e.tag, e.direction, e.setupId, e.live]), [["TRENDLINE", "LONG", "t1", true]]);
  assert.equal(strategyConflict(market, TRENDLINE_ONLY), null, "no artificial conflict with one strategy");
  // An engine without strategies[] still maps the market to its trendline result.
  assert.deepEqual(strategyMatrix({state: "DEVELOPING", direction: "SHORT"}, null).map(e => [e.id, e.direction]), [["trendline", "SHORT"]]);
  const disagreeing = {...market, strategies: [...market.strategies,
    {strategy_id: "smc", status: "OK", state: "DEVELOPING", direction: "SHORT", confirmed: false, setup_id: "m1"}]};
  const conflict = strategyConflict(disagreeing, TWO_LIVE);
  assert.deepEqual(conflict.sides.map(s => [s.tag, s.direction]), [["TRENDLINE", "LONG"], ["SMC", "SHORT"]]);
  assert.equal(strategyConflict(disagreeing, WITH_SHADOW), null, "a non-live strategy cannot create a conflict");
  const failing = {...market, strategies: [...market.strategies, {strategy_id: "smc", status: "ERROR"}]};
  assert.equal(strategyConflict(failing, TWO_LIVE), null);
  const html = marketOverview([marketOverviewRow(disagreeing, TWO_LIVE)]);
  assert.match(html, /gd-market-row has-conflict/);
  assert.match(html, /Strategy conflict/);
  assert.match(html, /TRENDLINE ▲ BUY/);
  assert.match(html, /SMC ▼ SELL/);
  const single = marketOverview([marketOverviewRow(market, TRENDLINE_ONLY)]);
  assert.doesNotMatch(single, /gd-market-matrix|Strategy conflict/, "no extra metadata with one strategy");
});

test("per-strategy performance passes backend counts through and never mixes strategies", () => {
  const report = {primary_horizon: "4h", daily: [{primary_horizon: "4h", by_horizon: {"4h": {win: 3, loss: 2}},
    by_strategy: {trendline: {win: 2, loss: 1, pending: 4, no_hit: 0, ambiguous: 1}, smc: {win: 1, loss: 1, pending: 0, no_hit: 2, ambiguous: 0}}}]};
  const trendline = strategyPerformance(report, "trendline");
  assert.deepEqual([trendline.win, trendline.loss, trendline.pending, trendline.noHit, trendline.ambiguous], [2, 1, 4, 0, 1]);
  assert.deepEqual([strategyPerformance(report, "smc").win, strategyPerformance(report, "smc").noHit], [1, 2]);
  assert.equal(strategyPerformance(report, "crt"), null, "no data is shown as none, not zero");
  assert.equal("winRate" in trendline, false, "no statistic the backend did not produce");
  const html = strategyPerformanceBlock(trendline, strategyTag("trendline"));
  assert.match(html, /2W \/ 1L/);
  assert.doesNotMatch(html, /SMC|%/);
  assert.match(strategyPerformanceBlock(null, strategyTag("crt")), /No confirmed Candle Range Theory setups/);
});
