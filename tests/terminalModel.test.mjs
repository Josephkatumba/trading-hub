import test from "node:test";
import assert from "node:assert/strict";
import { ema, rsi, atr, supportResistance, percentileRank, volatilityRegime } from "../src/app/indicators.mjs";
import { lifecycleOf, radarFilter, radarRank, marketStatus, rCurve, rStats, signalOutcome, tradeCurve, pnlSince, strategyTier, signalRows, sortRows, priceDigits } from "../src/app/model.mjs";

test("ema seeds with SMA and returns null before period", () => {
  const out = ema([1, 2, 3, 4, 5], 3);
  assert.deepEqual(out.slice(0, 2), [null, null]);
  assert.equal(out[2], 2);
  assert.equal(out[3], 3);
});

test("rsi is 100 on monotonic rise and null without history", () => {
  assert.equal(rsi([1, 2], 14)[1], null);
  const up = Array.from({ length: 20 }, (_, i) => i + 1);
  assert.equal(rsi(up, 14).at(-1), 100);
});

test("atr uses true range", () => {
  const c = Array.from({ length: 20 }, (_, i) => ({ time: i, open: 10, high: 11, low: 9, close: 10 }));
  assert.equal(atr(c, 14).at(-1), 2);
});

test("support/resistance clusters pivots and labels relative to close", () => {
  const c = [];
  for (let i = 0; i < 60; i++) { const p = 100 + 5 * Math.sin(i / 3); c.push({ time: i, open: p, high: p + 1, low: p - 1, close: p }); }
  const levels = supportResistance(c, { span: 2, tolerance: 0.5 });
  assert.ok(levels.length > 0);
  for (const l of levels) assert.equal(l.type, l.price >= c.at(-1).close ? "RESISTANCE" : "SUPPORT");
});

test("volatility regime from percentile", () => {
  assert.equal(percentileRank([1, 2, 3, 4]), 100);
  assert.equal(volatilityRegime(90), "HIGH");
  assert.equal(volatilityRegime(10), "LOW");
  assert.equal(volatilityRegime(null), "UNKNOWN");
});

test("lifecycle and radar filters", () => {
  assert.equal(lifecycleOf({ state: "DEVELOPING" }), "DEVELOPING");
  assert.equal(lifecycleOf({ lifecycle_state: "CONFIRMED", state: "WATCHING" }), "CONFIRMED");
  assert.equal(lifecycleOf({}), "IDLE");
  const markets = [{ symbol: "A", state: "WATCHING", market_bias: "BULLISH", score: 1 }, { symbol: "B", state: "CONFIRMING", market_bias: "BEARISH", score: 2 }];
  assert.deepEqual(markets.filter(radarFilter("BULLISH")).map(m => m.symbol), ["A"]);
  assert.deepEqual(markets.filter(radarFilter("CONFIRMING")).map(m => m.symbol), ["B"]);
  assert.deepEqual([...markets].sort(radarRank).map(m => m.symbol), ["B", "A"]);
});

test("market status: weekend closed, overlap detected", () => {
  assert.equal(marketStatus(new Date("2026-11-21T12:00:00Z")).fxOpen, false);
  const s = marketStatus(new Date("2026-11-24T13:30:00Z"));
  assert.equal(s.fxOpen, true);
  assert.equal(s.overlap, true);
});

test("signal R curve ignores pending and tracks drawdown", () => {
  const curve = rCurve([
    { outcome_status: "TARGET_HIT", r_multiple: 2, outcome_at: "2026-01-01T00:00:00Z" },
    { outcome_status: "STOP_HIT", r_multiple: -1, outcome_at: "2026-01-02T00:00:00Z" },
    { outcome_status: "PENDING", r_multiple: null, confirmed_at: "2026-01-03T00:00:00Z" },
  ]);
  assert.equal(curve.length, 2);
  assert.equal(curve.at(-1).equity, 1);
  assert.equal(curve.at(-1).drawdown, -1);
  assert.equal(signalOutcome({ outcome_status: "STOP_HIT" }), "LOSS");
  assert.equal(signalOutcome({}), "OPEN");
});

test("rStats", () => {
  const s = rStats([2, -1, -1, 2]);
  assert.equal(s.winRate, 0.5);
  assert.equal(s.profitFactor, 2);
  assert.equal(s.maxDrawdown, 2);
  assert.equal(rStats([]).winRate, null);
});

