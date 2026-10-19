import test from "node:test";
import assert from "node:assert/strict";
import {bankPanel, bankRows, bankStatus, historicalRows} from "../src/garden/strategyBank.mjs";

const row = (n, key, name, status, over = {}) => ({n, key, name, status, signals: 0, resolved: 0, open: 0, win_rate: null,
  expectancy_r: null, max_drawdown_r: null, unsupported_reason: null, ...over});
const REPORT = {
  worker: {enabled: false, running: false},
  strategies: [
    row(1, "trendline_break_retest", "Trendline Break & Retest", "LINKED", {signals: 44, resolved: 44, win_rate: 0.1818, expectancy_r: -0.42, max_drawdown_r: 20.1}),
    row(6, "ema_pullback", "EMA Pullback", "EXPERIMENTAL"),
    row(13, "vwap_reversion", "VWAP Reversion", "UNSUPPORTED", {unsupported_reason: "MT5 supplies only tick_volume."}),
  ],
  historical: {label: "HISTORICAL BACKTEST (simulated, not live results)", results: {strategies: {
    ema_pullback: {n: 6, name: "EMA Pullback", verdict: "HISTORICALLY UNPROFITABLE after costs",
      performance: {all_periods: {trades: 5293, win_rate: 0.32, expectancy_r: -0.1028, expectancy_ci95: [-0.1416, -0.0644]}}}}}},
  notes: ["All bank strategies are EXPERIMENTAL."],
};

test("live columns show recorded statistics only, Pending when nothing has resolved", () => {
  const rows = bankRows(REPORT);
  assert.deepEqual(rows.map(r => [r.name, r.signals, r.winRate, r.expectancy]), [
    ["Trendline Break & Retest", 44, "18%", "-0.42R"], ["EMA Pullback", 0, null, null], ["VWAP Reversion", null, null, null]]);
  const html = bankPanel(REPORT);
  assert.match(html, /EMA Pullback<\/td><td>Experimental · not running<\/td><td>0<\/td><td><span class="gd-na">Pending<\/span><\/td><td><span class="gd-na">Pending<\/span>/);
  assert.match(html, /VWAP Reversion is unsupported/);
  assert.match(html, /18%/);
});

test("historical backtests are separate and labelled as simulated", () => {
  const html = bankPanel(REPORT);
  assert.match(html, /HISTORICAL BACKTEST \(simulated, not live results\)/);
  assert.match(html, /not live results and do not count toward the live statistics/);
  const hist = historicalRows(REPORT);
  assert.deepEqual(hist.map(r => [r.name, r.trades, r.expectancy]), [["EMA Pullback", 5293, "-0.10R"]]);
  // The backtest's -0.10R must not leak into the live EMA Pullback row.
  assert.equal(bankRows(REPORT).find(r => r.key === "ema_pullback").expectancy, null);
});

test("status reflects whether the bank is actually running", () => {
  assert.equal(bankStatus({status: "EXPERIMENTAL"}, {enabled: false}), "Experimental · not running");
  assert.equal(bankStatus({status: "EXPERIMENTAL"}, {enabled: true, running: true}), "Monitoring · experimental");
  assert.equal(bankStatus({status: "LINKED"}, {}), "Monitoring · live production strategy");
  assert.match(bankPanel(null), /unavailable/);
});
