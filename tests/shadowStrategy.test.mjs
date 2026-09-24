import test from "node:test";
import assert from "node:assert/strict";
import {createConfirmationAlertTracker, persistedConfirmationEvents} from "../src/confirmationAlerts.mjs";
import {liveGardenRows, shadowResults, strategyConflict, strategyMatrix} from "../src/strategyModel.mjs";
import {gardenAreas, gardenCounters, marketOverviewRow} from "../src/garden/gardenModel.mjs";
import {marketOverview, strategyLabPanel, strategyPerformanceBlock} from "../src/garden/gardenCards.mjs";
import {strategyPerformance, strategyTag} from "../src/strategyModel.mjs";

// The registry as the Phase 6 engine reports it.
const REGISTRY = [{strategy_id: "trendline", version: "trendline-first-v3", status: "LIVE"},
  {strategy_id: "support_resistance", version: "sr-levels-v1", status: "SHADOW"}];
const market = (srDirection, srConfirmed = false) => ({symbol: "XAUUSD", state: "DEVELOPING", direction: "LONG", setup_id: "t1",
  strategies: [{strategy_id: "trendline", mode: "LIVE", status: "OK", state: "DEVELOPING", direction: "LONG", confirmed: false, setup_id: "t1"},
    {strategy_id: "support_resistance", mode: "SHADOW", status: "OK", state: "CONFIRMING", direction: srDirection, confirmed: srConfirmed,
      setup_family: "SR_BOUNCE", setup_id: "s1"}]});

test("shadow confirmations never become live confirmation alerts", () => {
  const performance = {daily: [{setups: [
    {setup_id: "t1", confirmation_event_id: "c1", confirmed_at: "2026-09-24T12:00:00Z", strategy_id: "trendline"},
    {setup_id: "s1", confirmation_event_id: "c2", confirmed_at: "2026-09-24T12:00:00Z", strategy_id: "support_resistance", shadow: true}]}]};
  assert.deepEqual(persistedConfirmationEvents(performance).map(e => e.setup_id), ["t1"]);
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-24T00:00:00Z")});
  assert.deepEqual(tracker.observe(performance.daily[0].setups).map(e => e.setup_id), ["t1"]);
});

test("shadow S/R setups never appear in the Garden, counters or market rows", () => {
  const episodes = {current: [{setup_id: "s1", strategy_id: "support_resistance", lifecycle_state: "DEVELOPING", shadow: true}],
    confirmed: [{setup_id: "s2", strategy_id: "support_resistance", lifecycle_state: "CONFIRMED", confirmation: {}, shadow: true},
      {setup_id: "t2", strategy_id: "trendline", lifecycle_state: "CONFIRMED", confirmation: {}}]};
  const areas = gardenAreas(episodes, [], {registry: REGISTRY});
  assert.deepEqual([...areas.growing, ...areas.bloomed].map(r => r.setup_id), ["t2"]);
  assert.deepEqual(gardenCounters({episodes, registry: REGISTRY}).bloomed, 1);
  assert.deepEqual(liveGardenRows(episodes.current, REGISTRY), []);
  const html = marketOverview([marketOverviewRow(market("SHORT", true), REGISTRY)]);
  assert.doesNotMatch(html, /S\/R|gd-market-matrix|Strategy conflict/, "shadow results are not shown on the Garden page");
});

test("trendline and S/R may disagree; a shadow strategy never creates a live conflict", () => {
  const matrix = strategyMatrix(market("SHORT"), REGISTRY);
  assert.deepEqual(matrix.map(e => [e.tag, e.mode, e.direction, e.live]), [["TRENDLINE", "LIVE", "LONG", true], ["S/R", "SHADOW", "SHORT", false]]);
  assert.equal(strategyConflict(market("SHORT"), REGISTRY), null);
  // Were S/R ever made LIVE, the same disagreement would be shown as a conflict, not suppressed.
  const live = REGISTRY.map(e => ({...e, status: "LIVE"}));
  assert.deepEqual(strategyConflict(market("SHORT"), live).sides.map(s => s.direction), ["LONG", "SHORT"]);
});

test("the Strategy Lab lists shadow results with a SHADOW label and research-only statistics", () => {
  const markets = [market("SHORT", true), {...market("LONG"), symbol: "EURUSD"}, {symbol: "GER40", strategies: [{strategy_id: "trendline", status: "OK"},
    {strategy_id: "support_resistance", mode: "SHADOW", status: "ERROR"}]}];
  assert.deepEqual(shadowResults(markets, REGISTRY).map(r => [r.symbol, r.direction, r.confirmed]),
    [["XAUUSD", "SHORT", true], ["EURUSD", "LONG", false], ["GER40", null, false]]);
  const performance = {primary_horizon: "4h", daily: [{by_strategy: {support_resistance: {win: 2, loss: 1, pending: 3, no_hit: 0, ambiguous: 0}}}]};
  const html = strategyLabPanel(REGISTRY, {markets, performance});
  assert.match(html, /gd-shadow-badge">SHADOW</);
  assert.match(html, /Not live setups, not alerts, not trade signals/);
  assert.match(html, /<th>XAUUSD<\/th><td>S\/R<\/td><td>CONFIRMING<\/td><td>SHORT<\/td><td>yes<\/td>/);
  assert.match(html, /S\/R research, 4h market outcome:<\/b> 2 target first · 1 stop first · 3 pending/);
  assert.match(html, /<th>GER40<\/th><td>S\/R<\/td><td>unavailable/);
  const block = strategyPerformanceBlock(strategyPerformance(performance, "support_resistance"), strategyTag("support_resistance"), {shadow: true});
  assert.match(block, /Research only: this strategy runs in shadow mode/);
  assert.match(strategyLabPanel([REGISTRY[0]]), /No shadow-mode strategies are registered/);
});
