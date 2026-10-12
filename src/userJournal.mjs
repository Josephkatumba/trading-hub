import {engineFetch,getEngineUrl} from "./engine.js";
export const identityState={user:null,csrf:null,entitlements:null,ready:false};
export const authRequired=()=>import.meta.env?.VITE_AUTH_REQUIRED==="1";
const records={trade:new Map(),review:new Map(),account:new Map()};
export const cloudActive=()=>Boolean(identityState.user);
export const cloudRows=kind=>[...records[kind].values()].map(r=>r.payload);
export const cloudObject=kind=>Object.fromEntries([...records[kind]].map(([id,r])=>[id,r.payload]));
export async function initIdentity(){
  try{
    const me=await engineFetch("/api/auth/me");Object.assign(identityState,me);
    await Promise.all(Object.keys(records).map(async kind=>{
      records[kind].clear();let cursor="";
      do{const page=await engineFetch(`/api/journal/${kind}?cursor=${encodeURIComponent(cursor)}`);
        for(const r of page.records)records[kind].set(r.id,r);cursor=page.next_cursor;
      }while(cursor);
    }));
  }catch(error){
    identityState.user=null;identityState.csrf=null;identityState.entitlements=null;
    for(const map of Object.values(records))map.clear();
    if(error.status!==401&&authRequired())throw error;
  }finally{identityState.ready=true;}
  return identityState;
}
export async function cloudWrite(kind,id,payload){
  if(!cloudActive())throw new Error("Sign in required");
  const old=records[kind].get(String(id));
  const saved=await engineFetch(`/api/journal/${kind}/${encodeURIComponent(id)}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({payload,version:old?.version||0})});
  records[kind].set(String(id),saved);return saved;
}
export async function saveCloudTrades(trades){
  // No destructive replacement: an import updates its own IDs and preserves remote history.
  for(const t of trades){
    if(t.account&&!records.account.has(t.account))await cloudWrite("account",t.account,{name:t.account});
    if(JSON.stringify(records.trade.get(String(t.id))?.payload)!==JSON.stringify(t))await cloudWrite("trade",String(t.id),t);
  }
}
export function signIn(){location.assign(getEngineUrl()+"/api/auth/login");}
export async function signOut(){
  await engineFetch("/api/auth/logout",{method:"POST"});
  for(const map of Object.values(records))map.clear();
  identityState.user=null;identityState.csrf=null;identityState.entitlements=null;location.reload();
}
