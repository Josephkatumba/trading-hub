import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {equityCurve,calculateMetrics}=await import("../src/data.js");
const {IMPORTED_TRADES}=await import("../src/importedData.js");

// The previous O(n^2) implementation, kept verbatim as the reference.
const reference=ordered=>ordered.map((t,i)=>({i,pnl:Number(t.pnl)||0,equity:ordered.slice(0,i+1).reduce((s,x)=>s+(Number(x.pnl)||0),0)}));

test("matches the previous implementation exactly on the bundled data", () => {
  const ordered=[...IMPORTED_TRADES].sort((a,b)=>String(a.time).localeCompare(String(b.time)));
  assert.deepStrictEqual(equityCurve(ordered),reference(ordered));
  assert.deepStrictEqual(calculateMetrics(IMPORTED_TRADES).equityCurve,reference(ordered));
});

test("bit-identical on random floats, strings, nulls and NaN", () => {
  let seed=42;const rnd=()=>(seed=(seed*1103515245+12345)%2147483648)/2147483648;
  const odd=[null,undefined,"12.5","abc",NaN,"",0,-0];
  const rows=Array.from({length:2000},(_,i)=>({pnl:i%97===0?odd[i%odd.length]:(rnd()-0.5)*1000/(1+rnd()*7)}));
  const fast=equityCurve(rows),slow=reference(rows);
  assert.equal(fast.length,slow.length);
  for(let i=0;i<fast.length;i++)assert.ok(Object.is(fast[i].equity,slow[i].equity)&&Object.is(fast[i].pnl,slow[i].pnl)&&fast[i].i===i,"mismatch at "+i);
});

test("known values and empty input", () => {
  assert.deepStrictEqual(equityCurve([]),[]);
  assert.deepStrictEqual(equityCurve([{pnl:10},{pnl:-4},{pnl:"2"}]).map(x=>x.equity),[10,6,8]);
});

test("scales linearly (20k trades well under a second)", () => {
  const rows=Array.from({length:20000},(_,i)=>({pnl:i%3-1}));
  const started=performance.now();equityCurve(rows);
  assert.ok(performance.now()-started<1000);
});
