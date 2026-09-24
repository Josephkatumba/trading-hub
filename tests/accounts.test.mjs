import test from "node:test";
import assert from "node:assert/strict";
import {INITIAL_ACCOUNTS} from "../src/accounts.mjs";

globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
const {IMPORTED_TRADES}=await import("../src/importedData.js");
const {getAccounts}=await import("../src/data.js");

const dataAccounts=new Set(IMPORTED_TRADES.map(t=>t.account));

test("every mapped account exists in the bundled trade data", () => {
  for(const name of Object.keys(INITIAL_ACCOUNTS))assert.ok(dataAccounts.has(name),name+" is mapped but has no trades");
});

test("every account in the bundled trade data has metadata", () => {
  for(const name of dataAccounts)assert.ok(INITIAL_ACCOUNTS[name],name+" has trades but no metadata");
});

test("no balances are invented for accounts whose export has none", () => {
  for(const meta of Object.values(INITIAL_ACCOUNTS))assert.equal(meta.balance,undefined);
});

test("merged account rows carry the mapped platform and status", () => {
  const rows=getAccounts(IMPORTED_TRADES).map(a=>({...a,...(INITIAL_ACCOUNTS[a.name]||{})}));
  assert.equal(rows.length,dataAccounts.size);
  assert.ok(rows.every(a=>a.platform==="MT5"&&a.status==="DEMO"&&a.trades>0));
});
