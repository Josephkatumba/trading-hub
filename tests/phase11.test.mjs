// Phase 11: confirmed-plan integrity, risk visualization, lifecycle rail, strategy identity,
// the compact header, strategy sectors and the evaluation views. Pure functions only.
import test from "node:test";
import assert from "node:assert/strict";
import {analystModel, archiveEntry, constellationLayout, gardenAreas, gardenCounters, gardenHeaderModel, lifecycleRail,
  riskModel, sectorAngle, setupCardModel, tradeLevels} from "../src/garden/gardenModel.mjs";
import {analystPanel, evaluationPanel, evidenceBubbles, gardenHeader, riskBar, setupCard, strategyFilterBar} from "../src/garden/gardenCards.mjs";
import {filterByStrategy, strategyFilters} from "../src/strategyModel.mjs";

const REGISTRY = [{strategy_id: "trendline", version: "trendline-first-v4", status: "LIVE"},
  {strategy_id: "support_resistance", version: "sr-levels-v1", status: "LIVE"},
  {strategy_id: "trend_momentum", version: "tm-pullback-v2", status: "LIVE"}];

// The real XAUUSD case: confirmed at 4265.00 / 4293.06 / 4185.45 (1:2.84); the latest
// observation drifted to entry 4291.72 with a 1:79 plan while the setup was active.
const confirmedPlan = {observation_id: "obs_c", entry: 4265.0, stop_loss: 4293.058571428572, take_profit: 4185.45, rr: 2.84,
  risk_distance: 28.058571428571668, reward_distance: 79.55, invalidation_price: 4293.058571428572, reference_price: 4265.025,
  score: 78, reason: "M15 continuation after a controlled pullback; all confirmation rules passed.", strategy_version: "tm-pullback-v1"};
const xau = (over = {}) => ({setup_id: "stp_x", observation_id: "obs_latest", symbol: "XAUUSD", direction: "SHORT", strategy_id: "trend_momentum",
  strategy_version: "tm-pullback-v1", lifecycle_state: "ACTIVE", score: 40, timeframe: "M15", setup_type: "TM_PULLBACK_CONTINUATION",
  proposed_entry: 4291.72, proposed_stop_loss: 4293.058571428572, proposed_take_profit: 4185.45, features: {rr: 79.02, risk_distance: 1.34, reward_distance: 106.27},
  rule_evidence: {reason: "Controlled pullback; not confirmed: resumption, stop_ok."},
  confirmation: {observation_id: "obs_c", confirmed_at: "2026-09-25T00:00:00Z", strategy_version: "tm-pullback-v1"},
  confirmed_plan: confirmedPlan,
  lifecycle_events: [{to_state: "DEVELOPING", occurred_at: "2026-09-24T21:11:04Z"}, {to_state: "CONFIRMED", occurred_at: "2026-09-25T00:00:00Z"},
    {to_state: "ACTIVE", occurred_at: "2026-09-25T00:00:10Z"}], ...over});

test("a confirmed setup shows its confirmed plan, never the latest drifting observation", () => {
  const levels = tradeLevels(xau());
  assert.equal(levels.basis, "confirmation");
  assert.deepEqual([levels.entry, levels.stop, levels.target, levels.rr], ["4,265.00", "4,293.06", "4,185.45", "1:2.84"]);
  const card = setupCardModel(xau());
  assert.equal(card.score, 78, "the score it was confirmed with");
  assert.equal(card.why, "M15 continuation after a controlled pullback. All confirmation rules passed.");
  assert.equal(card.planDrift, true);
  assert.equal(card.strategyVersion, "tm-pullback-v1", "a historical record keeps its own version");
  const html = setupCard(card);
  assert.match(html, /Confirmed plan shown/);
  assert.doesNotMatch(html, /4,291\.72|1:79/);
  // Without a confirmed plan (not confirmed) the latest observation is what exists.
  const developing = tradeLevels(xau({confirmed_plan: null, confirmation: null, lifecycle_state: "DEVELOPING"}));
  assert.equal(developing.basis, "latest");
  assert.equal(developing.rr, "1:79.02");
});

test("no frontend calculations: levels, R:R and score are the backend's values", () => {
  const noRr = tradeLevels(xau({confirmed_plan: {...confirmedPlan, rr: null}}));
  assert.equal(noRr.rr, null, "a missing R:R stays missing; it is never computed");
  const analysis = {risk_context: {entry: 1, stop_loss: 0.5, take_profit: 3, rr: 4}};
  assert.equal(tradeLevels(xau(), analysis).entry, "4,265.00", "a confirmed plan outranks any other source");
});

