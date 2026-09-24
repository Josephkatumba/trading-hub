import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createConfirmationAlertTracker, isPersistedConfirmation, persistedConfirmationEvents} from "../src/confirmationAlerts.mjs";
import {gardenResearchEntries, liveGardenRows, strategyConflict, strategyMatrix, strategyTag} from "../src/strategyModel.mjs";
import {gardenAreas, gardenCounters, marketOverviewRow} from "../src/garden/gardenModel.mjs";
import {marketOverview} from "../src/garden/gardenCards.mjs";
import {comparisonRows, evidenceModel, evidencePanel, labReportPanel} from "../src/garden/strategyLab.mjs";

// The registry as the Phase 10 engine reports it.
const REGISTRY = [{strategy_id: "trendline", version: "trendline-first-v4", status: "LIVE"},
  {strategy_id: "support_resistance", version: "sr-levels-v1", status: "SHADOW"},
  {strategy_id: "trend_momentum", version: "tm-pullback-v1", status: "SHADOW"}];
const tmEntry = (direction = "SHORT", extra = {}) => ({strategy_id: "trend_momentum", strategy_version: "tm-pullback-v1", mode: "SHADOW",
  status: "OK", state: "CONFIRMING", direction, confirmed: true, score: 88, entry: 110.94, stop_loss: 109.17, take_profit: 117.98,
  setup_family: "TM_PULLBACK_CONTINUATION", setup_id: "tm1", ...extra});
const market = (tm = tmEntry()) => ({symbol: "XAUUSD", state: "DEVELOPING", direction: "LONG", setup_id: "t1",
  strategies: [{strategy_id: "trendline", mode: "LIVE", status: "OK", state: "DEVELOPING", direction: "LONG", confirmed: false, setup_id: "t1"},
    {strategy_id: "support_resistance", mode: "SHADOW", status: "OK", state: "CONFIRMING", direction: "SHORT", confirmed: true, setup_id: "s1"},
    tm]});
const TM_CONFIRMATION = {setup_id: "tm1", confirmation_event_id: "c3", confirmed_at: "2026-09-24T12:00:00Z", strategy_id: "trend_momentum", shadow: true};

test("trend/momentum has its own identity in the catalog", () => {
  assert.deepEqual(strategyTag("trend_momentum"), {id: "trend_momentum", tag: "TREND/MOM", label: "Trend / Momentum", gardenResearch: true});
  assert.equal(strategyTag("support_resistance").gardenResearch, undefined, "S/R keeps its Strategy Lab-only presentation");
});

test("the market overview shows trend/momentum on a separate RESEARCH line", () => {
  const html = marketOverview([marketOverviewRow(market(), REGISTRY)]);
  assert.match(html, /class="gd-market-research"[^>]*><span class="gd-shadow-badge">RESEARCH<\/span>/);
  assert.match(html, /data-strategy="trend_momentum" title="Entry 110.94 · Stop 109.17 · Target 117.98">TREND\/MOM ▼ SHORT · CONFIRMING · research confirmed · 88</);
  assert.doesNotMatch(html, /gd-market-matrix|Strategy conflict/, "no live strategy line or conflict from research results");
  assert.doesNotMatch(html, /S\/R/, "S/R shadow results stay out of the Garden page");
  // Nothing to show without a directional research result.
  assert.doesNotMatch(marketOverview([marketOverviewRow(market(tmEntry(null, {state: "NO SETUP", confirmed: false})), REGISTRY)]), /RESEARCH/);
  assert.doesNotMatch(marketOverview([marketOverviewRow(market(tmEntry("LONG", {status: "ERROR"})), REGISTRY)]), /RESEARCH/);
});

test("research entries require SHADOW mode and the catalog opt-in", () => {
  const matrix = strategyMatrix(market(), REGISTRY);
  assert.deepEqual(gardenResearchEntries(matrix).map(e => e.id), ["trend_momentum"]);
  // Were the registry to report it LIVE, it would not be drawn as research (and the live rules would apply).
  const live = REGISTRY.map(e => e.strategy_id === "trend_momentum" ? {...e, status: "LIVE"} : e);
  assert.deepEqual(gardenResearchEntries(strategyMatrix(market(), live)), []);
});

test("research setups never become Garden setups, counters, conflicts or alerts", () => {
  const episodes = {current: [{setup_id: "tm2", strategy_id: "trend_momentum", lifecycle_state: "DEVELOPING", shadow: true}],
    confirmed: [{setup_id: "tm1", strategy_id: "trend_momentum", lifecycle_state: "CONFIRMED", confirmation: {}, shadow: true},
      {setup_id: "t2", strategy_id: "trendline", lifecycle_state: "CONFIRMED", confirmation: {}}]};
  const areas = gardenAreas(episodes, [], {registry: REGISTRY});
  assert.deepEqual([...areas.growing, ...areas.bloomed].map(r => r.setup_id), ["t2"]);
  assert.equal(gardenCounters({episodes, registry: REGISTRY}).bloomed, 1);
  assert.deepEqual(liveGardenRows(episodes.current, REGISTRY), []);
  assert.equal(strategyConflict(market(), REGISTRY), null, "opposite research direction is not a live conflict");
  assert.equal(isPersistedConfirmation(TM_CONFIRMATION), false);
  const performance = {daily: [{setups: [{setup_id: "t1", confirmation_event_id: "c1", confirmed_at: "2026-09-24T12:00:00Z"}, TM_CONFIRMATION]}]};
  assert.deepEqual(persistedConfirmationEvents(performance).map(e => e.setup_id), ["t1"]);
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-24T00:00:00Z")});
  assert.deepEqual(tracker.observe(performance.daily[0].setups).map(e => e.setup_id), ["t1"]);
});

