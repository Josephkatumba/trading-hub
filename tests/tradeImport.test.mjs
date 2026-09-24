import test from "node:test";
import assert from "node:assert/strict";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {parseCSV}=await import("../src/data.js");
const {mergeImportedTrades,tradeOrigin}=await import("../src/tradeImport.mjs");
const {IMPORTED_TRADES}=await import("../src/importedData.js");

const HEADER="Account,Symbol,Type,Open Price,Close Price,Volume,Profit,Time";
const ROW_A="Acct1,EURUSD,buy,1.1000,1.1010,1,10,2026-09-16 09:15:00";
const ROW_B="Acct1,XAUUSD,sell,3350,3340,0.1,100,2026-09-16 14:00:00";
const ROW_C="Acct1,GBPUSD,buy,1.3000,1.2990,1,-10,2026-09-17 10:00:00";
const csv=(...rows)=>[HEADER,...rows].join("\n");
const imp=(text,existing=[])=>mergeImportedTrades(existing,parseCSV(text,{sourceTimeZone:"UTC"}));

test("1. first import adds every row with deterministic IDs", () => {
  const first=imp(csv(ROW_A,ROW_B));
  assert.equal(first.added,2);
  assert.equal(first.trades.length,2);
  assert.deepEqual(parseCSV(csv(ROW_A,ROW_B)).map(t=>t.id),parseCSV(csv(ROW_A,ROW_B)).map(t=>t.id));
  assert.ok(first.trades.every(t=>t.origin==="import"&&t.id.startsWith("IMP-")));
});

test("2. importing the same file twice does not duplicate", () => {
  const first=imp(csv(ROW_A,ROW_B)),second=imp(csv(ROW_A,ROW_B),first.trades);
  assert.equal(second.added,0);
  assert.equal(second.skippedExistingId,2);
  assert.equal(second.trades.length,2);
  assert.deepEqual(second.trades.map(t=>t.id),first.trades.map(t=>t.id));
});

test("row order and trailing whitespace do not change IDs (no length/header fingerprint)", () => {
  const first=imp(csv(ROW_A,ROW_B)),reordered=imp(csv(ROW_B,ROW_A)+"\n\n",first.trades);
  assert.equal(reordered.added,0);
});

test("3. overlapping files only add the non-overlapping rows", () => {
  const first=imp(csv(ROW_A,ROW_B)),overlap=imp(csv(ROW_B,ROW_C),first.trades);
  assert.equal(overlap.added,1);
  assert.equal(overlap.trades.length,3);
  assert.equal(overlap.trades[0].symbol,"GBPUSD");
});

test("identical rows inside one file are distinct trades (partial fills) and still dedupe on re-import", () => {
  const first=imp(csv(ROW_A,ROW_A));
  assert.equal(first.added,2);
  assert.notEqual(first.trades[0].id,first.trades[1].id);
  assert.equal(imp(csv(ROW_A,ROW_A),first.trades).added,0);
  // a later file with a third identical fill adds exactly one
  assert.equal(imp(csv(ROW_A,ROW_A,ROW_A),first.trades).added,1);
});

test("4. a file containing existing IDs keeps the existing records unchanged", () => {
  const existing=[{id:"CUSTOM-1",account:"Acct1",symbol:"EURUSD",side:"BUY",entry:1.1,exit:1.101,volume:1,pnl:10,time:"2026-09-16 09:15:00",note:"keep me",origin:"import"}];
  const withIds="Id,"+HEADER+"\nCUSTOM-1,Acct1,EURUSD,buy,1.1,1.2,1,999,2026-09-16 09:15:00\nCUSTOM-2,"+ROW_C;
  const merged=imp(withIds,existing);
  assert.equal(merged.added,1);
  assert.equal(merged.skippedExistingId,1);
  const kept=merged.trades.find(t=>t.id==="CUSTOM-1");
  assert.equal(kept.pnl,10);
  assert.equal(kept.note,"keep me");
  assert.ok(merged.trades.some(t=>t.id==="CUSTOM-2"));
});

test("broker ticket/position column gives a stable ID", () => {
  const withTicket="Position,"+HEADER+"\n555,"+ROW_A;
  const first=imp(withTicket);
  assert.match(first.trades[0].id,/^IMP-T-/);
  assert.equal(imp(withTicket,first.trades).added,0);
});

test("legacy imports stored under the old ID scheme are matched by content", () => {
  const legacy=parseCSV(csv(ROW_A)).map(t=>({...t,id:"IMP-1790000000000-0"}));
  const merged=imp(csv(ROW_A,ROW_C),legacy);
  assert.equal(merged.added,1);
  assert.equal(merged.skippedDuplicateContent,1);
  assert.ok(merged.trades.some(t=>t.id==="IMP-1790000000000-0"));
});

test("5. genuinely new trades are added and bundled sample records are kept separate", () => {
  const merged=imp(csv(ROW_C),IMPORTED_TRADES);
  assert.equal(merged.added,1);
  assert.equal(merged.sampleExcluded,IMPORTED_TRADES.length);
  assert.ok(merged.trades.every(t=>tradeOrigin(t)==="import"));
  assert.ok(IMPORTED_TRADES.every(t=>tradeOrigin(t)==="sample"));
  assert.ok(tradeOrigin({id:"TH-001"})==="sample");
});

test("import stamps the chosen broker timezone and classifies from UTC", () => {
  const [t]=parseCSV(csv("Acct1,EURUSD,buy,1.1,1.2,1,10,2026-09-16 15:24:43"),{sourceTimeZone:"Europe/Athens"});
  assert.equal(t.source_timezone,"Europe/Athens");
  assert.equal(t.time,"2026-09-16 15:24:43");
  assert.equal(t.time_utc,"2026-09-16T12:24:43.000Z");
  assert.equal(t.session,"London");
  const [u]=parseCSV(csv(ROW_A));
  assert.equal(u.session,"Unverified");
  const [e]=parseCSV("Session,"+HEADER+"\nTokyo,"+ROW_A);
  assert.equal(e.session,"Tokyo");
  assert.equal(e.session_source,"export");
});

test("rows without a timestamp are not given a fabricated time", () => {
  const [t]=parseCSV("Symbol,Type,Profit\nEURUSD,buy,5");
  assert.equal(t.time,"");
  assert.equal(t.time_status,"MISSING");
  assert.equal(t.session,"Unverified");
});