test("trade curve and trailing P&L", () => {
  const c = tradeCurve([{ time: "2026-11-20 10:00", pnl: 10 }, { time: "2026-11-24 10:00", pnl: -4 }]);
  assert.equal(c.at(-1).equity, 6);
  assert.deepEqual(pnlSince(c, 86400000, Date.parse("2026-11-24T12:00:00Z")), { pnl: -4, trades: 1 });
});

test("strategy tiers never upgrade experimental", () => {
  assert.equal(strategyTier("APPROVED_EXPERIMENTAL"), "EXPERIMENTAL");
  assert.equal(strategyTier("PRODUCTION"), "PRODUCTION");
  assert.equal(strategyTier(undefined), "EXPERIMENTAL");
});

test("signal rows sort with nulls last", () => {
  const rows = signalRows([{ signal_id: "a", confirmed_at: "2026-01-01T00:00:00Z", quality: { score: 10 } }, { signal_id: "b", confirmed_at: "2026-01-02T00:00:00Z" }]);
  assert.deepEqual(sortRows(rows, "score", "desc").map(r => r.id), ["a", "b"]);
  assert.deepEqual(sortRows(rows, "time", "desc").map(r => r.id), ["b", "a"]);
  assert.equal(priceDigits("EURUSD", 1.1), 5);
  assert.equal(priceDigits("X", 1.1, 3), 3);
});

test("open signals have no R", async () => {
  const { signalR } = await import("../src/app/model.mjs");
  assert.equal(signalR({ outcome_status: "PENDING", r_multiple: 0 }), null);
  assert.equal(signalR({ outcome_status: "STOP_HIT", r_multiple: -1 }), -1);
  assert.equal(signalR({ outcome_status: "TARGET_HIT", r_multiple: null }), null);
});

// ── Redesign: lifecycle honesty, breadth, trend strength, evidence ranking ──
import { breadth, trendStrength, assetClass, rankStrategies, isConfirmedStage } from "../src/app/model.mjs";

test("a DETECTED episode on a WATCHING market is shown as WATCHING, never DEVELOPING", () => {
  assert.equal(lifecycleOf({ lifecycle_state: "DETECTED", state: "WATCHING" }), "WATCHING");
  assert.equal(lifecycleOf({ lifecycle_state: "DETECTED", state: "DEVELOPING" }), "DEVELOPING");
  assert.equal(lifecycleOf({ lifecycle_state: "ACTIVE", state: "CONFIRMING" }), "ACTIVE");
  assert.equal(lifecycleOf({ state: "CONFIRMING" }), "CONFIRMING");
  assert.equal(isConfirmedStage(lifecycleOf({ state: "CONFIRMING" })), false);
  assert.equal(isConfirmedStage(lifecycleOf({ lifecycle_state: "CONFIRMED" })), true);
  // a monotonic CONFIRMING episode whose scanner fell back to WATCHING is shown as WATCHING
  assert.equal(lifecycleOf({ lifecycle_state: "CONFIRMING", state: "WATCHING" }), "WATCHING");
});

test("breadth counts bias and lifecycle stages", () => {
  const b = breadth([{ market_bias: "BULLISH", state: "WATCHING" }, { market_bias: "BEARISH", state: "DEVELOPING" }, { market_bias: "RANGE / NEUTRAL", lifecycle_state: "ACTIVE" }]);
  assert.deepEqual([b.bullish, b.bearish, b.neutral, b.total, b.confirmed], [1, 1, 1, 3, 1]);
  assert.equal(b.stages.WATCHING, 1);
  assert.equal(b.stages.ACTIVE, 1);
});

test("trend strength is the EMA spread in ATR, clamped and null without data", () => {
  assert.equal(trendStrength({ ema20: 103, ema50: 100, atr: 1 }), 1);
  assert.equal(trendStrength({ ema20: 100, ema50: 100.75, atr: 1 }), -0.5);
  assert.equal(trendStrength({ ema20: 1 }), null);
  assert.equal(assetClass("BTCUSD"), "Crypto");
  assert.equal(assetClass("XAUUSD"), "Metals");
  assert.equal(assetClass("NAS100"), "Indices");
  assert.equal(assetClass("EURUSD"), "FX");
});

test("strategies rank by evidence tier first, then by the CI lower bound", () => {
  const mk = (name, tier, lo) => ({ name, evidence: { tier }, historical: { all_periods: { expectancy_ci95: [lo, lo + 0.2] } } });
  const order = rankStrategies([mk("a", "SUSPENDED", 0.5), mk("b", "RESEARCH", -0.1), mk("c", "RESEARCH", 0.0), mk("d", "VALIDATED", 0.01)]).map(r => r.name);
  assert.deepEqual(order, ["d", "c", "b", "a"]);
});