test("mutation: removing the shadow guard from alerts is caught", async () => {
  const source = readFileSync(new URL("../src/confirmationAlerts.mjs", import.meta.url), "utf8");
  const guard = "event?.shadow !== true &&";
  assert.ok(source.includes(guard), "the guard exists");
  // A data: module cannot resolve relative imports; point them at the real files.
  const absolute = source.replace(/from "\.\/([^"]+)"/g, (_, file) => 'from "' + new URL("../src/" + file, import.meta.url).href + '"');
  const mutated = await import("data:text/javascript," + encodeURIComponent(absolute.replace(guard, "")));
  assert.equal(mutated.isPersistedConfirmation(TM_CONFIRMATION), true, "without the guard a research confirmation would alert");
  assert.notEqual(mutated.isPersistedConfirmation(TM_CONFIRMATION), isPersistedConfirmation(TM_CONFIRMATION));
});

test("Strategy Lab: its own column and stored evidence", () => {
  const block = (id, total) => ({strategy_id: id, mode: id === "trendline" ? "LIVE" : "SHADOW", version: "v",
    setups: {total, closed: 0, by_state: {}}, confirmations: total, outcomes: {verified_target: 1, verified_stop: 1},
    win_rate: null, win_rate_note: "Not shown: 2 verified target/stop outcomes (needs 30).", recent: [], by_instrument: {}, by_direction: {},
    by_timeframe: {}, by_setup_type: {}});
  const report = {strategies: [block("trendline", 1), block("support_resistance", 0), block("trend_momentum", 3)]};
  const comparison = comparisonRows(report);
  assert.deepEqual(comparison.strategies.map(s => s.tag), ["TRENDLINE", "S/R", "TREND/MOM"]);
  assert.deepEqual(comparison.rows.find(r => r.label === "Setups recorded").values, [1, 0, 3]);
  assert.match(labReportPanel(report, {selected: "trend_momentum"}), /TREND\/MOM <span class="gd-shadow-badge">SHADOW<\/span>/);
  const detail = {setup_id: "tm1", snapshots: [{record_type: "setup_snapshot", observation_id: "o1", symbol: "XAUUSD", direction: "LONG",
    strategy_id: "trend_momentum", strategy_version: "tm-pullback-v1", shadow: true, setup_type: "TM_PULLBACK_CONTINUATION",
    observed_at: "2026-09-24T12:00:00Z", strategy_evidence: {
      trend: {h4: {direction: "LONG", structure: "HIGHER_HIGHS_HIGHER_LOWS", ema50_slope_atr: 1.198}, d1: {status: "AGREES"}, h1: {aligned: true}},
      momentum: {impulse_atr: 10.14, efficiency: 0.853}, pullback: {retracement: 0.45, pullback_bars: 6, controlled: true, failed: []},
      trigger: {resumption: true}, confirmation: {rules: {h4_trend: true, resumption: true}},
      plan: {entry: 110.94, stop: 109.17, target: 117.98, rr: 3.97, min_rr: 1.5, structure_invalidation: 109.37},
      score_components: {h4_trend: {points: 20, max: 20}, pullback: {points: 20, max: 20}}}}],
    confirmation_events: [{observation_id: "o1", confirmed_at: "2026-09-24T12:00:00Z"}], lifecycle_events: [], market_outcomes: []};
  const html = evidencePanel(evidenceModel(detail));
  assert.match(html, /TREND\/MOM <span class="gd-shadow-badge">SHADOW<\/span>/);
  assert.match(html, /<dt>H4 trend<\/dt><dd>LONG · HIGHER_HIGHS_HIGHER_LOWS · EMA50 slope 1.20 × ATR<\/dd>/);
  assert.match(html, /<dt>Pullback<\/dt><dd>retraced 0.450 over 6 H1 bars · controlled yes<\/dd>/);
  assert.match(html, /<dt>M15 continuation<\/dt><dd>yes<\/dd>/);
  assert.match(html, /<li>h4_trend 20 \/ 20<\/li>/);
  assert.match(html, /✓ resumption/);
  assert.match(html, /<dt>R<\/dt><dd>3.97 \(min 1.5\)<\/dd>/);
  assert.doesNotMatch(html, /no structured strategy evidence/);
});
