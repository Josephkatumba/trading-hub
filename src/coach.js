import {analyzeBehavior} from "./behavior.js";
const money=n=>(n<0?"-$":"$")+Math.abs(Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});
const signed=n=>n>=0?"+"+money(n):money(n);
const avg=xs=>xs.length?xs.reduce((s,x)=>s+x,0)/xs.length:0;
const pct=n=>Number(n||0).toFixed(1)+"%";
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
export function answerQuestion(question,trades){
 const q=String(question||"").toLowerCase(), b=analyzeBehavior(trades);
 const ordered=[...trades].sort((a,z)=>String(a.time).localeCompare(String(z.time)));
 const lossFollow=ordered.slice(1).filter((t,i)=>ordered[i].pnl<0);
 const winFollow=ordered.slice(1).filter((t,i)=>ordered[i].pnl>0);
 const best=b.setups[0], worst=[...b.setups].sort((a,z)=>a.pnl-z.pnl)[0];
 let title="Here is what your data says";
 let body="I need a little more reviewed trade history before I can make a useful behavioral observation.";
 let facts=[];
 if(/risk|size|sizing|lot/.test(q)){
   title="Your risk profile";
   body=b.riskAvg?"Your average recorded risk is "+money(b.riskAvg)+". Risk consistency is "+(b.riskCv?Math.max(0,(1-b.riskCv)*100).toFixed(0):"—")+"/100.":"There is not enough recorded risk data yet.";
   if(b.riskCv>.35)facts.push("Risk varies materially across the current sample.");
 } else if(/after.*loss|loss.*after|revenge|losing/.test(q)){
   title="What happens after a loss";
   body=lossFollow.length?"You have "+lossFollow.length+" trades immediately following a loss, averaging "+(avg(lossFollow.map(t=>Number(t.pnl)||0))>=0?"+":"")+money(avg(lossFollow.map(t=>Number(t.pnl)||0)))+" each.":"There are not enough sequential trades after losses to measure this yet.";
   facts=b.maxLoss>=3?["Longest losing streak: "+b.maxLoss+" trades."]:[];
 } else if(/after.*win|win.*after|confidence/.test(q)){
   title="What happens after a win";
   body=winFollow.length?"You have "+winFollow.length+" trades immediately following a win, averaging "+(avg(winFollow.map(t=>Number(t.pnl)||0))>=0?"+":"")+money(avg(winFollow.map(t=>Number(t.pnl)||0)))+" each.":"There are not enough sequential trades after wins to measure this yet.";
 } else if(/setup|strategy|pattern/.test(q)){
   title="Setup performance";
   body=best?"Your strongest reviewed setup is "+best.name+" with "+signed(best.pnl)+" across "+best.trades+" trades.":"You have not reviewed enough trades with named setups yet.";
   if(worst&&worst.name!==best?.name)facts.push("The lowest reviewed setup by P&L is "+worst.name+" at "+signed(worst.pnl)+".");
 } else if(/mistake|mistakes|wrong|discipline|rule/.test(q)){
   title="Recurring behavior";
   const flagged=b.flags.filter(x=>x.type!=="sample");
   body=flagged.length?flagged[0].text:"No strong recurring behavior flag is triggered by the current sample.";
   facts=b.rules.filter(x=>x.count&&x.winRate<50).slice(0,2).map(x=>x.name+" has a "+pct(x.winRate)+" win rate when checked.");
 } else if(/gold|xau/.test(q)){
   const gold=trades.filter(t=>/XAU/i.test(t.symbol)); const gp=gold.reduce((s,t)=>s+(Number(t.pnl)||0),0);
   title="Your gold history";
   body=gold.length?"Gold accounts for "+gold.length+" trades and "+signed(gp)+" net P&L in this dataset.":"No XAUUSD trades are currently loaded.";
   facts=gold.length?[pct(gold.filter(t=>t.pnl>0).length/gold.length*100)+" win rate."]:[];
 } else if(/why|performance|doing|overview/.test(q)){
   title="Your current trading fingerprint";
   body="You have "+trades.length+" executions with "+b.reviewedCount+" reviewed. The current observed edge is "+(trades.length?trades.reduce((m,t)=>m+(Number(t.pnl)||0),0)>=0?"positive":"negative":"unclear")+" by total P&L.";
   facts=[b.setups.length?"Strongest reviewed setup: "+b.setups[0].name+".":"Name more setups in your reviews.",b.maxLoss?"Longest losing streak: "+b.maxLoss+".":"Streak data is still building."];
 }
 return {title,body,facts};
}