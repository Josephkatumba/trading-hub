// Phase 10b: Trendline, S/R and Trend/Momentum are all LIVE Garden strategies.
import test from "node:test";
import assert from "node:assert/strict";
import {confirmationToastModel, createConfirmationAlertTracker, persistedConfirmationEvents} from "../src/confirmationAlerts.mjs";
import {liveGardenRows, setupFamilyLabel, strategyConflict, strategyFilters} from "../src/strategyModel.mjs";
import {gardenAreas, gardenCounters, marketOverviewRow, setupCardModel} from "../src/garden/gardenModel.mjs";
import {confirmationToastHtml, counterTiles, marketOverview, setupCard} from "../src/garden/gardenCards.mjs";

// The registry as the Phase 10b engine reports it.
const REGISTRY = [{strategy_id: "trendline", version: "trendline-first-v4", status: "LIVE"},
  {strategy_id: "support_resistance", version: "sr-levels-v1", status: "LIVE"},
  {strategy_id: "trend_momentum", version: "tm-pullback-v1", status: "LIVE"}];

const episode = (overrides = {}) => ({setup_id: "x", symbol: "XAUUSD", direction: "LONG", lifecycle_state: "DEVELOPING", score: 70,
  observed_at: "2026-09-25T10:00:00Z", timeframe: "M15", ...overrides});
const trendline = episode({setup_id: "t1", setup_type: "BREAK"});                               // no strategy_id: historical trendline row
const sr = episode({setup_id: "s1", strategy_id: "support_resistance", direction: "SHORT", setup_type: "SR_BOUNCE", score: 79});
const tm = episode({setup_id: "m1", strategy_id: "trend_momentum", setup_type: "TM_PULLBACK_CONTINUATION", score: 84,
  lifecycle_state: "CONFIRMED", confirmation: {confirmed_at: "2026-09-25T10:15:00Z", setup_type: "TM_PULLBACK_CONTINUATION"}});
const smc = episode({setup_id: "z1", strategy_id: "smc"});
const EPISODES = {current: [trendline, sr, smc], confirmed: [tm], closed: []};

test("all three live strategies appear in the Garden, each as its own setup on the same symbol", () => {
  const areas = gardenAreas(EPISODES, [], {registry: REGISTRY});
  assert.deepEqual(areas.growing.map(r => r.setup_id).sort(), ["s1", "t1"]);
  assert.deepEqual(areas.bloomed.map(r => r.setup_id), ["m1"]);
  assert.deepEqual([...areas.growing, ...areas.bloomed].map(r => r.symbol), ["XAUUSD", "XAUUSD", "XAUUSD"]);
  // Opposite directions on one instrument: both shown, neither suppressed.
  assert.deepEqual([...areas.growing, ...areas.bloomed].map(r => r.direction).sort(), ["LONG", "LONG", "SHORT"]);
});

test("every card names its strategy, direction and setup family", () => {
  const cards = [trendline, sr, tm].map(row => setupCard(setupCardModel(row)));
  assert.match(cards[0], /data-strategy="trendline"[^>]*>TRENDLINE<\/span><span class="gd-dir gd-dir-long">▲ LONG/);
  assert.match(cards[1], /data-strategy="support_resistance"[^>]*>S\/R<\/span><span class="gd-dir gd-dir-short">▼ SHORT/);
  assert.match(cards[1], /Resistance rejection/);
  assert.match(cards[2], /data-strategy="trend_momentum"[^>]*>TREND\/MOM<\/span><span class="gd-dir gd-dir-long">▲ LONG/);
  assert.match(cards[2], /Trend continuation · pullback/);
  assert.match(cards[0], /BREAK/, "trendline families are shown as recorded");
  for (const card of cards) assert.match(card, /Not an entry recommendation/);
  assert.equal(setupFamilyLabel("SR_BREAK_RETEST", "LONG"), "Resistance break/retest");
  assert.equal(setupFamilyLabel("REVERSAL", "SHORT"), "REVERSAL");
});

test("counters include every live strategy once per episode, with a per-strategy split", () => {
  // The same S/R episode listed in two buckets is one episode.
  const episodes = {...EPISODES, confirmed: [tm, {...sr, lifecycle_state: "CONFIRMED", confirmation: {confirmed_at: "2026-09-25T10:20:00Z"}}]};
  const counters = gardenCounters({markets: [{}, {}], episodes, registry: REGISTRY});
  assert.equal(counters.growing + counters.confirming + counters.bloomed + counters.active, 3);
  assert.deepEqual(counters.byStrategy.map(item => [item.tag, item.count]).sort(), [["S/R", 1], ["TREND/MOM", 1], ["TRENDLINE", 1]]);
  const tiles = counterTiles(counters);
  for (const tag of ["TRENDLINE", "S\\/R", "TREND\\/MOM"]) assert.match(tiles, new RegExp('class="gd-counter-breakdown".*>' + tag + ' <b>1</b>'));
  assert.equal(counterTiles(gardenCounters({mode: "OFFLINE"})).includes("gd-counter-breakdown"), false);
});

