import test from "node:test";
import assert from "node:assert/strict";
import {GARDEN_STAGES, analystModel, cardTone, formatRiskReward, gardenAreas, gardenCounters, gardenStage,
  marketOverviewRow, constellationLayout, BANDS, setupCardModel, tradeLevels} from "../src/garden/gardenModel.mjs";
import {analystPanel, counterTiles, marketOverview, setupCard} from "../src/garden/gardenCards.mjs";
import {chooseGardenRenderer} from "../src/garden/gardenMount.mjs";

const episode = (over = {}) => ({setup_id: "stp_1", observation_id: "obs_1", symbol: "XAUUSD", direction: "SHORT",
  lifecycle_state: "DETECTED", score: 78, setup_type: "REVERSAL", timeframe: "M15", observed_at: "2026-09-24T09:42:00+00:00",
  session: {session: "New York"}, rule_evidence: {reason: "price rejected the descending trendline; momentum agrees"}, ...over});

test("garden stages mirror the authoritative lifecycle states without changing them", () => {
  const cases = {DETECTED: "growing", DEVELOPING: "growing", CONFIRMING: "shaping", CONFIRMED: "bloomed",
    ACTIVE: "active", INVALIDATED: "history", EXPIRED: "history", RESOLVED: "history"};
  for (const [state, stage] of Object.entries(cases)) assert.equal(gardenStage({lifecycle_state: state}), stage, state);
  // markets without a lifecycle fall back to scanner state
  assert.equal(gardenStage({state: "CONFIRMING", strategy_valid: false}), "shaping");
  assert.equal(gardenStage({state: "CONFIRMING", strategy_valid: true}), "bloomed");
  assert.equal(gardenStage({state: "WATCHING"}), "growing");
  assert.deepEqual(Object.keys(GARDEN_STAGES), ["growing", "shaping", "bloomed", "active", "history"]);
});

test("tone: confirmed long green, confirmed short red, history grey, developing neutral", () => {
  assert.equal(cardTone("bloomed", "LONG"), "long");
  assert.equal(cardTone("active", "SHORT"), "short");
  assert.equal(cardTone("history", "LONG"), "history");
  assert.equal(cardTone("shaping", "SHORT"), "developing");
});

test("trade levels appear only when the engine calculated both stop and target", () => {
  const watching = tradeLevels({entry: 4272.4, stop_loss: null, take_profit: null, rr: null});
  assert.equal(watching.planned, false);
  assert.equal(watching.entry, null, "a live price must not be presented as an entry");
  const planned = tradeLevels({proposed_entry: 4272.4, proposed_stop_loss: 4285.2, proposed_take_profit: 4234, features: {rr: 3}});
  assert.deepEqual([planned.entry, planned.stop, planned.target, planned.rr], ["4,272.40", "4,285.20", "4,234.00", "1:3"]);
  const fromAnalysis = tradeLevels({}, {risk_context: {entry: 1.1, stop_loss: 1.09, take_profit: 1.13, rr: 2.456}});
  assert.equal(fromAnalysis.rr, "1:2.46");
  assert.equal(formatRiskReward(null), null);
  assert.equal(formatRiskReward(0), null);
});

test("card model uses only API data and marks gaps explicitly", () => {
  const card = setupCardModel(episode({lifecycle_state: "CONFIRMED", confirmation: {confirmed_at: "2026-09-24T09:42:10Z"},
    proposed_entry: 4272.4, proposed_stop_loss: 4285.2, proposed_take_profit: 4234, features: {rr: 3}}), {bucket: "bloomed"});
  assert.equal(card.headline, "CONFIRMED SHORT");
  assert.equal(card.tone, "short");
  assert.equal(card.score, 78);
  assert.equal(card.confirmationTime, "09:42 UTC · 24 Sep");
  assert.equal(card.session, "New York");
  assert.equal(card.why, "Price rejected the descending trendline. Momentum agrees.");
  const sparse = setupCardModel({symbol: "EURUSD", state: "WATCHING"});
  assert.equal(sparse.score, null);
  assert.equal(sparse.session, null);
  assert.equal(sparse.why, null);
  assert.equal(sparse.key, "mkt-EURUSD");
  const html = setupCard(sparse);
  assert.doesNotMatch(html, /gd-levels"/, "no level grid without calculated levels");
  assert.match(html, /appear once the engine calculates a stop and a target/);
  assert.match(html, /No explanation was recorded/);
  assert.match(html, /Not an entry recommendation\. The trader makes the final decision\./);
});

test("cards never offer execution buttons", () => {
  const html = setupCard(setupCardModel(episode({lifecycle_state: "CONFIRMED", confirmation: {confirmed_at: "2026-09-24T09:42:10Z"}})));
  for (const forbidden of [/buy now/i, /sell now/i, /execute/i, /place order/i]) assert.doesNotMatch(html, forbidden);
  for (const action of ["View setup", "View evidence", "View analysis", "Track setup"]) assert.ok(html.includes(action), action);
});

test("simulated cards cannot be tracked and all text is escaped", () => {
  const card = setupCardModel({symbol: "<img src=x onerror=alert(1)>", state: "WATCHING", reason: "<b>x</b>"}, {simulated: true});
  const html = setupCard(card);
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /Track setup/);
});

