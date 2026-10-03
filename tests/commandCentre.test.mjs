// Garden command centre: Market Watch, compact cards, selected-market overlay,
// header split and the Market Research drawer. Everything shown must be API data
// or an explicit "Not available" — never a derived or invented value.
import test from "node:test";
import assert from "node:assert/strict";
import {gardenHeaderModel, researchModel, setupCardModel} from "../src/garden/gardenModel.mjs";
import {compactCard, focusPanel, gardenHeader, headerStats, headerStrategies, researchPanel} from "../src/garden/gardenCards.mjs";
import {setupCountSummary, visibleSetupEntries} from "../src/radarLayout.mjs";

const REGISTRY = [{strategy_id: "trendline", status: "LIVE"}, {strategy_id: "support_resistance", status: "LIVE"}, {strategy_id: "trend_momentum", status: "LIVE"}];
const confirmed = (extra = {}) => ({
  setup_id: "stp_1", symbol: "XAUUSD", direction: "SHORT", strategy_id: "support_resistance", lifecycle_state: "CONFIRMED", timeframe: "M15",
  setup_type: "SR_REJECTION", score: 78, session: {session: "London"},
  confirmation: {confirmed_at: "2026-09-25T09:42:00Z", observation_id: "obs_1"},
  confirmed_plan: {observation_id: "obs_1", entry: 4273.5, stop_loss: 4285.2, take_profit: 4240, rr: 2.86, score: 78},
  features: {structure: "Lower highs + lower lows", higher_timeframe_bias: "BEARISH", momentum: "BEARISH", rsi: 41.27, nearest_level: 4286.1, nearest_level_type: "RESISTANCE", nearest_level_atr: 0.62, trendline_line: {a: 1}},
  ...extra,
});

test("compact cards: summary only, stop and confirmation only on confirmed cards", () => {
  const card = setupCardModel(confirmed());
  const done = compactCard(card, {variant: "confirmed"});
  for (const text of ["XAUUSD", "▼ SHORT", "78", "4,273.50", "4,285.20", "4,240.00", "1:2.86", "London session", "Confirmed 09:42 UTC", "CONFIRMED", "M15"]) assert.ok(done.includes(text), text);
  assert.match(done, /data-dir="short"/);
  assert.doesNotMatch(done, /Why TRADeden sees it/, "no paragraphs on compact cards");
  const developing = compactCard(setupCardModel(confirmed({lifecycle_state: "DEVELOPING", confirmation: null, confirmed_plan: null,
    proposed_entry: 4270, proposed_stop_loss: 4280, proposed_take_profit: 4250, features: {rr: 2}})));
  assert.doesNotMatch(developing, /Stop<\/dt>/);
  assert.match(developing, /Target<\/dt>/);
  const sparse = compactCard(setupCardModel({symbol: "EURUSD", state: "WATCHING", lifecycle_state: "DEVELOPING"}));
  assert.match(sparse, /Levels appear once/);
});

test("the selected-market overlay offers Market Research and can be cleared", () => {
  const html = focusPanel(setupCardModel(confirmed()));
  assert.match(html, /data-focus-action="research"/);
  assert.match(html, /View market research/);
  assert.match(html, /data-focus-action="close"/);
  assert.match(html, /Lifecycle CONFIRMED/);
  assert.match(html, /S\/R/);
});

test("header split keeps every number and marks them for change transitions", () => {
  const model = gardenHeaderModel({markets: new Array(12).fill({}), episodes: {current: [], confirmed: [confirmed()], closed: []}, registry: REGISTRY});
  assert.equal(gardenHeader(model), headerStrategies(model) + headerStats(model));
  const stats = headerStats(model);
  for (const key of ["instruments", "confirmed", "developing", "watching"]) assert.match(stats, new RegExp('data-stat="' + key + '"'));
  assert.match(stats, /data-stat="instruments">12</);
  assert.match(headerStats(gardenHeaderModel({mode: "OFFLINE"})), /data-stat="instruments">—</, "offline is unavailable, never 0");
});

test("research reads recorded facts and evidence only", () => {
  const analysis = {confirmations: [{category: "momentum", claim: "Recorded momentum supports SHORT."}, {category: "support_resistance", claim: "Recorded nearby support/resistance level."}],
    conflicts: [{category: "higher_timeframe", claim: "Higher-timeframe bias opposes the recorded direction."}], missing_confirmations: [], summary: "Rejection at resistance."};
  const model = researchModel(confirmed(), {analysis});
  assert.equal(model.basis, "recorded");
  assert.deepEqual(model.sections.structure.facts, [{label: "Structure", value: "Lower highs + lower lows"}]);
  assert.deepEqual(model.sections.momentum.facts.map(f => f.value), ["BEARISH", "41.3"]);
  assert.deepEqual(model.sections.levels.facts.map(f => f.value), ["RESISTANCE", "4,286.10", "0.62 ATR"]);
  assert.ok(!model.sections.trend.facts.some(f => f.label === "Trendline"), "object-valued fields are not shown");
  assert.equal(model.sections.momentum.evidence[0].claim, "Recorded momentum supports SHORT.");
  assert.equal(model.sections.trend.evidence[0].tone, "oppose");
  const html = researchPanel(model);
  for (const title of ["Market structure", "Trend", "Momentum", "Support &amp; resistance", "Strategy evidence", "Current plan", "Why TRADeden sees it", "What could invalidate it", "Historical context"])
    assert.ok(html.includes(title), title);
  assert.match(html, /Rejection at resistance\./);
  assert.match(html, /4,285\.20/);
  assert.match(html, /not an AI or machine-learning prediction/i);
});