test("risk bar: backend distances on a price axis, a SHORT mirrors a LONG, a hairline reveals a tiny stop", () => {
  const risk = riskModel(xau());
  assert.equal(risk.direction, "SHORT");
  assert.deepEqual(risk.axis.map(point => point.key), ["target", "entry", "stop"]);
  assert.deepEqual(risk.segments, ["reward", "risk"]);
  assert.ok(Math.abs(risk.riskShare - 28.058571428571668 / (28.058571428571668 + 79.55)) < 1e-12);
  const long = riskModel({...xau(), direction: "LONG", confirmed_plan: {...confirmedPlan, entry: 100, stop_loss: 98, take_profit: 106, risk_distance: 2, reward_distance: 6, rr: 3}});
  assert.deepEqual(long.axis.map(point => point.key), ["stop", "entry", "target"]);
  const drifted = riskModel(xau({confirmed_plan: null, confirmation: null, lifecycle_state: "DEVELOPING"}));
  assert.ok(drifted.riskShare < 0.02, "1:79 shows as a sliver of risk");
  assert.match(riskBar(drifted), /flex-grow:0\.0/);
  assert.equal(risk.quality, null, "no stop evidence recorded (v1): no quality label is invented");
});

test("stop quality labels come only from backend stop evidence", () => {
  const stop = {risk_quality: "RISK_REJECTED", basis: "STRUCTURAL", stop_distance_atr_h1: 3.4, rejection_reason: "Structural invalidation requires excessive risk (3.40 ATR(H1), max 3.0). Setup rejected."};
  const row = xau({confirmed_plan: null, confirmation: null, lifecycle_state: "CONFIRMING", strategy_evidence: {stop}, proposed_entry: 100, proposed_stop_loss: 110, proposed_take_profit: 60, features: {rr: 4}});
  const risk = riskModel(row);
  assert.equal(risk.quality.label, "Risk rejected");
  assert.equal(risk.structural, true);
  assert.match(riskBar(risk), /Risk rejected/);
  const model = analystModel(row);
  assert.match(analystPanel(model), /Stop evidence/);
  assert.match(analystPanel(model), /Setup rejected\./);
  const trendline = riskModel({...row, strategy_id: "trendline", strategy_evidence: {}});
  assert.equal(trendline.quality, null);
});

test("lifecycle rail follows recorded events and names the terminal state", () => {
  const rail = lifecycleRail(xau());
  assert.deepEqual(rail.steps.filter(step => step.reached).map(step => step.step), ["WATCHING", "DEVELOPING", "CONFIRMED", "ACTIVE"]);
  assert.equal(rail.current, "ACTIVE");
  const closed = lifecycleRail(xau({lifecycle_state: "INVALIDATED", lifecycle_events: [...xau().lifecycle_events, {to_state: "INVALIDATED", occurred_at: "2026-09-25T01:21:50Z"}]}));
  assert.equal(closed.current, "CLOSED");
  assert.equal(closed.steps.at(-1).label, "INVALIDATED");
  assert.equal(closed.steps.find(step => step.step === "CONFIRMING").reached, false, "never inferred");
});

test("the historical XAUUSD record: closed, short, trend/momentum, stop hit, -1.0R, confirmed levels", () => {
  const closedRow = xau({lifecycle_state: "INVALIDATED", closed_event: {occurred_at: "2026-09-25T01:21:50Z", reason_code: "INVALIDATION_PRICE_CROSSED"}});
  const verified = {record_type: "market_outcome", setup_id: "stp_x", observation_id: "obs_c", horizon: "4h", label: "LOSS",
    label_definition: "target-invalidation-first-v1", timestamp_quality: "VERIFIED", data_quality: {timestamp_quality: "VERIFIED"},
    outcome_time_validity: "OUTCOME_TIME_VALID", outcome_time_validation: {outcome_time_validity: "OUTCOME_TIME_VALID",
      every_candidate_strictly_after_observation: true, candidate_candles_chronological: true}};
  const snapshot = {proposed_entry: confirmedPlan.entry, proposed_stop_loss: confirmedPlan.stop_loss, proposed_take_profit: confirmedPlan.take_profit,
    reference_price: confirmedPlan.reference_price, invalidation_price: confirmedPlan.invalidation_price};
  const entry = archiveEntry(closedRow, [verified], snapshot);
  assert.deepEqual([entry.lifecycle, entry.direction, entry.strategy.tag, entry.label, entry.rText], ["INVALIDATED", "SHORT", "TREND/MOM", "Stop hit", "-1.0R"]);
  const model = analystModel(closedRow, null, entry);
  const html = analystPanel(model);
  assert.match(html, /Not a trade result/);
  assert.match(html, /4,265\.00/);
  assert.doesNotMatch(html, /4,291\.72/);
});

