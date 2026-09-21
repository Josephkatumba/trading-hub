import {getJournal} from "./journal.js";

const round=(n,d=2)=>Number(n||0).toFixed(d);
const avg=(xs)=>xs.length?xs.reduce((s,x)=>s+x,0)/xs.length:0;
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
    const wins=items.filter(t=>t.pnl>0).length;
    return {name,trades:items.length,pnl,winRate:items.length?wins/items.length*100:0,avgR:avg(items.map(t=>Number(t.r)||0))};
  }).sort((a,b)=>b.pnl-a.pnl);
}

export function analyzeBehavior(trades){
  const journal=getJournal();
  const reviewed=trades.map(t=>({trade:t,review:journal[t.id]})).filter(x=>x.review);
  const setupRows=reviewed.filter(x=>x.review.setup).map(x=>({...x.trade,setup:x.review.setup}));
  const setups=bucket(setupRows,"setup");
  const grades=bucket(reviewed.filter(x=>x.review.grade).map(x=>({...x.trade,grade:x.review.grade})),"grade");

  const ruleRows=[];
  reviewed.forEach(({trade,review})=>{
    (review.rules||[]).forEach(ruleIndex=>ruleRows.push({...trade,ruleIndex}));
  });
  const rules=Object.entries(journal).length?[]:[];
  const ruleNames=[
    "Wait for a clear setup",
    "Confirm structure / support / resistance",
    "Keep risk inside the planned limit",
    "Avoid revenge trading"
  ];
  for(let i=0;i<ruleNames.length;i++){
    const adherent=reviewed.filter(x=>(x.review.rules||[]).includes(i)).map(x=>x.trade);
    const nonAdherent=reviewed.filter(x=>!(x.review.rules||[]).includes(i)).map(x=>x.trade);
    rules.push({
      name:ruleNames[i],
      count:adherent.length,
      pnl:adherent.reduce((s,t)=>s+(Number(t.pnl)||0),0),
      winRate:adherent.length?adherent.filter(t=>t.pnl>0).length/adherent.length*100:0,
      missed:nonAdherent.length
    });
  }

  const ordered=[...trades].sort((a,b)=>String(a.time).localeCompare(String(b.time)));
  const risk=ordered.map(t=>Number(t.risk)||0).filter(Boolean);
  const riskAvg=avg(risk);
  const riskVariance=avg(risk.map(x=>(x-riskAvg)**2));
  const riskCv=riskAvg?Math.sqrt(riskVariance)/riskAvg:0;
  const afterWin=ordered.slice(1).filter((t,i)=>ordered[i].pnl>0);
  const afterLoss=ordered.slice(1).filter((t,i)=>ordered[i].pnl<0);
  const streaks=[];
  let current=0,type="";
  ordered.forEach(t=>{
    const next=t.pnl>=0?"W":"L";
    if(next===type)current++; else {if(type)streaks.push({type,length:current});type=next;current=1;}
  });
  if(type)streaks.push({type,length:current});
  const maxWin=Math.max(0,...streaks.filter(s=>s.type==="W").map(s=>s.length));
  const maxLoss=Math.max(0,...streaks.filter(s=>s.type==="L").map(s=>s.length));

  const flags=[];
  if(setups.length){
    const strongest=[...setups].sort((a,b)=>b.pnl-a.pnl)[0];
    if(strongest.trades>=2)flags.push({type:"edge",title:"Setup pattern",text:strongest.name+" has the highest reviewed net P&L at "+(strongest.pnl>=0?"+":"")+"$"+Math.abs(Math.round(strongest.pnl)).toLocaleString()+"."});
  }
  if(risk.length>=3&&riskCv>.35)flags.push({type:"risk",title:"Risk variability",text:"Position risk varies materially across the observed trades. Consistent sizing may make performance easier to evaluate."});
  if(afterLoss.length>=2){
    const p=avg(afterLoss.map(t=>Number(t.pnl)||0));
    if(p<0)flags.push({type:"behavior",title:"Post-loss pattern",text:"Trades following a loss have negative average P&L in this sample. Review the next-entry decision after losing trades."});
  }
  if(afterWin.length>=2){
    const p=avg(afterWin.map(t=>Number(t.pnl)||0));
    if(p<0)flags.push({type:"behavior",title:"Post-win pattern",text:"Trades following a win have negative average P&L in this sample. Check whether confidence changes execution."});
  }
  if(maxLoss>=3)flags.push({type:"streak",title:"Loss sequence",text:"The dataset contains a "+maxLoss+"-trade losing streak. Review those executions together rather than in isolation."});
  if(!flags.length)flags.push({type:"sample",title:"More evidence needed",text:"No strong behavioral flag is triggered by the current sample. Add more reviewed executions to make the patterns more useful."});

  return {
    reviewedCount:reviewed.length,
    reviewCoverage:trades.length?reviewed.length/trades.length*100:0,
    setups,grades,rules,
    riskAvg,riskCv,
    afterWin:{count:afterWin.length,avgPnl:avg(afterWin.map(t=>Number(t.pnl)||0))},
    afterLoss:{count:afterLoss.length,avgPnl:avg(afterLoss.map(t=>Number(t.pnl)||0))},
    maxWin,maxLoss,flags
  };
}

export function behaviorSummary(b){
  return {
    coverage:pct(b.reviewCoverage),
    riskConsistency:b.riskCv?Math.max(0,Math.min(100,(1-b.riskCv)*100)).toFixed(0):"—",
    strongestSetup:b.setups[0]?.name||"—",
    strongestSetupPnl:b.setups[0]?.pnl||0
  };
}
