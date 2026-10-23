import test from 'node:test';
import assert from 'node:assert/strict';
import {localLabsAvailable,labsContent,renderQuantLabs} from '../src/quantLabs.mjs';
test('research navigation is restricted to loopback',()=>{assert.ok(localLabsAvailable('127.0.0.1'));assert.ok(localLabsAvailable('localhost'));assert.equal(localLabsAvailable('tradeden.com'),false);});
test('pending labs, unavailable metrics and outbound block are explicit',()=>{const html=labsContent({labs:[{name:'Claude Quant Lab',status:'PENDING_ACTUAL_AI_MODEL',models:[]}],performance:{}});assert.match(html,/Awaiting a model authored/);assert.match(html,/NO OUTBOUND DELIVERY/);assert.match(html,/Actual executed R unavailable/);assert.match(renderQuantLabs(),/quantLabsData/);});
test('untrusted model and signal text are escaped',()=>{const html=labsContent({labs:[],signals:[{model_name:'<img src=x onerror=alert(1)>',outcome:{reason:'<script>x</script>'}}],outbox:[{message:'<b>TEST</b>'}]});assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script>'));assert.match(html,/&lt;b&gt;TEST/);});
test('leaderboard separates historical and forward results and flags small samples',()=>{
 const board={historical_note:'never pooled',rows:[{researcher:'Codex',strategy:'<b>X</b>',version:'0.1.0',instruments:['BTCUSD'],timeframe:'M15',category:'B',category_label:'Inconclusive',status:'EXPERIMENTAL',telegram_enabled:false,family:'one hypothesis',historical:{train:{n:35,net_expectancy_r:0.195},validation:{n:25,net_expectancy_r:0.265,insufficient_sample:true},test:{n:21,net_expectancy_r:0.33,stress_expectancy_r:0.285,insufficient_sample:true}},forward:{confirmed:0,resolved:0,insufficient_sample:true},last_successful_evaluation:null}]};
 const html=labsContent({labs:[],leaderboard:board,runtime:{telegram_mode:'EXPERIMENTAL_APPROVED'}});
 assert.match(html,/Unified Quant Labs leaderboard/);assert.match(html,/\+0\.33R/);assert.match(html,/small sample/);assert.match(html,/Correlated family/);
 assert.ok(!html.includes('<b>X</b>'));assert.match(html,/APPROVED FOR PAPER CANDIDATES ONLY/);assert.doesNotMatch(html,/NO OUTBOUND DELIVERY/);});
test('gold and bitcoin intelligence renders explanations, unavailable data and no trade levels',()=>{
 const intel={symbol:'XAUUSD',name:'Gold',price:4011.03,price_source:'live bid quote',data_timestamp:'2026-10-23T01:30:00+00:00',stale:false,
  structure:{D1:{state:'DOWN'},H4:{state:'DOWN'},H1:{state:'DOWN'}},regime:{trend:{state:'TRENDING'},volatility:{state:'HIGH'},expansion:{state:'NORMAL'},shock:{state:'NONE'}},
  sessions:{current:'Asia'},nearest_resistance:{name:'Previous day low',price:4021.13,event:'ACCEPTED',rule:'L1'},nearest_support:null,
  scenarios:{bullish:{rule:'C1',requires:'H1 close above <x>',currently_met:false},bearish:{rule:'C2',requires:'H1 close below y',currently_met:true},neutral:{rule:'C3',reasons:[]}},
  explanations:[{conclusion:'Structure D1 DOWN',rules:['T1'],observations:{},data_timestamp:'t',missing:[],conflicts:[]}],
  macro:{economic_calendar:{state:'UNAVAILABLE',reason:'No authoritative calendar connected'}},not_a_signal:'Market analysis only.'};
 const html=labsContent({labs:[],intelligence:[intel]});
 assert.match(html,/Gold &amp; Bitcoin intelligence|Gold & Bitcoin intelligence/);assert.match(html,/XAUUSD intelligence/);assert.match(html,/No authoritative calendar connected/);
 assert.match(html,/conditions, not trades/);assert.match(html,/<b>met<\/b>/);assert.ok(!html.includes('<x>'));assert.doesNotMatch(html,/Stop loss|Take profit/i);});