test("three live strategies are visible with LIVE and their version; combined view and filters", () => {
  const model = gardenHeaderModel({markets: new Array(16).fill({}), episodes: {current: [], confirmed: [xau()], closed: []}, registry: REGISTRY, lastScan: "2026-09-25T06:12:00Z"});
  assert.deepEqual(model.strategies.map(s => [s.tag, s.version]), [["TRENDLINE", "trendline-first-v4"], ["S/R", "sr-levels-v1"], ["TREND/MOM", "tm-pullback-v2"]]);
  assert.equal(model.confirmed, 1);
  const html = gardenHeader(model);
  for (const label of ["Trendline", "Support &amp; Resistance", "Trend / Momentum"]) assert.match(html, new RegExp('<small class="gd-live">LIVE</small>' + label));
  assert.match(html, /tm-pullback-v2/);
  const bar = strategyFilterBar(strategyFilters(REGISTRY));
  assert.match(bar, /data-strategy-filter="all"/);
  for (const id of ["trendline", "support_resistance", "trend_momentum"]) assert.match(bar, new RegExp('data-strategy-filter="' + id + '"'));
  assert.doesNotMatch(bar, /data-strategy-filter="(smc|crt|ict)"/);
  const rows = [xau(), {...xau(), setup_id: "t", strategy_id: "trendline"}];
  assert.deepEqual(filterByStrategy(rows, "trend_momentum").map(r => r.setup_id), ["stp_x"]);
});

test("a setup listed in several buckets is counted once", () => {
  const episodes = {current: [xau()], confirmed: [xau()], closed: []};
  const counters = gardenCounters({markets: [], episodes, registry: REGISTRY});
  assert.equal(counters.confirmed, 1);
  assert.equal(gardenAreas(episodes, [], {registry: REGISTRY}).bloomed.length, 1);
});

test("each strategy grows in its own sector of the garden", () => {
  const cards = ["trendline", "support_resistance", "trend_momentum", "smc"].flatMap(id => [0, 1, 2, 3].map(i =>
    ({key: id + i, symbol: "S" + i, stage: i % 2 ? "growing" : "bloomed", direction: "LONG", score: 70, strategy: {id}})));
  for (const orb of constellationLayout(cards)) {
    const offset = Math.atan2(Math.sin(Math.atan2(orb.z, orb.x) - sectorAngle(orb.strategy)), Math.cos(Math.atan2(orb.z, orb.x) - sectorAngle(orb.strategy)));
    assert.ok(Math.abs(offset) <= (Math.PI * 2 / 4) * 0.42 + 1e-9, orb.id);
  }
});

test("confirmed setups get the strongest visual state; watching setups are quiet seeds", () => {
  assert.match(setupCard(setupCardModel(xau())), /gd-stage-active[^"]*" data-key="stp_x"[^>]*data-strategy="trend_momentum"/);
  const watching = setupCardModel({...xau(), setup_id: "w", lifecycle_state: "DETECTED", confirmation: null, confirmed_plan: null});
  assert.equal(watching.watching, true);
  assert.match(setupCard(watching, {compact: true}), /class="gd-seed/);
  assert.doesNotMatch(setupCard(setupCardModel(xau()), {compact: true}), /class="gd-seed/, "a confirmed setup is never a seed");
});

test("evaluation views: insufficient data is said plainly and no rate is shown", () => {
  const similar = {strategy_id: "trend_momentum", min_verified: 30, strategy_totals: {confirmed: 1, verified_decisive: 0, status: "INSUFFICIENT_VERIFIED_DATA"},
    conditions: [{condition: "instrument", label: "Instrument", value: "XAUUSD", confirmed: 1, verified_target: 0, verified_stop: 0, verified_decisive: 0,
      status: "INSUFFICIENT_VERIFIED_DATA", target_share: null}]};
  const html = evidenceBubbles(similar);
  assert.match(html, /INSUFFICIENT VERIFIED DATA/);
  assert.doesNotMatch(html, /%/);
  const sufficient = evidenceBubbles({...similar, strategy_totals: {confirmed: 40, verified_decisive: 32, status: "SUFFICIENT"},
    conditions: [{...similar.conditions[0], confirmed: 40, verified_decisive: 32, verified_target: 8, status: "SUFFICIENT", target_share: 0.25}]});
  assert.doesNotMatch(sufficient, /INSUFFICIENT/);
  assert.match(sufficient, /25% target first of 32 verified/);
  assert.match(evidenceBubbles(null, {state: "loading"}), /Loading historical evidence/);
  const report = {min_verified: 30, rules: "Verified only.", strategies: [{strategy_id: "trend_momentum", totals: {confirmed: 2, verified_stop: 1, status: "INSUFFICIENT_VERIFIED_DATA"},
    conditions: {direction: {label: "Direction", values: {SHORT: {confirmed: 1, verified_decisive: 1, status: "INSUFFICIENT_VERIFIED_DATA", target_share: null}}}}}]};
  const panel = evaluationPanel(report);
  assert.match(panel, /INSUFFICIENT VERIFIED DATA/);
  assert.match(panel, /Direction/);
  assert.match(evaluationPanel(null), /unavailable/);
});
