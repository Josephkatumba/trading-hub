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