test("research shows Not available instead of inventing anything", () => {
  const bare = researchModel({symbol: "GER40", state: "WATCHING"});
  assert.equal(bare.basis, "live");
  assert.equal(bare.hasSetup, false);
  const html = researchPanel(bare);
  assert.match(html, /Not available for this setup/);
  assert.match(html, /this market has no recorded setup/);
  assert.match(html, /Not available: the engine has not calculated both a stop and a target/);
  assert.match(html, /Live market scan/);
  assert.doesNotMatch(html, /NaN|undefined|null/);
  assert.match(researchPanel(researchModel(confirmed()), {loading: true}), /Loading recorded evidence/);
  assert.equal(researchModel(null), null);
});

test("closed setups open as records with their outcome", () => {
  const closed = confirmed({lifecycle_state: "RESOLVED", closed_event: {occurred_at: "2026-09-25T11:00:00Z", reason: "target reached"}});
  const archive = {icon: "🎯", label: "Target hit", horizon: "1h", rText: "+2.9R", confirmed: true, kind: "target"};
  const html = researchPanel(researchModel(closed, {archive}));
  assert.match(html, /Closed setup record/);
  assert.match(html, /gd-outcome-target/);
  assert.match(html, /\+2\.9R/);
  assert.match(html, /What invalidated it/);
  assert.doesNotMatch(html, /data-research-action="track"/, "closed setups are not trackable");
});

test("section limits: 10 developing before View all", () => {
  const rows = Array.from({length: 14}, (_, i) => i);
  assert.equal(visibleSetupEntries(rows, false, 10).length, 10);
  assert.equal(setupCountSummary(14, false, 10), "Showing 10 of 14");
  assert.equal(setupCountSummary(10, false, 10), null);
});

test("S/R and Trend/Momentum research reads the strategy's own recorded evidence", () => {
  const tm = {setup_id: "tm1", symbol: "EURUSD", strategy_id: "trend_momentum", direction: "SHORT", lifecycle_state: "DEVELOPING", features: {price: 1.139, atr: 0.00078},
    strategy_evidence: {trend: {h4: {direction: "SHORT", structure: "LOWER_HIGHS_LOWER_LOWS", ema50_slope_atr: -0.8747, last_swing_highs: [1.14782, 1.13991]}, d1: {status: "AGREES"}, h1: {aligned: true}},
      momentum: {impulse_atr: 8.5996, efficiency: 0.2541}, pullback: {retracement: 0.4851, controlled: false},
      confirmation: {rules: {h4_trend: true, pullback_controlled: false, min_rr: false}}}};
  const market = {symbol: "EURUSD", structure: "Lower highs", market_bias: "BEARISH", momentum: "BEARISH", rsi: 44.2};
  const model = researchModel(tm, {market});
  assert.deepEqual(model.sections.structure.facts.map(f => [f.label, f.value]), [["H4 structure", "Lower highs lower lows"], ["Pullback retracement", "48.5%"], ["Pullback controlled", "No"]]);
  assert.deepEqual(model.sections.trend.facts.map(f => f.value), ["Short", "-0.87 ATR", "Agrees", "Yes"]);
  assert.deepEqual(model.sections.momentum.facts.map(f => f.value), ["8.60 ATR", "0.25"]);
  assert.equal(model.sections.levels.facts.find(f => f.label === "H4 swing highs").value, "1.14782, 1.13991");
  assert.deepEqual(model.sections.structure.scan, [], "scan context only fills sections the setup left empty");
  assert.deepEqual(model.rules, [{rule: "H4 trend", passed: true}, {rule: "Pullback controlled", passed: false}, {rule: "Min rr", passed: false}]);
  const html = researchPanel(model);
  assert.match(html, /Trend \/ Momentum rules · latest observation/);
  const sr = {setup_id: "sr1", symbol: "GBPUSD", strategy_id: "support_resistance", direction: "SHORT", lifecycle_state: "DEVELOPING", features: {atr: 0.0006},
    strategy_evidence: {family: "SR_BOUNCE", level: {type: "RESISTANCE", price: 1.32404, zone_low: 1.32383, zone_high: 1.32439, reactions: 5, role_reversal: true}, distance_atr_h1: 0}};
  const srModel = researchModel(sr, {market});
  assert.deepEqual(srModel.sections.levels.facts.map(f => f.value), ["0.0006", "Resistance", "1.32404", "1.32383", "1.32439", "5", "Yes", "0.00 ATR"]);
  assert.deepEqual(srModel.sections.trend.facts, []);
  assert.deepEqual(srModel.sections.trend.scan.map(f => f.value), ["BEARISH"], "S/R records no trend: the latest scan fills it, labelled");
  assert.match(researchPanel(srModel), /Latest market scan/);
  const closedSr = researchModel({...sr, lifecycle_state: "EXPIRED"}, {market});
  assert.deepEqual(closedSr.sections.trend.scan, [], "a closed setup is a record: never mixed with today's scan");
});
