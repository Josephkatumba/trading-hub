import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {answerQuestion,sampleResultTitle}=await import("../src/coach.js");

const trade=(pnl,i)=>({id:"T"+i,account:"A",symbol:"EURUSD",side:"BUY",pnl,time:"2026-09-16 1"+i+":00",session:"London"});

test("overview title follows the sign of total P&L", () => {
  assert.equal(answerQuestion("overview",[trade(50,1),trade(-20,2)]).title,"Why the current sample is profitable");
  assert.equal(answerQuestion("overview",[trade(-50,1),trade(20,2)]).title,"Why the current sample is losing");
  assert.equal(answerQuestion("overview",[trade(20,1),trade(-20,2)]).title,"Why the current sample is flat");
  assert.equal(answerQuestion("Why have I been losing?",[trade(10,1)]).title,"Why the current sample is profitable");
});

test("float noise and sub-cent totals read as flat", () => {
  assert.equal(sampleResultTitle(0.1+0.2-0.3),"Why the current sample is flat");
  assert.equal(sampleResultTitle(0.004),"Why the current sample is flat");
  assert.equal(sampleResultTitle(0.01),"Why the current sample is profitable");
  assert.equal(sampleResultTitle(-0.01),"Why the current sample is losing");
});

test("analytical facts are kept", () => {
  const a=answerQuestion("overview",[trade(50,1),trade(-20,2)]);
  assert.match(a.body,/Across 2 executions, total P&L is \+\$30/);
  assert.ok(a.facts.some(f=>f.startsWith("Lowest instrument")));
});
