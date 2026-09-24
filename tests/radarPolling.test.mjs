import test from "node:test";
import assert from "node:assert/strict";
import {createPoller} from "../src/radarPolling.mjs";

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
  t.tick();t.tick();
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
