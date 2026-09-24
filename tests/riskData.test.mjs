import test from "node:test";
import assert from "node:assert/strict";
import {averageR, formatR, hasRecordedR, hasRecordedRisk} from "../src/riskData.mjs";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {calculateMetrics,getTradeContext,parseCSV}=await import("../src/data.js");
const {analyzeBehavior,behaviorSummary}=await import("../src/behavior.js");
const {answerQuestion}=await import("../src/coach.js");
const {IMPORTED_TRADES}=await import("../src/importedData.js");

test("zero or missing risk is unavailable, never zero risk", () => {
  assert.equal(hasRecordedRisk({risk:0}),false);
  assert.equal(hasRecordedRisk({risk:null}),false);
  assert.equal(hasRecordedRisk({}),false);
  assert.equal(hasRecordedRisk({risk:120}),true);
});

test("R counts only when backed by risk or explicitly non-zero", () => {
  assert.equal(hasRecordedR({r:0,risk:0}),false);
  assert.equal(hasRecordedR({r:null,risk:100}),false);
  assert.equal(hasRecordedR({r:0,risk:100}),true);      // genuine breakeven
  assert.equal(hasRecordedR({r:1.5}),true);
  assert.deepEqual(averageR([{r:0,risk:0},{r:2},{r:-1,risk:50}]),{value:0.5,count:2,total:3});
  assert.equal(averageR([{r:0,risk:0}]).value,null);
  assert.equal(formatR(null),"Unavailable");
  assert.equal(formatR(0.5),"+0.50R");
});

test("bundled trades (risk 0, r 0) report unavailable R and risk, raw fields untouched", () => {
  assert.ok(IMPORTED_TRADES.every(t=>t.risk===0&&t.r===0));
  const m=calculateMetrics(IMPORTED_TRADES);
  assert.equal(m.avgR,null);
  assert.equal(m.rCoverage,0);
  assert.equal(m.riskCoverage,0);
  assert.equal(getTradeContext(IMPORTED_TRADES[0],IMPORTED_TRADES).avgRisk,0);
  assert.equal(getTradeContext(IMPORTED_TRADES[0],IMPORTED_TRADES).symbolAvgR,null);
  const b=analyzeBehavior(IMPORTED_TRADES);
  assert.equal(behaviorSummary(b).riskConsistency,"Unavailable");
  assert.ok(answerQuestion("Am I risking consistently?",IMPORTED_TRADES).facts.some(f=>/initial stop loss/.test(f)));
});

test("recorded R is averaged only over trades that have it", () => {
  const trades=[{pnl:100,r:2,risk:50,time:"a"},{pnl:-10,r:0,risk:0,time:"b"}];
  const m=calculateMetrics(trades);
  assert.equal(m.avgR,2);
  assert.equal(m.rCoverage,1);
});

test("CSV without risk/R columns keeps them null instead of 0", () => {
  const [t]=parseCSV("Symbol,Type,Profit,Time\nEURUSD,buy,5,2026-09-16 10:00");
  assert.equal(t.risk,null);
  assert.equal(t.r,null);
  const [u]=parseCSV("Symbol,Type,Profit,Risk,R\nEURUSD,buy,5,50,0.1");
  assert.equal(u.risk,50);
  assert.equal(u.r,0.1);
});
