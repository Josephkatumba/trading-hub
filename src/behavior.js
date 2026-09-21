import {getJournal} from "./journal.js";

const avg=xs=>xs.length?xs.reduce((s,x)=>s+x,0)/xs.length:0;
const pct=(n,d=1)=>Number(n||0).toFixed(d)+"%";

function bucket(trades,key){
  const map=new Map();
  trades.forEach(t=>{
    const value=t[key]||"Unknown";
    if(!map.has(value))map.set(value,[]);
    map.get(value).push(t);
  });
  return [...map.entries()].map(([name,items])=>{
    const pnl=items.reduce((s,t)=>s+(Number(t.pnl)||0),0);
    const wins=items.filter(t=>Number(t.pnl)>0).length;
    return {name,trades:items.length,pnl,winRate:items.length?wins/items.length*100:0,avgR:avg(items.map(t=>Number(t.r)||0))};
  }).sort((a,b)=>b.pnl-a.pnl);
}

function pairBuckets(trades,a,b){
  return bucket(trades.map(t=>({...t,__pair:(t[a]||"Unknown")+" · "+(t[b]||"Unknown")})),"__pair");
}

export function analyzeBehavior(trades){
  const journal=getJournal();
  const reviewed=trades.map(t=>({trade:t,review:journal[t.id]})).filter(x=>x.review);
  const setups=bucket(reviewed.filter(x=>x.review.setup).map(x=>({...x.trade,setup:x.review.setup})),"setup");
  const grades=bucket(reviewed.filter(x=>x.review.grade).map(x=>({...x.trade,grade:x.review.grade})),"grade");

  const ruleNames=["Wait for a clear setup","Confirm structure / support / resistance","Keep risk inside the planned limit","Avoid revenge trading"];
  const rules=ruleNames.map((name,i)=>{
    const checked=reviewed.filter(x=>(x.review.rules||[]).includes(i)).map(x=>x.trade);
    const recorded=reviewed.filter(x=>(x.review.rules||[]).some(r=>r===i)).length;
    return {name,count:checked.length,recorded,pnl:checked.reduce((s,t)=>s+(Number(t.pnl)||0),0),winRate:checked.length?checked.filter(t=>t.pnl>0).length/checked.length*100:0};
  });

  const ordered=[...trades].sort((a,b)=>String(a.time).localeCompare(String(b.time)));
  const risk=ordered.map(t=>Number(t.risk)||0).filter(Boolean);
  const riskAvg=avg(risk), riskCv=riskAvg?Math.sqrt(avg(risk.map(x=>(x-riskAvg)**2)))/riskAvg:0;
  const afterWin=ordered.slice(1).filter((t,i)=>ordered[i].pnl>0);
  const afterLoss=ordered.slice(1).filter((t,i)=>ordered[i].pnl<0);

  const streaks=[];let current=0,type="";
  ordered.forEach(t=>{const next=t.pnl>=0?"W":"L";if(next===type)current++;else{if(type)streaks.push({type,length:current});type=next;current=1;}});
  if(type)streaks.push({type,length:current});
  const maxWin=Math.max(0,...streaks.filter(s=>s.type==="W").map(s=>s.length));
  const maxLoss=Math.max(0,...streaks.filter(s=>s.type==="L").map(s=>s.length));

  const bySymbol=bucket(trades,"symbol");
  const bySession=bucket(trades,"session");
  const bySide=bucket(trades,"side");
  const byAccount=bucket(trades,"account");
  const pair=pairBuckets(trades,"symbol","session").filter(x=>x.trades>=2);

  const largestLosses=[...trades].sort((a,b)=>a.pnl-b.pnl).slice(0,5);
  const largestWins=[...trades].sort((a,b)=>b.pnl-a.pnl).slice(0,5);
  const flags=[];
  const strongest=bySymbol[0];
  if(strongest&&strongest.trades>=3)flags.push({type:"edge",title:"Instrument fingerprint",text:strongest.name+" leads the current sample with "+(strongest.pnl>=0?"+":"")+"$"+Math.abs(Math.round(strongest.pnl)).toLocaleString()+" net P&L across "+strongest.trades+" trades."});
  if(pair[0])flags.push({type:"edge",title:"Context fingerprint",text:pair[0].name+" has "+pair[0].trades+" trades and "+(pair[0].pnl>=0?"+":"")+"$"+Math.abs(Math.round(pair[0].pnl)).toLocaleString()+" net P&L."});
  if(risk.length>=3&&riskCv>.35)flags.push({type:"risk",title:"Risk variability",text:"Recorded position risk varies materially. Standardizing risk can make performance comparisons cleaner."});
  if(afterLoss.length>=3&&avg(afterLoss.map(t=>Number(t.pnl)||0))<0)flags.push({type:"behavior",title:"Post-loss pattern",text:"Trades immediately following losses are negative on average in this sample. This is an observation, not proof of causation."});
  if(maxLoss>=3)flags.push({type:"streak",title:"Loss sequence",text:"The dataset contains a "+maxLoss+"-trade losing streak. Review those executions as one sequence."});
  if(largestLosses[0]&&Math.abs(largestLosses[0].pnl)>Math.abs(avg(trades.map(t=>t.pnl))))flags.push({type:"risk",title:"Loss concentration",text:"The largest loss is materially larger than the average trade outcome. Inspect its execution context."});
  if(!flags.length)flags.push({type:"sample",title:"Machine is learning",text:"Add more executions and post-trade reviews. Trading Hub will have more evidence to compare behavior against outcomes."});

  return {reviewedCount:reviewed.length,reviewCoverage:trades.length?reviewed.length/trades.length*100:0,setups,grades,rules,riskAvg,riskCv,
    afterWin:{count:afterWin.length,avgPnl:avg(afterWin.map(t=>Number(t.pnl)||0))},
    afterLoss:{count:afterLoss.length,avgPnl:avg(afterLoss.map(t=>Number(t.pnl)||0))},
    maxWin,maxLoss,bySymbol,bySession,bySide,byAccount,pair,largestLosses,largestWins,flags};
}

export function behaviorSummary(b){
  return {coverage:pct(b.reviewCoverage),riskConsistency:b.riskCv?Math.max(0,Math.min(100,(1-b.riskCv)*100)).toFixed(0):"—",
    strongestSetup:b.setups[0]?.name||"—",strongestSetupPnl:b.setups[0]?.pnl||0};
}
