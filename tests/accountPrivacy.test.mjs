import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {migrateJournalKeys, redactSampleTrade} from "../src/sampleRedaction.mjs";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {IMPORTED_TRADES}=await import("../src/importedData.js");

test("bundled frontend data contains no MT5 login numbers or server names", () => {
  const text=readFileSync(new URL("../src/importedData.js",import.meta.url),"utf8");
  assert.doesNotMatch(text,/333840872|53055259/);
  assert.doesNotMatch(text,/"(login|server)"\s*:/);
  for(const t of IMPORTED_TRADES)assert.doesNotMatch(t.account+" "+t.id,/\d{6,}(?=\D*$)|Demo \d/);
});

test("previously saved sample trades are redacted the same way; imports are untouched", () => {
  const old={id:"MT5-XM Demo 333840872-1157976726-2421",account:"XM Demo 333840872"};
  assert.deepEqual(redactSampleTrade(old),{id:"MT5-XM Demo-1157976726-2421",account:"XM Demo"});
  assert.ok(IMPORTED_TRADES.some(t=>t.id===redactSampleTrade(old).id));
  const imported={id:"IMP-C-abc-0",account:"XM Demo 333840872"};
  assert.equal(redactSampleTrade(imported),imported);
});

test("journal reviews keyed by old sample IDs follow the redacted IDs", () => {
  const {journal,changed}=migrateJournalKeys({"MT5-XM Demo 333840872-1-2":{grade:"A"},"IMP-C-x-0":{grade:"B"}});
  assert.equal(changed,true);
  assert.deepEqual(journal,{"MT5-XM Demo-1-2":{grade:"A"},"IMP-C-x-0":{grade:"B"}});
  assert.equal(migrateJournalKeys(journal).changed,false);
});
