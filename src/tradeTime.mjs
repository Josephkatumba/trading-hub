// Single normalization path for imported trade timestamps.
//
// MT5 exports broker/server wall-clock time, not UTC. This mirrors the backend
// rule in backend/market_time.py (normalize_mt5_epoch): the source time basis
// must be explicit (an IANA zone such as "Europe/Athens", or "UTC"). An unset
// basis is UNVERIFIED and is never silently treated as UTC; wall times that do
// not exist or are ambiguous in the basis zone (DST transitions) are rejected
// rather than guessed. The raw timestamp string is always preserved.

// Existing trade-session definitions (previously inside data.js inferSession),
// now applied to the UTC instant instead of the raw broker wall clock.
export const SESSION_WINDOWS_UTC=[
  {name:"London",startHour:8,endHour:13},
  {name:"New York",startHour:13,endHour:18},
];
export const FALLBACK_SESSION="Asia";
export const UNVERIFIED_SESSION="Unverified";

const WALL_TIME=/^(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/i;

function parseWallTime(raw){
  const m=WALL_TIME.exec(String(raw??"").trim());
  if(!m)return null;
  const [,y,mo,d,h,mi,s,offset]=m;
  const parts={year:+y,month:+mo,day:+d,hour:h==null?null:+h,minute:+(mi||0),second:+(s||0),offset:offset||null};
  if(parts.month<1||parts.month>12||parts.day<1||parts.day>31||(parts.hour!=null&&(parts.hour>23||parts.minute>59||parts.second>59)))return null;
  const check=new Date(Date.UTC(parts.year,parts.month-1,parts.day));
  if(check.getUTCDate()!==parts.day)return null;
  return parts;
}

const formatters=new Map();
function zoneFormatter(zone){
  if(!formatters.has(zone))formatters.set(zone,new Intl.DateTimeFormat("en-US",{timeZone:zone,hourCycle:"h23",year:"numeric",month:"numeric",day:"numeric",hour:"numeric",minute:"numeric",second:"numeric"}));
  return formatters.get(zone);
}
export function isValidTimeZone(zone){
  if(!zone||typeof zone!=="string")return false;
  try{zoneFormatter(zone);return true;}catch{return false;}
}
function wallMsInZone(instantMs,zone){
  const p=Object.fromEntries(zoneFormatter(zone).formatToParts(new Date(instantMs)).map(x=>[x.type,x.value]));
  return Date.UTC(+p.year,+p.month-1,+p.day,+p.hour%24,+p.minute,+p.second);
}

// Returns every UTC instant whose wall clock in `zone` equals the given wall time.
function instantsForWallTime(wallMs,zone){
  const offsets=new Set([-86400000,0,86400000].map(delta=>wallMsInZone(wallMs+delta,zone)-(wallMs+delta)));
  const found=new Set();
  for(const offset of offsets){const candidate=wallMs-offset;if(wallMsInZone(candidate,zone)===wallMs)found.add(candidate);}
  return [...found].sort((a,b)=>a-b);
}

export function normalizeTradeTime(raw,sourceTimeZone){
  const basis=String(sourceTimeZone||"").trim();
  const result={raw:raw??null,utc:null,basis:basis||"UNVERIFIED",status:"UNVERIFIED",reason:null};
  const wall=parseWallTime(raw);
  if(raw==null||String(raw).trim()===""){return {...result,status:"MISSING",reason:"TRADE_TIMESTAMP_MISSING"};}
  if(!wall)return {...result,status:"INVALID",reason:"UNPARSEABLE_TRADE_TIMESTAMP"};
  if(wall.hour==null)return {...result,reason:"NO_TIME_OF_DAY"};
  const wallMs=Date.UTC(wall.year,wall.month-1,wall.day,wall.hour,wall.minute,wall.second);
  if(wall.offset){
    const sign=wall.offset[0]==="-"?-1:1,digits=wall.offset.replace(/[^0-9]/g,"");
    const offsetMs=wall.offset.toUpperCase()==="Z"?0:sign*(+digits.slice(0,2)*60+ +digits.slice(2,4))*60000;
    return {...result,utc:new Date(wallMs-offsetMs).toISOString(),basis:"EXPLICIT_OFFSET",status:"VERIFIED",reason:"TIMESTAMP_CARRIES_OFFSET"};
  }
  if(!basis)return {...result,reason:"SOURCE_TIME_BASIS_UNVERIFIED"};
  if(basis.toUpperCase()==="UTC")return {...result,basis:"UTC",utc:new Date(wallMs).toISOString(),status:"VERIFIED",reason:"SOURCE_BASIS_EXPLICIT_UTC"};
  if(!isValidTimeZone(basis))return {...result,reason:"SOURCE_TIME_BASIS_UNKNOWN"};
  const instants=instantsForWallTime(wallMs,basis);
  if(instants.length===0)return {...result,status:"INVALID",reason:"NONEXISTENT_LOCAL_SOURCE_TIME"};
  if(instants.length>1)return {...result,reason:"AMBIGUOUS_LOCAL_SOURCE_TIME"};
  return {...result,utc:new Date(instants[0]).toISOString(),status:"VERIFIED",reason:"SOURCE_BASIS_EXPLICIT_IANA_ZONE"};
}

export function sessionForUtc(utcIso){
  const hour=new Date(utcIso).getUTCHours();
  return SESSION_WINDOWS_UTC.find(w=>hour>=w.startHour&&hour<w.endHour)?.name||FALLBACK_SESSION;
}

export function inferSession(raw,sourceTimeZone){
  const normalized=normalizeTradeTime(raw,sourceTimeZone);
  return normalized.status==="VERIFIED"?sessionForUtc(normalized.utc):UNVERIFIED_SESSION;
}

// Derives time/session provenance for one trade. Pure and idempotent:
// - `time` (raw broker string) and `source_timezone` (stamped at import) are never changed.
// - a session that came from the export itself (`session_source: "export"`) is kept.
// - otherwise the session is re-derived from time + basis; the previously stored
//   label is kept once in `session_recorded` so nothing is silently lost.
export function withTimeProvenance(trade,workspaceTimeZone){
  const basis=trade.source_timezone||workspaceTimeZone||"";
  const n=normalizeTradeTime(trade.time,basis);
  const out={...trade,time_utc:n.utc,time_basis:n.basis,time_status:n.status,time_reason:n.reason};
  if(trade.session_source==="export")return out;
  if(out.session_recorded===undefined&&trade.session!==undefined&&trade.session_source!=="inferred")out.session_recorded=trade.session;
  out.session=n.status==="VERIFIED"?sessionForUtc(n.utc):UNVERIFIED_SESSION;
  out.session_source="inferred";
  return out;
}
