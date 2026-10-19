// T-035: one dashboard for the whole strategy bank (pure functions only).
import test from "node:test";
import assert from "node:assert/strict";
import {FAMILIES, bankGardenRow, bankOutcomeKind, filterUnified, familyOf, matchesUnified, productionIdOf, selectableKeys,
  strategyOptions, unifiedHeaderModel, unifiedKey, unifiedStrategy, validationOf} from "../src/strategyUnified.mjs";
import {bankArchiveEntry, constellationLayout, sectorAngle, setupCardModel, strategySectors} from "../src/garden/gardenModel.mjs";
import {focusPanel, strategySelect, unifiedHeader} from "../src/garden/gardenCards.mjs";
import {bankResearchPanel, bankStrategyPerformance} from "../src/garden/strategyBank.mjs";
import {strategyTag} from "../src/strategyModel.mjs";

const REPORT = {
  worker: {enabled: true, running: true, telegram_enabled: true},
  strategies: [
    {n: 1, key: "trendline_break_retest", name: "Trendline Break & Retest", status: "LINKED", signals: 44, resolved: 40, win_rate: 0.2, expectancy_r: -0.4},
    {n: 2, key: "trendline_bounce", name: "Trendline Bounce", status: "LINKED", signals: 51, resolved: 50, win_rate: 0.24, expectancy_r: -0.3},
    {n: 3, key: "support_resistance", name: "Support & Resistance", status: "LINKED", signals: 27, resolved: 27, win_rate: 0.37, expectancy_r: 0},
    {n: 5, key: "ema_crossover", name: "EMA Crossover", status: "EXPERIMENTAL", signals: 1, resolved: 0, win_rate: null, expectancy_r: null},
    {n: 11, key: "london_breakout", name: "London Session Breakout", status: "EXPERIMENTAL", signals: 3, resolved: 0, win_rate: null},
    {n: 13, key: "vwap_reversion", name: "VWAP Reversion", status: "UNSUPPORTED", signals: 0, unsupported_reason: "MT5 supplies only tick_volume."},
  ],
  historical: {label: "HISTORICAL BACKTEST (simulated, not live results)", results: {strategies: {
    ema_crossover: {n: 5, name: "EMA Crossover", verdict: "HISTORICALLY UNPROFITABLE after costs",
      performance: {all_periods: {trades: 900, win_rate: 0.3, expectancy_r: -0.08, expectancy_ci95: [-0.12, -0.04]}}}}}},
};
const REGISTRY = [{strategy_id: "trendline_v5", status: "LIVE"}, {strategy_id: "support_resistance", status: "LIVE"},
  {strategy_id: "trend_momentum", status: "LIVE"}, {strategy_id: "smc", status: "LIVE"}];
const SIGNAL = {signal_id: "bank_1", strategy_key: "london_breakout", strategy_name: "London Session Breakout", status: "EXPERIMENTAL",
  symbol: "USDCAD", direction: "SHORT", timeframe: "M15", confirmed_at: "2026-10-19T10:30:00+00:00", entry: 1.4, stop_loss: 1.402,
  take_profit: 1.396, rr: 2, explanation: "M15 close below the London range.", contradictions: ["RSI(14) is oversold at 28"],
  opportunity_id: "opp_1", outcome_status: "PENDING", r_multiple: null};

test("every row gets one unified strategy key; production setups map onto the bank", () => {
  assert.equal(unifiedKey({strategy_id: "trendline_v5", setup_type: "BREAK"}), "trendline_break_retest");
  assert.equal(unifiedKey({strategy_id: "trendline_v5", confirmation: {setup_type: "REVERSAL"}, setup_type: "WATCHING"}), "trendline_bounce");
  assert.equal(unifiedKey({strategy_id: "trendline_v5", setup_type: "WATCHING"}), "prod:trendline_v5");
  assert.equal(unifiedKey({strategy_id: "support_resistance"}), "support_resistance");
  assert.equal(unifiedKey({strategy_id: "smc"}), "prod:smc");
  assert.equal(unifiedKey({}), "prod:trendline", "records without strategy_id are the retired trendline");
  assert.equal(unifiedKey(SIGNAL), "london_breakout");
  assert.equal(productionIdOf("trendline_bounce"), "trendline_v5");
  assert.equal(productionIdOf("prod:trend_momentum"), "trend_momentum");
  assert.equal(productionIdOf("ema_crossover"), null);
});

