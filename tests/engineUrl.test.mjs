import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

function memoryStorage(initial={}){
  const map=new Map(Object.entries(initial));
  return {getItem:k=>map.has(k)?map.get(k):null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k),map};
}
globalThis.localStorage=memoryStorage();
const {getEngineUrl,DEFAULT_ENGINE_URL}=await import("../src/engine.js");

test("default engine URL is the canonical port 8000", () => {
  globalThis.localStorage=memoryStorage();
  assert.equal(DEFAULT_ENGINE_URL,"http://127.0.0.1:8000");
  assert.equal(getEngineUrl(),"http://127.0.0.1:8000");
});

test("a saved :8000 URL is kept as-is (no 8000 -> 8010 rewrite)", () => {
  globalThis.localStorage=memoryStorage({th_engine_url:"http://127.0.0.1:8000"});
  assert.equal(getEngineUrl(),"http://127.0.0.1:8000");
  assert.equal(localStorage.getItem("th_engine_url"),"http://127.0.0.1:8000");
});

test("the app-written legacy :8010 value is cleared back to the default", () => {
  globalThis.localStorage=memoryStorage({th_engine_url:"http://127.0.0.1:8010/"});
  assert.equal(getEngineUrl(),"http://127.0.0.1:8000");
  assert.equal(localStorage.getItem("th_engine_url"),null);
});

test("a user-chosen remote URL is respected and only trailing slash trimmed", () => {
  globalThis.localStorage=memoryStorage({th_engine_url:"https://engine.example.com/"});
  assert.equal(getEngineUrl(),"https://engine.example.com");
});

test("startup script, stop script and READMEs all use port 8000 and no 8010 remains", () => {
  const read=p=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
  assert.match(read("backend/start_engine.bat"),/--port 8000\b/);
  assert.match(read("STOP TRADING HUB.bat"),/:8000/);
  assert.match(read("backend/README.md"),/127\.0\.0\.1:8000\/api\/health/);
  for(const p of ["backend/start_engine.bat","STOP TRADING HUB.bat","START TRADING HUB.bat","backend/README.md","README.md","backend/main.py"])
    assert.doesNotMatch(read(p),/8010/,p+" still references 8010");
});
