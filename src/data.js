import {IMPORTED_TRADES} from "./importedData.js";
const DEMO_TRADES = [
  { id:"TH-001", account:"Goldimus Funded", symbol:"XAUUSD", side:"BUY", entry:3342.2, exit:3356.8, volume:0.3, pnl:620, r:1.84, risk:337, time:"2026-09-21 14:32", session:"New York" },
  { id:"TH-002", account:"Personal Futures", symbol:"NAS100", side:"SELL", entry:22780, exit:22690, volume:1, pnl:410, r:1.35, risk:303, time:"2026-09-21 11:08", session:"London" },
  { id:"TH-003", account:"XAUUSD Account", symbol:"XAUUSD", side:"SELL", entry:3358.4, exit:3364.2, volume:0.2, pnl:-185, r:-0.55, risk:336, time:"2026-09-20 16:41", session:"New York" },
  { id:"TH-004", account:"Personal Futures", symbol:"BTCUSD", side:"BUY", entry:115200, exit:116050, volume:0.1, pnl:295, r:0.92, risk:321, time:"2026-09-20 10:14", session:"London" },
  { id:"TH-005", account:"Goldimus Funded", symbol:"US500", side:"SELL", entry:6532, exit:6540, volume:1, pnl:-90, r:-0.28, risk:321, time:"2026-09-18 13:22", session:"London" },
  { id:"TH-006", account:"Goldimus Funded", symbol:"XAUUSD", side:"BUY", entry:3328.4, exit:3341.8, volume:0.3, pnl:515, r:1.52, risk:339, time:"2026-09-17 15:06", session:"New York" },
  { id:"TH-007", account:"Goldimus Funded", symbol:"XAUUSD", side:"SELL", entry:3319.7, exit:3327.2, volume:0.3, pnl:-120, r:-0.36, risk:333, time:"2026-09-16 14:48", session:"New York" },
  { id:"TH-008", account:"Personal Futures", symbol:"NAS100", side:"SELL", entry:22910, exit:22780, volume:1, pnl:590, r:1.72, risk:343, time:"2026-09-15 10:41", session:"London" }
];

export function getTrades() {
  try {
    const saved=localStorage.getItem("th_trades");
    return saved ? JSON.parse(saved) : IMPORTED_TRADES;
  } catch { return IMPORTED_TRADES; }
}
export function saveTrades(trades){ localStorage.setItem("th_trades",JSON.stringify(trades)); }
export function resetTrades(){ localStorage.removeItem("th_trades"); }

const cleanHeader=h=>String(h).toLowerCase().replace(/[^a-z0-9]/g,"");
function splitLine(line,delimiter=","){
  const out=[]; let value="",quoted=false;
  for(let i=0;i<line.length;i++){
    const c=line[i];
    if(c === '"' && line[i+1] === '"'){ value+='"'; i++; }
    else if(c === '"'){ quoted=!quoted; }
    else if(c === delimiter && !quoted){ out.push(value.trim()); value=""; }
    else value+=c;
  }
  out.push(value.trim());
  return out;
}
function delimiterFor(line){
  const choices=[",",";","\t"];
  return choices.sort((a,b)=>line.split(b).length-line.split(a).length)[0];
}
const num=value=>Number(String(value??"").replace(/[$,%]/g,"").replace(/,/g,""))||0;
const aliases={
 account:["account","accountname","accountid","login"],symbol:["symbol","instrument","market"],side:["side","direction","type","action","ordertype"],
 entry:["entry","entryprice","openprice","open"],exit:["exit","exitprice","closeprice","close"],volume:["volume","lots","size","quantity"],
 pnl:["pnl","profit","profitloss","netprofit","netpnl"],r:["r","rr","riskreward"],risk:["risk","riskamount","riskusd"],time:["time","datetime","date","closetime","opentime","timestamp"],session:["session"]
};
export function parseCSV(text){
  const lines=String(text).replace(/^\uFEFF/,"").replace(/\r/g,"").split("\n").filter(x=>x.trim());
  if(lines.length<2)return [];
  const delimiter=delimiterFor(lines[0]);
  const headers=splitLine(lines[0],delimiter).map(cleanHeader);
  const find=(row,names)=>{for(const name of names){const i=headers.indexOf(cleanHeader(name));if(i>=0)return row[i]??"";}return "";};
  return lines.slice(1).map((line,index)=>{
    const row=splitLine(line,delimiter),rawSide=String(find(row,aliases.side)).toUpperCase(),time=find(row,aliases.time),pnl=num(find(row,aliases.pnl));
    return {id:"IMP-"+Date.now()+"-"+index,account:find(row,aliases.account)||"Imported Account",symbol:(find(row,aliases.symbol)||"UNKNOWN").toUpperCase(),side:rawSide.includes("SELL")?"SELL":"BUY",entry:num(find(row,aliases.entry)),exit:num(find(row,aliases.exit)),volume:num(find(row,aliases.volume)),pnl,r:num(find(row,aliases.r)),risk:num(find(row,aliases.risk))||Math.abs(pnl),time:time||new Date().toISOString().slice(0,16).replace("T"," "),session:find(row,aliases.session)||inferSession(time)};
  }).filter(t=>t.symbol!=="UNKNOWN" && (t.pnl!==0 || t.entry!==0 || t.exit!==0));
}
function inferSession(time){const hour=Number(String(time).match(/(?:T|\s)(\d{1,2})/)?.[1]??12);if(hour>=13&&hour<18)return "New York";if(hour>=8&&hour<13)return "London";return "Asia";}

