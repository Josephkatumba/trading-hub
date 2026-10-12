import test from "node:test";
import assert from "node:assert/strict";
import {widgetConfig,candlesForChart,chartMarkers,planLines} from "../src/chartModel.mjs";
test("official widget mappings and timeframe selections",()=>{
 assert.equal(widgetConfig("EURUSD","H1").interval,"60");
 assert.equal(widgetConfig("EURUSD","H1").symbol,"FX:EURUSD");
 for(const symbol of ["XAUUSD","BTCUSD","ETHUSD","EURUSD","GBPUSD","GBPJPY","USDJPY","NAS100","US500","GER40"])
  assert.ok(widgetConfig(symbol,"M15").symbol);
 assert.throws(()=>widgetConfig("<script>","H1"));
});
test("candles are sorted, duplicate times collapsed, and malformed prices excluded",()=>{
 const bar={time:1,open:1,high:3,low:0,close:2};
 assert.deepEqual(candlesForChart([{...bar,time:2},bar,bar,{...bar,time:3,high:0}]).map(b=>b.time),[1,2]);
});
test("immutable confirmed levels override later observations without invented levels",()=>{
 assert.deepEqual(planLines({}),[]);
 const lines=planLines({entry:20,confirmed_plan:{entry:10,stop_loss:8,take_profit:14}});
 assert.deepEqual(lines.map(l=>l.price),[10,8,14]);
 assert.equal(lines[0].title,"Confirmed Entry");
});
test("historical markers use evaluation horizon, never generation time, and quarantine conflicts",()=>{
 const candles=[{time:100},{time:200},{time:300}];
 const iso=t=>new Date(t*1000).toISOString();
 const outcomes=[{setup_id:"s",observation_id:"o",horizon:"1h",label:"WIN",resolved_at:iso(200),horizon_end:iso(250)},
 {setup_id:"bad",horizon:"1h",horizon_end:iso(250),outcome_status:"DUPLICATE_OUTCOME_CONFLICT"},
 {setup_id:"unknown",resolved_at:iso(200)}];
 const markers=chartMarkers(candles,[{strategy_id:"smc",observed_at:iso(150),direction:"LONG"}],outcomes);
 assert.equal(markers.length,2);assert.equal(markers[1].time,200);
 assert.match(markers[1].text,/Unverified hypothetical/);
});
