// Single-loop poller for Market Radar.
// start() runs the task once, then schedules exactly one interval. A newer
// start() or a stop() bumps the generation, so an older start that is still
// awaiting its first task can never create a second timer afterwards.
// A tick is skipped while the previous refresh is still running, so a slow
// engine (a radar scan can exceed 10s) never gets overlapping requests.
export function createPoller({task,intervalMs=10000,schedule=(fn,ms)=>setInterval(fn,ms),cancel=id=>clearInterval(id)}){
  let timer=null,generation=0,pending=null;
  const run=isCurrent=>{
    const p=Promise.resolve().then(()=>task(isCurrent));
    pending=p;
    const settle=()=>{if(pending===p)pending=null;};
    p.then(settle,settle);
    return p;
  };
  const clear=()=>{if(timer!==null){cancel(timer);timer=null;}};
  return {
    async start(){
      clear();
      const gen=++generation,isCurrent=()=>gen===generation;
      await run(isCurrent);
      if(!isCurrent())return;
      timer=schedule(()=>{if(isCurrent()&&!pending)run(isCurrent).catch(()=>{});},intervalMs);
    },
    stop(){generation++;clear();},
    get active(){return timer!==null;},
  };
}