export function calculateMetrics(trades){
  const ordered=[...trades].sort((a,b)=>String(a.time).localeCompare(String(b.time)));
  const pnl=ordered.reduce((s,t)=>s+(Number(t.pnl)||0),0);
  const wins=ordered.filter(t=>Number(t.pnl)>0),losses=ordered.filter(t=>Number(t.pnl)<0),breakevens=ordered.filter(t=>Number(t.pnl)===0);
  const grossProfit=wins.reduce((s,t)=>s+Number(t.pnl),0),grossLoss=Math.abs(losses.reduce((s,t)=>s+Number(t.pnl),0));
  const avgWin=wins.length?grossProfit/wins.length:0,avgLoss=losses.length?grossLoss/losses.length:0;
  let equity=0,peak=0,maxDrawdown=0;
  for(const t of ordered){equity+=Number(t.pnl)||0;peak=Math.max(peak,equity);maxDrawdown=Math.max(maxDrawdown,peak-equity);}
  const by=key=>ordered.reduce((m,t)=>(m[t[key]]=(m[t[key]]||0)+(Number(t.pnl)||0),m),{});
  const bySymbol=by("symbol"),bySession=by("session");
  const bestInstrument=Object.entries(bySymbol).sort((a,b)=>b[1]-a[1])[0]?.[0]||"—",bestSession=Object.entries(bySession).sort((a,b)=>b[1]-a[1])[0]?.[0]||"—";
  const avgR=ordered.length?ordered.reduce((s,t)=>s+(Number(t.r)||0),0)/ordered.length:0;
  const expectancy=ordered.length?pnl/ordered.length:0;
  return {pnl,wins:wins.length,losses:losses.length,breakevens:breakevens.length,winRate:ordered.length?wins.length/ordered.length*100:0,profitFactor:grossLoss?grossProfit/grossLoss:0,avgWin,avgLoss,payoffRatio:avgLoss?avgWin/avgLoss:0,expectancy,avgR,maxDrawdown,bestInstrument,bestSession,grossProfit,grossLoss,equityCurve:ordered.map((t,i)=>({i,pnl:Number(t.pnl)||0,equity:ordered.slice(0,i+1).reduce((s,x)=>s+(Number(x.pnl)||0),0)}))};
}

export function getAccounts(trades){
  const map=new Map();
  trades.forEach(t=>{if(!map.has(t.account))map.set(t.account,{name:t.account,platform:"Imported",balance:0,pnl:0,trades:0});const a=map.get(t.account);a.pnl+=Number(t.pnl)||0;a.trades++;});
  return [...map.values()];
}
export function getTradeContext(trade,trades){
  const sameSymbol=trades.filter(t=>t.symbol===trade.symbol),wins=sameSymbol.filter(t=>t.pnl>0),sameSession=sameSymbol.filter(t=>t.session===trade.session);
  const avgRisk=trades.length?trades.reduce((s,t)=>s+(Number(t.risk)||Math.abs(t.pnl)||0),0)/trades.length:0;
  return {symbolTrades:sameSymbol.length,symbolWinRate:sameSymbol.length?wins.length/sameSymbol.length*100:0,symbolAvgR:sameSymbol.length?sameSymbol.reduce((s,t)=>s+(Number(t.r)||0),0)/sameSymbol.length:0,symbolPnl:sameSymbol.reduce((s,t)=>s+(Number(t.pnl)||0),0),sessionPnl:sameSession.reduce((s,t)=>s+(Number(t.pnl)||0),0),avgRisk};
}
