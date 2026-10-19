import test from 'node:test';
import assert from 'node:assert/strict';
import {localLabsAvailable,labsContent,renderQuantLabs} from '../src/quantLabs.mjs';
test('research navigation is restricted to loopback',()=>{assert.ok(localLabsAvailable('127.0.0.1'));assert.ok(localLabsAvailable('localhost'));assert.equal(localLabsAvailable('tradeden.com'),false);});
test('pending labs, unavailable metrics and outbound block are explicit',()=>{const html=labsContent({labs:[{name:'Claude Quant Lab',status:'PENDING_ACTUAL_AI_MODEL',models:[]}],performance:{}});assert.match(html,/Awaiting a model authored/);assert.match(html,/NO OUTBOUND DELIVERY/);assert.match(html,/Actual executed R unavailable/);assert.match(renderQuantLabs(),/quantLabsData/);});
test('untrusted model and signal text are escaped',()=>{const html=labsContent({labs:[],signals:[{model_name:'<img src=x onerror=alert(1)>',outcome:{reason:'<script>x</script>'}}],outbox:[{message:'<b>TEST</b>'}]});assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script>'));assert.match(html,/&lt;b&gt;TEST/);});
