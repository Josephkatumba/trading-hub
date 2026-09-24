const KEY="th_engine_url";
// Canonical local engine address. Must match backend/start_engine.bat and the READMEs.
export const DEFAULT_ENGINE_URL="http://127.0.0.1:8000";
// A previous build silently rewrote saved :8000 URLs to this value. Nothing else
// ever wrote it (setEngineUrl has no UI yet), so it is app-written, not a user choice.
const LEGACY_APP_WRITTEN_URLS=new Set(["http://127.0.0.1:8010","http://localhost:8010"]);

export function getEngineUrl(){
  try{
    const saved=String(localStorage.getItem(KEY)||"").trim().replace(/\/$/,"");
    if(LEGACY_APP_WRITTEN_URLS.has(saved)){
      localStorage.removeItem(KEY);
      return DEFAULT_ENGINE_URL;
    }
    return saved||DEFAULT_ENGINE_URL;
  }catch{return DEFAULT_ENGINE_URL;}
}

export function setEngineUrl(url){
  const clean=String(url||"").trim().replace(/\/$/,"");
  try{if(clean)localStorage.setItem(KEY,clean);else localStorage.removeItem(KEY);}catch{}
  return clean;
}

export async function engineFetch(path,options={}){
  const base=getEngineUrl();
  return fetch(base+path,{...options,headers:{"Accept":"application/json",...(options.headers||{})}}).then(async response=>{
    if(!response.ok) throw new Error("Engine request failed: "+response.status);
    return response.json();
  });
}
