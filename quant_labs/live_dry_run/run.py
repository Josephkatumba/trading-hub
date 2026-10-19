"""Repeatable SYNTHETIC dry run of the actual Codex model and existing client contract."""
import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime,timezone
import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from quant_live.store import Store
from quant_live.runtime import Runtime,register_codex
from quant_live.fixtures import ASOF,snapshot,future_bar
from quant_live.report import snapshot as report
from quant_live.telegram import ApprovedTelegramAdapter
from telegram_notifier import TelegramClient

def main():
    output=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as temporary:
        store=Store(temporary);register_codex(store);runtime=Runtime(store)
        first=runtime.process(snapshot(),ASOF)
        assert len(first['signals'])==1,first
        initial=report(store);s=first['signals'][0]
        # No HTTP traffic: existing production client uses an in-memory mock transport.
        requests=[]
        def mocked(request):
            requests.append(json.loads(request.content));return httpx.Response(200,json={'ok':True,'result':{'message_id':1}})
        client=TelegramClient('123456:FAKE_TOKEN_FOR_IN_MEMORY_TEST_ONLY',transport=httpx.MockTransport(mocked))
        try:
            adapter=ApprovedTelegramAdapter(client,'DRY_RUN_CHAT',{'activation_approved':True,'scope':'IN_MEMORY_MOCK_ONLY'})
            adapter.send(store.outbox()[0]['message'])
        finally:client.close()
        assert requests[0]['parse_mode']=='HTML'
        reopened=Store(temporary);assert reopened.recover()
        restart=Runtime(reopened).process(snapshot(),ASOF);assert not restart['signals']
        bar=future_bar(s);reopened.add_candles({'symbol':s['symbol'],'frames':{'M15':[bar]},'asof':ASOF+900})
        Runtime(reopened).resolve(s['symbol'],ASOF+900)
        resolved=report(reopened);assert resolved['signals'][0]['outcome']['status']=='TP'
        proof={'generated_at':datetime.now(timezone.utc).isoformat(),'evidence_kind':'SYNTHETIC_INTEGRATION_ONLY_NOT_STRATEGY_PERFORMANCE',
               'actual_codex_executable':True,'worker':first['runs'][0]['resources'],'initial':initial,'resolved':resolved,
               'restart_new_signals':len(restart['signals']),'durable_signal_count':len(reopened.signals()),'durable_preview_count':len(reopened.outbox()),
               'existing_client_mock_requests':len(requests),'remote_outbound_calls':0,'broker_orders':0,
               'claude_provider':'PENDING_ACTUAL_AI_MODEL','kimi_provider':'PENDING_ACTUAL_AI_MODEL'}
        (output/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
        (output/'telegram_preview.txt').write_text(store.outbox()[0]['message'],encoding='utf-8')
        (output/'dashboard_fixture.json').write_text(json.dumps({**resolved,'runtime':{'enabled':True,'running':True,'source':'SYNTHETIC_BROWSER_TEST'}}),encoding='utf-8')
        print(json.dumps({k:proof[k] for k in ['actual_codex_executable','worker','restart_new_signals','durable_signal_count','durable_preview_count','existing_client_mock_requests','remote_outbound_calls','broker_orders']},indent=2))

if __name__=='__main__':main()
