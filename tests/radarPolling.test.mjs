import test from "node:test";
import assert from "node:assert/strict";
import {archiveOutcomeIds, createPoller, historyDue, scanFreshnessText, scanKey} from "../src/radarPolling.mjs";

function fakeTimers(){
  const live=new Map();let next=1;
  return {live,schedule:(fn,ms)=>{const id=next++;live.set(id,{fn,ms});return id;},cancel:id=>live.delete(id),tick(){for(const {fn} of [...live.values()])fn();}};
}
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test("start runs once immediately, then keeps exactly one 10s interval", async () => {
  const t=fakeTimers();let calls=0;
  const poller=createPoller({task:async()=>{calls++;},schedule:t.schedule,cancel:t.cancel});
  await poller.start();
  assert.equal(calls,1);
  assert.equal(t.live.size,1);
  assert.equal([...t.live.values()][0].ms,10000);
  const settle=()=>new Promise(r=>setImmediate(r));
  t.tick();await settle();t.tick();await settle();
  assert.equal(calls,3);
});

test("stop clears the interval (navigating away)", async () => {
  const t=fakeTimers();let calls=0;
  const poller=createPoller({task:async()=>{calls++;},schedule:t.schedule,cancel:t.cancel});
  await poller.start();
  poller.stop();
  assert.equal(t.live.size,0);
  assert.equal(poller.active,false);
  t.tick();
  assert.equal(calls,1);
});

test("returning to Radar creates exactly one loop, even after repeated visits", async () => {
  const t=fakeTimers();
  const poller=createPoller({task:async()=>{},schedule:t.schedule,cancel:t.cancel});
  for(let i=0;i<5;i++){await poller.start();poller.stop();}
  await poller.start();await poller.start();
  assert.equal(t.live.size,1);
});

test("overlapping starts while the first fetch is in flight do not leak a timer", async () => {
  const t=fakeTimers();const first=deferred();let n=0;
  const poller=createPoller({task:()=>(++n===1?first.promise:Promise.resolve()),schedule:t.schedule,cancel:t.cancel});
  const a=poller.start();
  const b=poller.start();
  await b;
  first.resolve();await a;
  assert.equal(t.live.size,1);
});

test("stop during the first in-flight fetch prevents the interval from starting", async () => {
  const t=fakeTimers();const first=deferred();
  const poller=createPoller({task:()=>first.promise,schedule:t.schedule,cancel:t.cancel});
  const started=poller.start();
  poller.stop();
  first.resolve();await started;
  assert.equal(t.live.size,0);
});

test("the task can tell when its result is stale", async () => {
  const t=fakeTimers();const first=deferred();let staleSeen=null;
  const poller=createPoller({task:async isCurrent=>{await first.promise;staleSeen=!isCurrent();},schedule:t.schedule,cancel:t.cancel});
  const started=poller.start();poller.stop();first.resolve();await started;
  assert.equal(staleSeen,true);
});

test("a tick is skipped while the previous refresh is still running (no pile-up)", async () => {
  const t=fakeTimers();const slow=deferred();let calls=0;
  const settle=()=>new Promise(r=>setImmediate(r));
  const poller=createPoller({task:()=>{calls++;return calls===2?slow.promise:Promise.resolve();},schedule:t.schedule,cancel:t.cancel});
  await poller.start();                       // call 1
  t.tick();await settle();                    // call 2 starts and hangs
  t.tick();await settle();t.tick();await settle();   // skipped while call 2 is pending
  assert.equal(calls,2);
  slow.resolve();await settle();
  t.tick();await settle();                    // call 3
  assert.equal(calls,3);
});

// ----- Phase A: hidden tabs, once-per-scan history, scoped outcomes -------------------
function fakeVisibility(hidden=false){
  const listeners=new Set();
  return {isHidden:()=>hidden,watchVisibility:fn=>{listeners.add(fn);return ()=>listeners.delete(fn);},
    set(value){hidden=value;for(const fn of [...listeners])fn();},listeners};
}

test("a hidden document skips ticks; becoming visible refreshes at once", async () => {
  const t=fakeTimers(),v=fakeVisibility();let calls=0;
  const settle=()=>new Promise(r=>setImmediate(r));
  const poller=createPoller({task:async()=>{calls++;},schedule:t.schedule,cancel:t.cancel,isHidden:v.isHidden,watchVisibility:v.watchVisibility});
  await poller.start();
  assert.equal(calls,1);
  v.set(true);await settle();                 // hiding never triggers a request
  t.tick();await settle();t.tick();await settle();
  assert.equal(calls,1,"no polling while hidden");
  v.set(false);await settle();
  assert.equal(calls,2,"visible again: immediate refresh");
  t.tick();await settle();
  assert.equal(calls,3,"then the interval continues");
});

test("stop removes the visibility listener", async () => {
  const t=fakeTimers(),v=fakeVisibility();let calls=0;
  const poller=createPoller({task:async()=>{calls++;},schedule:t.schedule,cancel:t.cancel,isHidden:v.isHidden,watchVisibility:v.watchVisibility});
  await poller.start();
  assert.equal(v.listeners.size,1);
  await poller.start();
  assert.equal(v.listeners.size,1,"a restart never stacks listeners");
  poller.stop();
  assert.equal(v.listeners.size,0);
  v.set(false);
  assert.equal(calls,2);
});

test("history requests are due once per completed engine scan", () => {
  const radar=(sequence,completed_at="2026-10-05T06:00:00+00:00")=>({scan:{sequence,completed_at}});
  assert.equal(scanKey(radar(4)),"4|2026-10-05T06:00:00+00:00");
  assert.equal(historyDue(radar(4),null),true);
  assert.equal(historyDue(radar(4),scanKey(radar(4))),false,"same scan: nothing new to fetch");
  assert.equal(historyDue(radar(5),scanKey(radar(4))),true,"a new scan completed");
  assert.equal(historyDue(radar(1,"2026-10-05T07:00:00+00:00"),scanKey(radar(1))),true,"engine restart");
  assert.equal(scanKey({}),null);
  assert.equal(historyDue({},"anything"),true,"an engine without scan metadata refreshes every poll");
});

test("archive outcomes are requested only for closed confirmed setups", () => {
  const episodes={current:[{setup_id:"c1",confirmation:{}}],confirmed:[{setup_id:"k1",confirmation:{}}],
    closed:[{setup_id:"a",confirmation:{observation_id:"o"}},{setup_id:"b"},{setup_id:"a",confirmation:{}},{confirmation:{}}]};
  assert.deepEqual(archiveOutcomeIds(episodes),["a"]);
  assert.deepEqual(archiveOutcomeIds(null),[]);
  const many={closed:Array.from({length:250},(_,i)=>({setup_id:"s"+i,confirmation:{}}))};
  assert.equal(archiveOutcomeIds(many).length,200,"bounded like the engine's setup_ids limit");
});

test("the updated label shows when the scan completed and flags stale data", () => {
  const time=()=>"09:00:00";
  assert.equal(scanFreshnessText(null,"10:00:00",time),"Updated 10:00:00");
  assert.equal(scanFreshnessText({completed_at:"x",status:"FRESH"},"10:00:00",time),"Scanned 09:00:00");
  assert.equal(scanFreshnessText({completed_at:"x",status:"STALE",age_seconds:600},"10:00:00",time),"Scanned 09:00:00 · stale (10 min old)");
});
