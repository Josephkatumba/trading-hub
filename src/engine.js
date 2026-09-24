const KEY="th_engine_url";
const DEFAULT="http://127.0.0.1:8000";

export function getEngineUrl(){
  try{
    const saved=localStorage.getItem(KEY);
    // Migrate the old local backend port automatically.
    if(saved && /127\.0\.0\.1:8000$/.test(saved)){
      localStorage.setItem(KEY,DEFAULT);
      return DEFAULT;
    }
    return (saved||DEFAULT).replace(/\/$/,"");
  }catch{return DEFAULT;}
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
