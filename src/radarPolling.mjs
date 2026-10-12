// Single-loop poller for Market Radar.
// start() runs the task once, then schedules exactly one interval. A newer
// start() or a stop() bumps the generation, so an older start that is still
// awaiting its first task can never create a second timer afterwards.
// A tick is skipped while the previous refresh is still running, so a slow
// engine (a radar scan can exceed 10s) never gets overlapping requests.
// Ticks are also skipped while the document is hidden (background tab); when
// it becomes visible again the task runs at once, then the interval continues.
const documentHidden=()=>typeof document!=="undefined"&&document.visibilityState==="hidden";
function watchDocumentVisibility(onChange){
  if(typeof document==="undefined"||typeof document.addEventListener!=="function")return ()=>{};
  document.addEventListener("visibilitychange",onChange);
  return ()=>document.removeEventListener("visibilitychange",onChange);
}
export function createPoller({task,intervalMs=10000,schedule=(fn,ms)=>setInterval(fn,ms),cancel=id=>clearInterval(id),
  isHidden=documentHidden,watchVisibility=watchDocumentVisibility}){
  let timer=null,generation=0,pending=null,unwatch=null;
  const run=isCurrent=>{
    const p=Promise.resolve().then(()=>task(isCurrent));
    pending=p;
    const settle=()=>{if(pending===p)pending=null;};
    p.then(settle,settle);
    return p;
  };
  const tick=isCurrent=>{if(isCurrent()&&!pending&&!isHidden())run(isCurrent).catch(()=>{});};
  const clear=()=>{
    if(timer!==null){cancel(timer);timer=null;}
    if(unwatch){unwatch();unwatch=null;}
  };
  return {
    async start(){
      clear();
      const gen=++generation,isCurrent=()=>gen===generation;
      await run(isCurrent);
      if(!isCurrent())return;
      timer=schedule(()=>tick(isCurrent),intervalMs);
      unwatch=watchVisibility(()=>tick(isCurrent));
    },
    stop(){generation++;clear();},
    get active(){return timer!==null;},
  };
}

// The engine's radar is the autonomous scanner's latest result. Its scan key
// changes only when a new scan completed, so history/performance requests are
// made once per scan instead of every poll. null (an engine without scan
// metadata) means "unknown": refresh every poll, as before.
export function scanKey(radar){
  const scan=radar?.scan;
  if(!scan||scan.sequence==null)return null;
  return String(scan.sequence)+"|"+String(scan.completed_at||"");
}

// Whether the history requests (performance, setup episodes, outcomes) are due.
export function historyDue(radar,lastKey){
  const key=scanKey(radar);
  return key===null||key!==lastKey;
}

// Setup ids whose outcomes the archive needs: closed episodes that were confirmed.
export function archiveOutcomeIds(episodes,limit=200){
  const ids=[];
  for(const row of episodes?.closed||[]){
    const id=row?.setup_id;
    if(id&&row.confirmation&&!ids.includes(String(id)))ids.push(String(id));
  }
  return ids.slice(0,limit);
}

// "Updated …" text for a live radar: when the scan completed, and whether it is stale.
export function scanFreshnessText(scan,nowText,timeText=iso=>new Date(iso).toLocaleTimeString()){
  if(!scan?.completed_at)return "Updated "+nowText;
  const text="Scanned "+timeText(scan.completed_at);
  if(scan.status!=="STALE")return text;
  const minutes=Math.round(Number(scan.age_seconds||0)/60);
  return text+" · stale ("+minutes+" min old)";
}
