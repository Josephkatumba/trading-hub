import test from "node:test";
import assert from "node:assert/strict";
import { evidenceNote, money, notifiable, safetyBanner, signed } from "../src/scalper/scalperModel.mjs";

test("formatting", () => {
  assert.equal(money(-1234.5, "USD"), "−USD 1,234.50");
  assert.equal(signed(2), "+2.00");
  assert.equal(signed(null), "–");
});

test("safety banner never claims demo without the cBot's verification", () => {
  assert.equal(safetyBanner({}).level, "info");
  assert.equal(safetyBanner({ account: { demo_verified: false, verification: "x" } }).level, "serious");
  assert.equal(safetyBanner({ account: { demo_verified: true }, live_account_ever_seen: true }).level, "critical");
  assert.equal(safetyBanner({ account: { demo_verified: true, verification: "ok", account: "***1" } }).level, "good");
});

test("only executions and risk events notify", () => {
  const n = notifiable([
    { event: "signal", decision: "skipped" },
    { event: "signal", decision: "opened", side: "buy", symbol: "XAUUSD", run_id: "r", position_id: 1, ts: "t" },
    { event: "close", symbol: "XAUUSD", net: -5, run_id: "r", position_id: 1, ts: "t2" },
  ]);
  assert.equal(n.length, 2);
  assert.match(n[1].title, /−5.00/);
});

test("evidence note scales with sample size", () => {
  assert.match(evidenceNote(5), /far too few/);
  assert.match(evidenceNote(50), /early/);
});