test("areas split current / confirmed / closed and fall back to markets only without episodes", () => {
  const episodes = {current: [episode({setup_id: "a"})],
    confirmed: [episode({setup_id: "b", lifecycle_state: "ACTIVE", confirmation: {confirmed_at: "2026-09-24T09:00:00Z"}})],
    closed: [episode({setup_id: "c", lifecycle_state: "INVALIDATED"})]};
  const areas = gardenAreas(episodes, []);
  assert.deepEqual([areas.growing.length, areas.bloomed.length, areas.history.length], [1, 1, 1]);
  const fallback = gardenAreas({current: [], confirmed: [], closed: []}, [{symbol: "EURUSD", state: "DEVELOPING", setup: "Trendline setup"}]);
  assert.equal(fallback.growing.length, 1);
});

test("counters come from data and are unavailable (not zero) when offline", () => {
  const episodes = {current: [episode({setup_id: "a"}), episode({setup_id: "b", lifecycle_state: "CONFIRMING"})],
    confirmed: [episode({setup_id: "c", lifecycle_state: "CONFIRMED", confirmation: {}}), episode({setup_id: "d", lifecycle_state: "ACTIVE", confirmation: {}})],
    closed: [episode({setup_id: "e", lifecycle_state: "EXPIRED"})]};
  assert.deepEqual(gardenCounters({markets: new Array(15).fill({}), episodes, mode: "LIVE"}),
    {watched: 15, growing: 1, confirming: 1, bloomed: 1, active: 1});
  const offline = gardenCounters({markets: [], episodes: null, mode: "OFFLINE"});
  assert.ok(Object.values(offline).every(value => value === null));
  assert.match(counterTiles(offline), /—/);
});

test("analyst model is labelled rule-based and never claims prediction", () => {
  const model = analystModel(episode({proposed_stop_loss: 4285.2, proposed_take_profit: 4234, invalidation_price: 4285.2}),
    {analyst_version: "deterministic-setup-analyst-v1", summary: "WATCH: evidence is incomplete",
      confirmations: [{claim: "Price rejected resistance"}], missing_confirmations: [{claim: "Trendline gate not passed"}],
      conflicts: [{claim: "Momentum opposes the setup"}]});
  assert.deepEqual(model.confirms, ["Price rejected resistance"]);
  assert.deepEqual(model.stillNeeded, ["Trendline gate not passed"]);
  assert.equal(model.invalidates[0], "A move through 4,285.20 invalidates the setup.");
  assert.ok(model.invalidates.includes("Conflict: Momentum opposes the setup"));
  const html = analystPanel(model);
  assert.match(html, /Rule-based analysis \(deterministic-setup-analyst-v1\)/);
  assert.match(html, /not an AI or machine-learning prediction/);
  assert.match(html, /Not an entry recommendation/);
  assert.doesNotMatch(html, /guarantee/i);
  assert.match(analystPanel(null), /Select a setup/);
});

test("market overview rows show real values or explicit gaps", () => {
  const row = marketOverviewRow({symbol: "BTCUSD", price: 112840, change_pct: -0.48, direction: "SHORT", state: "WATCHING", lifecycle_state: "DETECTED"});
  assert.deepEqual([row.price, row.change, row.changeTone, row.setupStatus], ["112,840.00", "-0.48%", "down", "Growing"]);
  const empty = marketOverviewRow({symbol: "GER40"});
  assert.equal(empty.price, null);
  assert.equal(empty.setupStatus, "No setup");
  assert.match(marketOverview([empty]), /Unavailable/);
});