test("confirmed notifications come from every live strategy and always name it", () => {
  const events = [{setup_id: "t2", confirmation_event_id: "c1", confirmed_at: "2026-09-25T10:00:00Z", symbol: "XAUUSD", direction: "LONG", setup_type: "BREAK", score: 72},
    {setup_id: "s2", confirmation_event_id: "c2", confirmed_at: "2026-09-25T10:05:00Z", strategy_id: "support_resistance", symbol: "GBPJPY",
      direction: "SHORT", setup_type: "SR_BOUNCE", score: 79, rule_evidence: {reason: "Resistance rejection at resistance 210.1 (4 reactions, strength 7)"}},
    {setup_id: "m2", confirmation_event_id: "c3", confirmed_at: "2026-09-25T10:10:00Z", strategy_id: "trend_momentum", symbol: "XAUUSD",
      direction: "LONG", setup_type: "TM_PULLBACK_CONTINUATION", score: 84, rule_evidence: {reason: "M15 continuation after a controlled pullback"}}];
  const performance = {daily: [{setups: events}]};
  assert.deepEqual(persistedConfirmationEvents(performance).map(e => e.setup_id), ["t2", "s2", "m2"]);
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-25T00:00:00Z")});
  const alerts = tracker.observe(events);
  assert.deepEqual(alerts.map(e => e.setup_id), ["t2", "s2", "m2"], "one alert per strategy episode");
  assert.deepEqual(tracker.observe(events), [], "never repeated");
  const toasts = alerts.map(confirmationToastModel);
  assert.deepEqual(toasts.map(t => t.headline), ["XAUUSD · TRENDLINE · LONG", "GBPJPY · S/R · SHORT", "XAUUSD · TREND/MOM · LONG"]);
  assert.deepEqual(toasts.map(t => t.setup), ["BREAK", "Resistance rejection", "Trend continuation · pullback"]);
  assert.deepEqual(toasts.map(t => t.score), ["72", "79", "84"]);
  const html = confirmationToastHtml(events[2]);
  assert.match(html, /data-strategy="trend_momentum"/);
  assert.match(html, /NEW CONFIRMED SETUP<\/b><strong>XAUUSD · TREND\/MOM · LONG<\/strong>/);
  assert.match(html, /M15 continuation after a controlled pullback/);
  assert.match(html, /Not an entry recommendation\./);
  assert.equal(confirmationToastModel({setup_id: "q"}).headline, "Symbol unavailable · TRENDLINE · Direction unavailable");
});

test("a research (SHADOW) strategy would still never alert or reach the Garden", () => {
  const research = REGISTRY.map(e => e.strategy_id === "trend_momentum" ? {...e, status: "SHADOW"} : e);
  assert.deepEqual(liveGardenRows([tm], research), []);
  const shadowEvent = {setup_id: "m3", confirmation_event_id: "c4", confirmed_at: "2026-09-25T10:00:00Z", strategy_id: "trend_momentum", shadow: true};
  assert.deepEqual(persistedConfirmationEvents({daily: [{setups: [shadowEvent]}]}), []);
});

test("live strategies disagreeing on one market are shown side by side", () => {
  const market = {symbol: "XAUUSD", state: "DEVELOPING", direction: "LONG", setup_id: "t1", strategies: [
    {strategy_id: "trendline", mode: "LIVE", status: "OK", state: "DEVELOPING", direction: "LONG", setup_id: "t1"},
    {strategy_id: "support_resistance", mode: "LIVE", status: "OK", state: "CONFIRMING", direction: "SHORT", setup_id: "s1"},
    {strategy_id: "trend_momentum", mode: "LIVE", status: "OK", state: "DEVELOPING", direction: "LONG", setup_id: "m1"}]};
  const conflict = strategyConflict(market, REGISTRY);
  assert.deepEqual(conflict.sides.map(s => [s.tag, s.direction]), [["TRENDLINE", "LONG"], ["S/R", "SHORT"], ["TREND/MOM", "LONG"]]);
  const html = marketOverview([marketOverviewRow(market, REGISTRY)]);
  assert.match(html, /TRENDLINE ▲ BUY.*S\/R ▼ SELL.*TREND\/MOM ▲ BUY/);
  assert.doesNotMatch(html, /RESEARCH/);
});

test("SMC, CRT and ICT stay disabled and invisible", () => {
  const filters = Object.fromEntries(strategyFilters(REGISTRY).map(f => [f.key, f]));
  for (const id of ["smc", "crt", "ict"]) {
    assert.equal(filters[id].status, "UNAVAILABLE");
    assert.equal(filters[id].selectable, false);
  }
  for (const id of ["trendline", "support_resistance", "trend_momentum"]) assert.equal(filters[id].status, "LIVE");
  assert.deepEqual(liveGardenRows([smc], REGISTRY), []);
});

test("the archive keeps each setup's own strategy", () => {
  const closed = [{...tm, setup_id: "m9", lifecycle_state: "INVALIDATED", confirmation: null},
    {...sr, setup_id: "s9", lifecycle_state: "EXPIRED"}, {...trendline, setup_id: "t9", lifecycle_state: "EXPIRED"}];
  const areas = gardenAreas({current: [], confirmed: [], closed}, [], {registry: REGISTRY});
  assert.deepEqual(areas.history.map(row => setupCardModel(row).strategy.tag), ["TREND/MOM", "S/R", "TRENDLINE"]);
});