test("five families; every strategy has one, and bank names register for chips", () => {
  assert.equal(FAMILIES.length, 5);
  assert.equal(familyOf("trendline_v5").id, "trendline");
  assert.equal(familyOf("liquidity_sweep").id, "smart_money");
  assert.equal(familyOf("smc").id, familyOf("prod:smc").id);
  assert.equal(familyOf("bollinger_reversion").id, "reversion");
  assert.equal(strategyTag("ichimoku").label, "Ichimoku Trend Following");
  assert.equal(strategyTag("trendline_v5").tag, "TRENDLINE", "catalog names are unchanged");
  assert.equal(unifiedStrategy("ema_crossover").kind, "bank");
});

test("selector options come from the backend: experimental bank, production, unsupported disabled", () => {
  const options = strategyOptions(REPORT, REGISTRY);
  const labels = options.groups.map(group => [group.label, group.options.map(option => option.key)]);
  assert.deepEqual(labels, [
    ["Strategy bank · experimental", ["ema_crossover", "london_breakout"]],
    ["Production strategies · live", ["trendline_break_retest", "trendline_bounce", "support_resistance", "prod:trend_momentum", "prod:smc"]],
    ["Unsupported", ["vwap_reversion"]]]);
  const keys = selectableKeys(options);
  assert.ok(keys.has("all") && keys.has("ema_crossover") && keys.has("prod:smc"));
  assert.ok(!keys.has("vwap_reversion"));
  const html = strategySelect(options, "london_breakout");
  assert.match(html, /<option value="london_breakout" selected>11\. London Session Breakout · Experimental<\/option>/);
  assert.match(html, /<option value="vwap_reversion" disabled>13\. VWAP Reversion · unsupported<\/option>/);
  assert.doesNotMatch(html, /data-strategy-filter/, "the four-strategy button bar is gone");
  // Offline: still a full list from the static table.
  assert.ok(strategyOptions(null).groups[0].options.length >= 16);
});

test("filtering by unified key covers production setups and bank signals alike", () => {
  const rows = [{strategy_id: "trendline_v5", setup_type: "BREAK"}, {strategy_id: "trendline_v5", setup_type: "REVERSAL"}, bankGardenRow(SIGNAL)];
  assert.equal(filterUnified(rows, "all").length, 3);
  assert.deepEqual(filterUnified(rows, "trendline_bounce"), [rows[1]]);
  assert.ok(matchesUnified(rows[2], "london_breakout"));
});

test("a bank signal becomes a Garden row: open blooms, finished rests in history", () => {
  const open = bankGardenRow(SIGNAL, {opp_1: {strategies: ["London Session Breakout", "Breakout Trading"]}});
  assert.equal(open.lifecycle_state, "CONFIRMED");
  const card = setupCardModel(open);
  assert.equal(card.stage, "bloomed");
  assert.equal(card.unified.label, "London Session Breakout");
  assert.equal(card.validation.key, "experimental");
  assert.deepEqual(card.confirmedBy, ["London Session Breakout", "Breakout Trading"]);
  assert.match(focusPanel(card), /Strategy: <b>London Session Breakout<\/b>.*Also confirmed by: Breakout Trading/);
  const done = bankGardenRow({...SIGNAL, outcome_status: "STOP_HIT", r_multiple: -1, outcome_at: "2026-10-19T12:00:00+00:00"});
  assert.equal(setupCardModel(done).stage, "history");
  const entry = bankArchiveEntry(done.bankSignal);
  assert.deepEqual([entry.kind, entry.rText, entry.unified.label], ["stop", "-1.0R", "London Session Breakout"]);
  assert.equal(bankOutcomeKind({outcome_status: "TIME_EXIT"}), "time_exit");
  assert.equal(bankOutcomeKind({}), "pending", "an outcome is never inferred");
});

test("production cards name their precise strategy and are never called validated", () => {
  const card = setupCardModel({setup_id: "s1", strategy_id: "trendline_v5", setup_type: "REVERSAL", lifecycle_state: "CONFIRMED", symbol: "EURUSD", direction: "LONG"});
  assert.equal(card.strategy.tag, "TRENDLINE");
  assert.equal(card.unified.label, "Trendline Bounce");
  assert.equal(card.validation.label, "Live · not proven profitable");
  assert.equal(validationOf("VALIDATED").key, "validated", "only an explicit backend status is validated");
});

