import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {analyzeBehavior}=await import("../src/behavior.js");
const {renderAnalytics,renderInsights}=await import("../src/behaviorView.js");
const {IMPORTED_TRADES}=await import("../src/importedData.js");
const {calculateMetrics}=await import("../src/data.js");

test("behaviour analysis returns its machine flags (Setup Lab / Analyst pages render)", () => {
  const b=analyzeBehavior(IMPORTED_TRADES);
  assert.ok(Array.isArray(b.flags) && b.flags.length > 0);
  const m=calculateMetrics(IMPORTED_TRADES);
  assert.match(renderAnalytics(IMPORTED_TRADES,m), /Your trading fingerprint/);
  assert.match(renderInsights(IMPORTED_TRADES,m), /Trading Analyst/);
});
