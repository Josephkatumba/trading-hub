import {analyzeBehavior,behaviorSummary} from "./behavior.js";
const money=n=>(n<0?"-$":"$")+Math.abs(Number(n)||0).toLocaleString(undefined,{maximumFractionDigits:0});
const signed=n=>n>=0?"+"+money(n):money(n);
const pct=n=>Number(n||0).toFixed(1)+"%";
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
export function renderAnalytics(trades,m){
 const b=analyzeBehavior(trades),s=behaviorSummary(b);
 const setupRows=b.setups.length?b.setups.map(x=>"<div class=\"behavior-row\"><div><b>"+esc(x.name)+"</b><small>"+x.trades+" reviewed · "+pct(x.winRate)+" win rate · "+(x.avgR>=0?"+":"")+x.avgR.toFixed(2)+"R</small></div><strong class=\""+(x.pnl>=0?"up":"down")+"\">"+signed(x.pnl)+"</strong></div>").join(""):"<div class=\"empty-state\">Review trades from the drawer to build your setup history.</div>";
 const gradeRows=b.grades.length?b.grades.map(x=>"<div class=\"behavior-row\"><div><b>Grade "+esc(x.name)+"</b><small>"+x.trades+" trades · "+pct(x.winRate)+" win rate · "+(x.avgR>=0?"+":"")+x.avgR.toFixed(2)+"R</small></div><strong class=\""+(x.pnl>=0?"up":"down")+"\">"+signed(x.pnl)+"</strong></div>").join(""):"<div class=\"empty-state\">Add execution grades in post-trade reviews.</div>";
 const ruleRows=b.rules.map(x=>"<div class=\"behavior-row\"><div><b>"+esc(x.name)+"</b><small>"+x.count+" followed · "+x.missed+" not checked</small></div><strong>"+(x.count?pct(x.winRate):"—")+"</strong></div>").join("");
 const flagRows=b.flags.map(x=>"<div class=\"flag "+x.type+"\"><span>"+(x.type==="risk"?"◈":x.type==="behavior"?"↻":x.type==="streak"?"!":"✦")+"</span><div><b>"+esc(x.title)+"</b><p>"+esc(x.text)+"</p></div></div>").join("");
 return "<div class=\"page-title\"><div><div class=\"kicker\">BEHAVIORAL ANALYTICS</div><h1>Your trading fingerprint</h1><p class=\"sub\">Trading Hub compares outcomes with the behavior you record after each execution.</p></div><button class=\"ghost\" data-view=\"trades\">Review more trades</button></div>"+
 "<div class=\"analytics-grid\"><div class=\"panel\"><span class=\"kicker\">REVIEW COVERAGE</span><h2>"+s.coverage+"</h2><div class=\"score\">"+b.reviewedCount+" / "+trades.length+"</div><div class=\"meter\"><i style=\"width:"+Math.min(b.reviewCoverage,100)+"%\"></i></div><p class=\"sub\">Reviewed executions feeding behavioral analysis.</p></div>"+
 "<div class=\"panel\"><span class=\"kicker\">RISK CONSISTENCY</span><h2>"+(s.riskConsistency==="—"?"Building":s.riskConsistency+" / 100")+"</h2><div class=\"score\">"+(b.riskAvg?money(b.riskAvg)+" avg risk":"—")+"</div><p class=\"sub\">Lower variation means cleaner comparison.</p></div>"+
 "<div class=\"panel\"><span class=\"kicker\">STRONGEST REVIEWED SETUP</span><h2>"+esc(s.strongestSetup)+"</h2><div class=\"score up\">"+(s.strongestSetupPnl?signed(s.strongestSetupPnl):"—")+"</div><p class=\"sub\">Net P&L among reviewed setups.</p></div>"+
 "<div class=\"panel\"><span class=\"kicker\">STREAK MEMORY</span><h2>"+b.maxWin+"W · "+b.maxLoss+"L</h2><div class=\"score\">"+(b.afterLoss.count?((b.afterLoss.avgPnl>=0?"+":"")+money(b.afterLoss.avgPnl)):"—")+"</div><p class=\"sub\">Average P&L immediately after a loss.</p></div></div>"+
 "<div class=\"behavior-grid\"><div class=\"panel\"><span class=\"kicker\">SETUP LAB</span><h2>What happens by setup</h2><div class=\"behavior-list\">"+setupRows+"</div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">EXECUTION GRADES</span><h2>Grade vs outcome</h2><div class=\"behavior-list\">"+gradeRows+"</div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">RULE ADHERENCE</span><h2>Rules become measurable</h2><div class=\"behavior-list\">"+ruleRows+"</div></div>"+
 "<div class=\"panel\"><span class=\"kicker\">BEHAVIORAL FLAGS</span><h2>What deserves a closer look</h2><div class=\"flag-list\">"+flagRows+"</div></div></div>";
}
export function renderInsights(trades,m){
 const b=analyzeBehavior(trades),s=behaviorSummary(b);
 const flags=b.flags.slice(0,3).map(x=>"<div class=\"coach-item\"><span>✦</span><div><b>"+esc(x.title)+"</b><p>"+esc(x.text)+"</p></div></div>").join("");
 return "<div class=\"page-title\"><div><div class=\"kicker\">TRADING INTELLIGENCE</div><h1>Trading Coach</h1><p class=\"sub\">A deterministic intelligence layer today. The model layer can plug in later.</p></div></div>"+
 "<div class=\"analyst\"><div class=\"analyst-orb\">✦</div><h2>Show me what I keep doing.</h2><p>Trading Hub has <b>"+trades.length+" trades</b> and <b>"+b.reviewedCount+" reviewed trades</b>. Observed edge: <b>"+esc(m.bestInstrument)+"</b> in <b>"+esc(m.bestSession)+"</b>.</p>"+
 "<div class=\"analyst-grid\"><div><span>REVIEW COVERAGE</span><b>"+s.coverage+"</b></div><div><span>STRONGEST SETUP</span><b>"+esc(s.strongestSetup)+"</b></div><div><span>RISK CONSISTENCY</span><b>"+s.riskConsistency+"</b></div></div>"+
 "<div class=\"coach-feed\">"+flags+"</div><button class=\"ai-button\" data-view=\"analytics\">Open behavioral dashboard <span>↗</span></button></div>";
}