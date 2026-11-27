import test from 'node:test';
import assert from 'node:assert/strict';
import {candleTime,qualifiedSignals,researchEvents,researchGroups} from '../src/intelligencePresentation.mjs';
const iso=t=>new Date(t*1000).toISOString();
const candles=[{time:900},{time:1800},{time:7200}];
test('alignment uses the originating UTC candle and rejects gaps, naive dates and future events',()=>{
 assert.equal(candleTime(candles,iso(1850),'M15'),1800);
 for(const stamp of [iso(0),iso(3600),iso(8100),'2026-10-28T12:00:00','bad'])assert.equal(candleTime(candles,stamp,'M15'),null);
});
test('qualified view requires existing LIVE qualification and matching instrument/timeframe',()=>{
 const row={symbol:'XAUUSD',timeframe:'M15',mode:'LIVE',trade_qualified:true};
 assert.deepEqual(qualifiedSignals([row,{...row,mode:'SHADOW'},{...row,trade_qualified:false},{...row,symbol:'BTCUSD'},{...row,timeframe:'H1'}],'XAUUSD','M15'),[row]);
});
test('research groups preserve all records, separate event types and apply every filter',()=>{
 const e={setup_id:'s',strategy_id:'smc',observed_at:iso(1800),confirmation_time:iso(1850)};
 const o={setup_id:'s',observed_at:iso(1800),horizon:'1h',label:'WIN',horizon_end:iso(7200)};
 const events=researchEvents([e],[o,{...o,outcome_status:'DUPLICATE_OUTCOME_CONFLICT'}]);
 assert.equal(events.length,3);
 const filters={timeframe:'M15',strategy:'smc',kind:'Hypothetical outcome',horizon:'1h',outcome:'WIN',from:'1970-01-01',to:'1970-01-01'};
 const result=researchGroups(candles,events,filters);
 assert.equal(result.groups[0][0],1800);assert.equal(result.groups[0][1][0].horizon_end,iso(7200));
 assert.equal(researchGroups(candles,events,{timeframe:'M15'}).markers[0].text,'3');
 for(const [k,v] of Object.entries({strategy:'other',kind:'Expired',horizon:'4h',outcome:'LOSS',from:'2020-01-01',to:'1960-01-01'}))assert.equal(researchGroups(candles,events,{...filters,[k]:v}).total,0);
 assert.equal(e.kind,undefined);
});
test('research defaults to 20 compact markers with configurable bounded limits',()=>{
 const bars=Array.from({length:250},(_,i)=>({time:900+i*900}));
 const events=bars.map(b=>({stamp:iso(b.time),kind:'Observation'}));
 assert.equal(researchGroups(bars,events,{timeframe:'M15'}).markers.length,20);
 assert.equal(researchGroups(bars,events,{timeframe:'M15',limit:500}).markers.length,200);
});