test("garden sectors are strategy families: every orb stays in its family's sector", () => {
  const cards = [setupCardModel(bankGardenRow(SIGNAL)), setupCardModel({setup_id: "s2", strategy_id: "support_resistance", lifecycle_state: "CONFIRMED", symbol: "XAUUSD"}),
    setupCardModel(bankGardenRow({...SIGNAL, signal_id: "b2", strategy_key: "liquidity_sweep", strategy_name: "Liquidity Sweep"}))];
  const orbs = constellationLayout(cards);
  assert.equal(sectorAngle("london_breakout"), sectorAngle("support_resistance"), "same family, same branch");
  assert.notEqual(sectorAngle("liquidity_sweep"), sectorAngle("london_breakout"));
  const sectors = strategySectors(orbs);
  assert.deepEqual(sectors.map(sector => sector.label).sort(), ["Levels & breakouts", "Smart money"]);
  for (const orb of orbs) {
    const offset = Math.atan2(Math.sin(Math.atan2(orb.z, orb.x) - sectorAngle(orb.strategy)), Math.cos(Math.atan2(orb.z, orb.x) - sectorAngle(orb.strategy)));
    assert.ok(Math.abs(offset) <= (Math.PI * 2 / FAMILIES.length) * 0.42 + 1e-9);
  }
});

test("unified header: whole-bank figures from recorded data, nothing validated", () => {
  const model = unifiedHeaderModel({report: REPORT, signals: [SIGNAL, {...SIGNAL, signal_id: "x", outcome_status: "STOP_HIT"}],
    registry: REGISTRY, now: Date.parse("2026-10-19T12:00:00+00:00")});
  assert.deepEqual([model.active, model.linked, model.experimental, model.validated, model.unsupported, model.productionOnly],
    [5, 3, 2, 0, 1, 2]);
  assert.equal(model.open, 1);
  assert.equal(model.resolved, 117);
  assert.equal(Math.round(model.winRate * 100), 26);
  const html = unifiedHeader(model);
  assert.match(html, /Strategies active<\/small><\/span><b class="gd-hcount" data-stat="bank-active">5<\/b>/);
  assert.match(html, /data-stat="bank-validated">0</);
  assert.doesNotMatch(html, /gd-live">LIVE<\/small>Trendline/, "no four-strategy badges");
  assert.match(unifiedHeader(unifiedHeaderModel({report: null})), /Strategy bank unavailable/);
  const pending = unifiedHeader(unifiedHeaderModel({report: {...REPORT, strategies: REPORT.strategies.map(row => ({...row, resolved: 0}))}}));
  assert.match(pending, /data-stat="bank-winrate">Pending</);
});

test("bank details and per-strategy performance keep forward and historical results apart", () => {
  const card = setupCardModel(bankGardenRow(SIGNAL, {opp_1: {strategies: ["London Session Breakout"]}}));
  const panel = bankResearchPanel(card, SIGNAL);
  for (const expected of ["Strategy: <b>London Session Breakout</b>", "Experimental · not proven profitable", "M15 close below the London range.",
    "RSI(14) is oversold at 28", "⏳ Open", "not an executed trade"]) assert.ok(panel.includes(expected), expected);
  const perf = bankStrategyPerformance(REPORT, "ema_crossover");
  assert.match(perf, /FORWARD RESULTS \(RECORDED\)<\/b><b>Pending<\/b>/);
  assert.match(perf, /Historical backtest \(simulated, not live results\):<\/b> 900 trades/);
});

test("the bank has no fixed size: a new research strategy is listed, never counted as alerting", () => {
  const grown = {...REPORT, strategies: [...REPORT.strategies,
    {n: 21, key: "volatility_squeeze_v2", name: "Volatility Squeeze V2", status: "RESEARCH", signals: 0, resolved: 0}]};
  const options = strategyOptions(grown, REGISTRY);
  const research = options.groups.find(group => group.label === "In research · no alerts");
  assert.deepEqual(research.options.map(option => [option.key, option.validation.label]), [["volatility_squeeze_v2", "Research · no alerts"]]);
  assert.ok(selectableKeys(options).has("volatility_squeeze_v2"));
  const model = unifiedHeaderModel({report: grown, registry: REGISTRY});
  assert.deepEqual([model.active, model.research], [5, 1]);
  assert.match(unifiedHeader(model), /data-stat="bank-research">1</);
  assert.equal(unifiedStrategy("volatility_squeeze_v2", "Volatility Squeeze V2").label, "Volatility Squeeze V2");
});