test("constellation layout is stable per setup, capped per stage, banded and spaced", () => {
  const cards = Array.from({length: 40}, (_, i) => setupCardModel(episode({setup_id: "s" + i, lifecycle_state: i % 2 ? "INVALIDATED" : "DETECTED"})));
  const first = constellationLayout(cards), second = constellationLayout(cards);
  assert.deepEqual(first, second);
  assert.ok(first.filter(p => p.stage === "history").length <= 18);
  assert.ok(first.filter(p => p.stage === "growing").length <= 18);
  for (const orb of first) {
    const radius = Math.hypot(orb.x, orb.z), band = BANDS[orb.stage];
    assert.ok(radius >= band.r[0] - 1e-9 && radius <= band.r[1] + 1e-9, "orb outside its lifecycle band");
  }
  const live = first.filter(p => p.stage !== "history");
  for (let i = 0; i < live.length; i++) for (let j = i + 1; j < live.length; j++) {
    assert.ok(Math.hypot(live[i].x - live[j].x, live[i].z - live[j].z) > 0.4, "live orbs overlap");
  }
  assert.equal(constellationLayout(cards, "s0").find(p => p.id === "s0").selected, true);
});

test("history sits outside every live band so closed setups never crowd the centre", () => {
  const liveMax = Math.max(...["bloomed", "active", "shaping", "growing"].map(stage => BANDS[stage].r[1]));
  assert.ok(BANDS.history.r[0] > liveMax);
  assert.ok(BANDS.bloomed.r[1] <= BANDS.growing.r[0]);
});

test("renderer choice: WebGL only where it is cheap and wanted", () => {
  assert.equal(chooseGardenRenderer({webgl: false, width: 1600}).mode, "fallback");
  assert.equal(chooseGardenRenderer({webgl: true, width: 1600}).mode, "webgl");
  assert.equal(chooseGardenRenderer({webgl: true, width: 390}).mode, "fallback");
  assert.equal(chooseGardenRenderer({webgl: true, width: 1600, saveData: true}).mode, "fallback");
  assert.equal(chooseGardenRenderer({webgl: true, width: 1600, deviceMemory: 2}).mode, "fallback");
  assert.equal(chooseGardenRenderer({webgl: true, width: 1600, preference: "0"}).mode, "fallback");
  assert.equal(chooseGardenRenderer({webgl: true, width: 390, preference: "1"}).mode, "webgl");
});

test("bloom fires only on a real transition into CONFIRMED observed while open", async () => {
  const {shouldBloom} = await import("../src/garden/gardenModel.mjs");
  assert.equal(shouldBloom({previousStage: "shaping", nextStage: "bloomed", firstUpdate: false, animate: true}), true);
  assert.equal(shouldBloom({previousStage: undefined, nextStage: "bloomed", firstUpdate: true, animate: true}), false, "first paint replays state");
  assert.equal(shouldBloom({previousStage: "bloomed", nextStage: "bloomed", firstUpdate: false, animate: true}), false);
  assert.equal(shouldBloom({previousStage: "shaping", nextStage: "bloomed", firstUpdate: false, animate: false}), false, "reduced motion");
  assert.equal(shouldBloom({previousStage: "growing", nextStage: "shaping", firstUpdate: false, animate: true}), false);
  assert.equal(shouldBloom({previousStage: "bloomed", nextStage: "active", firstUpdate: false, animate: true}), false);
});

test("focus panel shows the selection with real levels only", async () => {
  const {focusPanel} = await import("../src/garden/gardenCards.mjs");
  const planned = focusPanel(setupCardModel(episode({lifecycle_state: "CONFIRMED", confirmation: {confirmed_at: "2026-09-24T09:42:10Z"},
    proposed_entry: 4272.4, proposed_stop_loss: 4285.2, proposed_take_profit: 4234, features: {rr: 3}})));
  assert.match(planned, /XAUUSD/); assert.match(planned, /4,285.20/); assert.match(planned, /1:3/); assert.match(planned, /View analysis/);
  const sparse = focusPanel(setupCardModel(episode()));
  assert.doesNotMatch(sparse, /gd-focus-levels/);
  assert.equal(focusPanel(null), "");
});
