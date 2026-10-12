import {migrateJournalKeys} from "./sampleRedaction.mjs";
import {cloudActive,cloudObject,cloudWrite,authRequired} from "./userJournal.mjs";
const KEY="th_journal_v1";

const DEFAULT_RULES=[
  "Wait for a clear setup before entering",
  "Confirm the setup with structure/support or resistance",
  "Keep risk inside the planned limit",
  "Do not revenge trade after a loss"
];

export function getJournal(){
  if(cloudActive())return cloudObject("review");
  if(authRequired())return {};
  try{
    const {journal,changed}=migrateJournalKeys(JSON.parse(localStorage.getItem(KEY)||"{}"));
    if(changed)localStorage.setItem(KEY,JSON.stringify(journal));
    return journal;
  }
  catch{return {};}
}

export function getReview(id){
  return getJournal()[id]||{rules:[],setup:"",grade:"",notes:""};
}

export function saveReview(id,review){
  if(cloudActive())return cloudWrite("review",id,{...getReview(id),...review,updatedAt:new Date().toISOString()});
  if(authRequired())throw new Error("Sign in required");
  const all=getJournal();
  all[id]={...getReview(id),...review,updatedAt:new Date().toISOString()};
  localStorage.setItem(KEY,JSON.stringify(all));
}

export function reviewedCount(){
  return Object.values(getJournal()).filter(x=>x.notes||x.grade||x.setup||x.rules?.length).length;
}

export {DEFAULT_RULES};
