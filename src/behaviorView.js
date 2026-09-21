import {analyzeBehavior,behaviorSummary} from "./behavior.js";
import {answerQuestion} from "./coach.js";
const money=n=>(n<0?"-$":"$")+Math.abs(Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});
const signed=n=>n>=0?"+"+money(n):money(n);
const pct=n=>Number(n||0).toFixed(1)+"%";
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function bars(rows,value="pnl",limit=6){
 const data=rows.slice(0,limit); if(!data.length)return '<div class="empty-state">More executions needed.</div>';
 const max=Math.max(1,...data.map(x=>Math.abs(Number(x[value])||0)));
 return '<div class="bar-chart">'+data.map(x=>'<div class="bar-row"><span>'+esc(x.name)+'</span><div class="bar-track"><i class="'+(x[value]>=0?"positive":"negative")+'" style="width:'+Math.max(4,Math.abs(x[value])/max*100)+'%"></i></div><b class="'+(x[value]>=0?"up":"down")+'">'+signed(x[value])+'</b></div>').join("")+'</div>';
}
function pie(rows){
 const data=rows.filter(x=>x.trades>0).slice(0,6); const total=data.reduce((s,x)=>s+x.trades,0)||1; let start=0;
 const colors=["#6fe0a3","#78a8ff","#d5a6ff","#f6c56b","#ef8d98","#67d7d1"];
 const stops=data.map((x,i)=>{const a=start/total*100;start+=x.trades;const b=start/total*100;return colors[i%colors.length]+" "+a+"% "+b+"%";}).join(",");
 return '<div class="pie-wrap"><div class="pie" style="background:conic-gradient('+stops+')"></div><div class="pie-legend">'+data.map((x,i)=>'<div><i style="background:'+colors[i%colors.length]+'"></i><span>'+esc(x.name)+'</span><b>'+x.trades+'</b></div>').join("")+'</div></div>';
}
export function renderAnalytics(trades,m){
 const b=analyzeBehavior(trades),s=behaviorSummary(b);
 const setupRows=b.setups.length?b.setups.map(x=>"<div class=\"behavior-row\"><div><b>"+esc(x.name)+"</b><small>"+x.trades+" reviewed · "+pct(x.winRate)+" win rate · "+(x.avgR>=0?"+":"")+x.avgR.toFixed(2)+"R</small></div><strong class=\""+(x.pnl>=0?"up":"down")+"\">"+signed(x.pnl)+"</strong></div>").join(""):"<div class=\"empty-state\">Review trades from the drawer to build your setup history.</div>";
 const gradeRows=b.grades.length?b.grades.map(x=>"<div class=\"behavior-row\"><div><b>Grade "+esc(x.name)+"</b><small>"+x.trades+" trades · "+pct(x.winRate)+" win rate</small></div><strong class=\""+(x.pnl>=0?"up":"down")+"\">"+signed(x.pnl)+"</strong></div>").join(""):"<div class=\"empty-state\">Add execution grades in post-trade reviews.</div>";
 const ruleRows=b.rules.map(x=>"<div class=\"behavior-row\"><div><b>"+esc(x.name)+"</b><small>"+x.count+" followed · "+x.recorded+" explicitly recorded</small></div><strong>"+(x.count?pct(x.winRate):"—")+"</strong></div>").join("");
 const flagRows=b.flags.map(x=>"<div class=\"flag "+x.type+"\"><span>"+(x.type==="risk"?"◈":x.type==="behavior"?"↻":x.type==="streak"?"!":"✦")+"</span><div><b>"+esc(x.title)+"</b><p>"+esc(x.text)+"</p></div></div>").join("");
 return "<div class=\"page-title\"><div><div class=\"kicker\">BEHAVIORAL ANALYTICS</div><h1>Your trading fingerprint</h1><p class=\"sub\">The machine compares instruments, sessions, sequences, risk and your reviews.</p></div><button class=\"ghost\" data-view=\"trades\">Review more trades</button></div>"+
 "<div class=\"analytics-grid\"><div class=\"panel\"><span class=\"kicker\">REVIEW COVERAGE</span><h2>"+s.coverage+"</h2><div class=\"score\">"+b.reviewedCount+" / "+trades.length+"</div><div class=\"meter\"><i style=\"width:"+Math.min(b.reviewCoverage,100)+"%\"></i></div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">RISK CONSISTENCY</span><h2>"+(s.riskConsistency==="—"?"Building":s.riskConsistency+" / 100")+"</h2><div class=\"score\">"+(b.riskAvg?money(b.riskAvg)+" avg risk":"—")+"</div></div></div>"+
 "<div class=\"chart-grid-2\"><div class=\"panel\"><div class=\"panel-head\"><div><span class=\"kicker\">P&L BY INSTRUMENT</span><h2>Where the money is moving</h2></div></div>"+bars(b.bySymbol)+"</div>"+
 "<div class=\"panel\"><div class=\"panel-head\"><div><span class=\"kicker\">TRADE MIX</span><h2>Instrument share</h2></div></div>"+pie(b.bySymbol)+"</div></div>"+
 "<div class=\"chart-grid-2\"><div class=\"panel\"><span class=\"kicker\">SESSION PERFORMANCE</span><h2>London vs New York vs Asia</h2>"+bars(b.bySession)+"</div>"+
 "<div class=\"panel\"><span class=\"kicker\">DIRECTION</span><h2>Buy vs sell</h2>"+bars(b.bySide)+"</div></div>"+
 "<div class=\"behavior-grid\"><div class=\"panel\"><span class=\"kicker\">SETUP LAB</span><h2>Reviewed setup performance</h2><div class=\"behavior-list\">"+setupRows+"</div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">EXECUTION GRADES</span><h2>Grade vs outcome</h2><div class=\"behavior-list\">"+gradeRows+"</div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">RULE ADHERENCE</span><h2>Rules become measurable</h2><div class=\"behavior-list\">"+ruleRows+"</div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">MACHINE SIGNALS</span><h2>What deserves a closer look</h2><div class=\"flag-list\">"+flagRows+"</div></div></div>";
}
export function renderInsights(trades,m){
 const b=analyzeBehavior(trades),s=behaviorSummary(b),initial=answerQuestion("overview",trades);
 const flags=b.flags.slice(0,4).map(x=>"<div class=\"coach-item\"><span>✦</span><div><b>"+esc(x.title)+"</b><p>"+esc(x.text)+"</p></div></div>").join("");
 return "<div class=\"page-title\"><div><div class=\"kicker\">TRADING INTELLIGENCE</div><h1>Trading Coach</h1><p class=\"sub\">Ask questions about your own trading history.</p></div></div>"+
 "<div class=\"coach-shell\"><div class=\"coach-header\"><div class=\"analyst-orb\">✦</div><div><span class=\"kicker\">ASK TRADING HUB</span><h2>What do you want to understand?</h2><p class=\"sub\">Answers are calculated from executions and reviews stored in this workspace.</p></div></div>"+
 "<div class=\"coach-prompts\"><button data-question=\"Why have I been losing?\">Why have I been losing?</button><button data-question=\"What happens after I take a loss?\">After a loss?</button><button data-question=\"Which setups make me money?\">Which setups work?</button><button data-question=\"Am I risking consistently?\">Is my risk consistent?</button></div>"+
 "<form class=\"coach-ask\" id=\"coachForm\"><input id=\"coachInput\" placeholder=\"Ask: what is my biggest recurring mistake?\" autocomplete=\"off\"/><button class=\"primary\">Ask</button></form>"+
 "<div class=\"coach-answer\" id=\"coachAnswer\"><div class=\"kicker\">DATA ANSWER</div><h3>"+esc(initial.title)+"</h3><p>"+esc(initial.body)+"</p>"+(initial.facts.length?"<ul>"+initial.facts.map(x=>"<li>"+esc(x)+"</li>").join("")+"</ul>":"")+"</div>"+
 "<div class=\"coach-feed\">"+flags+"</div><div class=\"analyst-grid\"><div><span>REVIEW COVERAGE</span><b>"+s.coverage+"</b></div><div><span>STRONGEST SETUP</span><b>"+esc(s.strongestSetup)+"</b></div><div><span>RISK CONSISTENCY</span><b>"+s.riskConsistency+"</b></div></div></div>";
}