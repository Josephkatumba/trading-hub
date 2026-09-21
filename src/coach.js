import {analyzeBehavior} from "./behavior.js";

const money=n=>(n<0?"-$":"$")+Math.abs(Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});
const signed=n=>n>=0?"+"+money(n):money(n);
const avg=xs=>xs.length?xs.reduce((s,x)=>s+x,0)/xs.length:0;
const pct=n=>Number(n||0).toFixed(1)+"%";

function total(trades){return trades.reduce((s,t)=>s+(Number(t.pnl)||0),0);}
function describeBucket(rows,label){
  if(!rows.length)return null;
  const pnl=total(rows), wins=rows.filter(t=>Number(t.pnl)>0).length;
  return {label,pnl,trades:rows.length,winRate:wins/rows.length*100,avgPnl:pnl/rows.length};
}

export function answerQuestion(question,trades){
 const q=String(question||"").toLowerCase(), b=analyzeBehavior(trades);
 const ordered=[...trades].sort((a,z)=>String(a.time).localeCompare(String(z.time)));
 const lossFollow=ordered.slice(1).filter((t,i)=>Number(ordered[i].pnl)<0);
 const winFollow=ordered.slice(1).filter((t,i)=>Number(ordered[i].pnl)>0);
 const best=b.setups[0], worst=[...b.setups].sort((a,z)=>a.pnl-z.pnl)[0];
 let title="Here is what your data says";
 let body="I need more reviewed trade history before I can make a useful behavioral observation.";
 let facts=[];

 if(/risk|size|sizing|lot/.test(q)){
   title="Your risk profile";
   body=b.riskAvg?"Your average recorded risk is "+money(b.riskAvg)+". Risk consistency is "+(b.riskCv?Math.max(0,(1-b.riskCv)*100).toFixed(0):"—")+"/100.":"There is not enough recorded risk data yet.";
   if(b.riskCv>.35)facts.push("Risk varies materially across the current sample.");
   facts.push("Risk consistency describes variability in recorded risk, not whether the risk level itself is appropriate.");
 }
 else if(/after.*loss|loss.*after|revenge/.test(q)){
   title="What happens after a loss";
   body=lossFollow.length?"You have "+lossFollow.length+" trades immediately following a loss, averaging "+(avg(lossFollow.map(t=>Number(t.pnl)||0))>=0?"+":"")+money(avg(lossFollow.map(t=>Number(t.pnl)||0)))+" each.":"There are not enough sequential trades after losses to measure this yet.";
   facts=b.maxLoss>=3?["Longest losing streak: "+b.maxLoss+" trades."]:["This is an observational pattern, not proof that the previous loss caused the next result."];
 }
 else if(/after.*win|win.*after|confidence/.test(q)){
   title="What happens after a win";
   body=winFollow.length?"You have "+winFollow.length+" trades immediately following a win, averaging "+(avg(winFollow.map(t=>Number(t.pnl)||0))>=0?"+":"")+money(avg(winFollow.map(t=>Number(t.pnl)||0)))+" each.":"There are not enough sequential trades after wins to measure this yet.";
 }
 else if(/setup|strategy|pattern/.test(q)){
   title="Setup performance";
   body=best?"Your strongest reviewed setup is "+best.name+" with "+signed(best.pnl)+" across "+best.trades+" trades.":"You have not reviewed enough trades with named setups yet.";
   if(worst&&worst.name!==best?.name)facts.push("Lowest reviewed setup by P&L: "+worst.name+" at "+signed(worst.pnl)+".");
 }
 else if(/mistake|mistakes|wrong|discipline|rule/.test(q)){
   title="Recurring behavior";
   const flagged=b.flags.filter(x=>x.type!=="sample");
   body=flagged.length?flagged[0].text:"No strong recurring behavior flag is triggered by the current sample.";
   facts=b.rules.filter(x=>x.count&&x.winRate<50).slice(0,2).map(x=>x.name+" has a "+pct(x.winRate)+" win rate when explicitly checked.");
 }
 else if(/gold|xau/.test(q)){
   const gold=trades.filter(t=>/XAU/i.test(t.symbol)), gp=total(gold);
   title="Your gold history";
   body=gold.length?"Gold accounts for "+gold.length+" trades and "+signed(gp)+" net P&L in this dataset.":"No XAUUSD trades are currently loaded.";
   facts=gold.length?[pct(gold.filter(t=>Number(t.pnl)>0).length/gold.length*100)+" win rate."]:[];
 }
 else if(/why.*lose|why.*losing|losing|performance|doing|overview|what.*wrong/.test(q)){
   title="Why the current sample is losing";
   const net=total(trades);
   const instrument=b.bySymbol[0];
   const worstInstrument=[...b.bySymbol].sort((a,z)=>a.pnl-z.pnl)[0];
   const worstSession=[...b.bySession].sort((a,z)=>a.pnl-z.pnl)[0];
   const worstSide=[...b.bySide].sort((a,z)=>a.pnl-z.pnl)[0];
   const largestLoss=b.largestLosses[0];
   const components=[
     instrument?describeBucket(trades.filter(t=>t.symbol===instrument.name),"instrument"):null,
     worstInstrument?describeBucket(trades.filter(t=>t.symbol===worstInstrument.name),"instrument"):null,
     worstSession?describeBucket(trades.filter(t=>t.session===worstSession.name),"session"):null,
     worstSide?describeBucket(trades.filter(t=>t.side===worstSide.name),"direction"):null
   ].filter(Boolean);
   body="Across "+trades.length+" executions, total P&L is "+signed(net)+". The machine is looking for concentration of losses rather than assuming a single cause.";
   if(worstInstrument)facts.push("Lowest instrument: "+worstInstrument.name+" at "+signed(worstInstrument.pnl)+" across "+worstInstrument.trades+" trades.");
   if(worstSession)facts.push("Lowest session: "+worstSession.name+" at "+signed(worstSession.pnl)+" across "+worstSession.trades+" trades.");
   if(worstSide)facts.push("Lowest direction: "+worstSide.name+" at "+signed(worstSide.pnl)+" across "+worstSide.trades+" trades.");
   if(largestLoss)facts.push("Largest single loss: "+signed(largestLoss.pnl)+". Review its execution context before drawing conclusions.");
   if(b.maxLoss>=3)facts.push("Longest losing streak: "+b.maxLoss+" trades.");
   if(!components.length)facts.push("More executions are needed before the loss pattern can be decomposed.");
 }
 else {
   title="Your current trading fingerprint";
   body="You have "+trades.length+" executions with "+b.reviewedCount+" reviewed. Total P&L is "+signed(total(trades))+".";
   facts=[b.setups.length?"Strongest reviewed setup: "+b.setups[0].name+".":"Name setups in your reviews so the system can compare them.",b.maxLoss?"Longest losing streak: "+b.maxLoss+".":"Streak data is still building."];
 }

 return {title,body,facts};
}
