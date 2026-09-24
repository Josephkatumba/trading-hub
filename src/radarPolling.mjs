// Single-loop poller for Market Radar.
// start() runs the task once, then schedules exactly one interval. A newer
// start() or a stop() bumps the generation, so an older start that is still
// awaiting its first task can never create a second timer afterwards.
export function createPoller({task,intervalMs=10000,schedule=(fn,ms)=>setInterval(fn,ms),cancel=id=>clearInterval(id)}){
  let timer=null,generation=0;
  const clear=()=>{if(timer!==null){cancel(timer);timer=null;}};
  return {
    async start(){
      clear();
      const gen=++generation,isCurrent=()=>gen===generation;
      await task(isCurrent);
      if(!isCurrent())return;
      timer=schedule(()=>{if(isCurrent())task(isCurrent);},intervalMs);
    },
    stop(){generation++;clear();},
    get active(){return timer!==null;},
  };
}
