import {migrateJournalKeys} from "./sampleRedaction.mjs";
const KEY="th_journal_v1";

const DEFAULT_RULES=[
  "Wait for a clear setup before entering",
  "Confirm the setup with structure/support or resistance",
  "Keep risk inside the planned limit",
  "Do not revenge trade after a loss"
];

export function getJournal(){
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
  const all=getJournal();
  all[id]={...getReview(id),...review,updatedAt:new Date().toISOString()};
  localStorage.setItem(KEY,JSON.stringify(all));
}

export function reviewedCount(){
  return Object.values(getJournal()).filter(x=>x.notes||x.grade||x.setup||x.rules?.length).length;
}

export {DEFAULT_RULES};
