"""Temporary infrastructure-only provider contracts, never real Claude/Kimi models."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from quant_labs.control import ControlPlane
from quant_labs.tests import fixture_cache
from quant_labs.data import snapshot,digest
from quant_labs.frozen import VERSION_DIR
from quant_labs.provider_bridge import register_source,cached_snapshot,probe
from quant_labs.next_phase.generate_intents import causal_snapshot
from quant_live.adapter import immutable
from quant_live.fixtures import snapshot as fake_snapshot,ASOF
from quant_live.store import Store
from quant_live.model_host import validate_source

NOOP='def detect(snapshot):\n return []\n'

def manifest(lab):
    return {'lab':lab,'key':'infrastructure_noop','version':'0.0.1','name':'NO STRATEGY: temporary infrastructure contract',
            'timeframe':'M15','requirements':{'M15':80,'H1':64},'instruments':['EURUSD'],'risk_model':'No trade decisions',
            'planned_rr':'Not applicable','known_limitations':'Synthetic test fixture only; not authored by an actual Claude/Kimi session.',
            'authorship':{'lab':lab,'session_reference':'ISOLATED CONTRACT FIXTURE, NOT ACTUAL AI AUTHORSHIP'}}

class ProviderBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        fixture_cache(self.root/'cache');self.control=ControlPlane(self.root/'state')
        dataset=snapshot(self.root/'cache',self.control.root/'shared')
        self.control.initialize(dataset,digest((VERSION_DIR/'freeze.json').read_bytes()))
        self.tokens=json.loads((self.control.root/'owner/credentials.json').read_text())
    def test_each_lab_own_capability_registers_noop_contract(self):
        for lab in ('codex','claude','kimi'):
            record=register_source(self.control,self.tokens['lab:'+lab],lab,manifest(lab),NOOP)
            self.assertEqual(record['lab'],lab)
        self.assertEqual([r['strategies'] for r in self.control.public()['labs']],[1,1,1])
    def test_cross_lab_and_false_manifest_binding_denied(self):
        with self.assertRaises(PermissionError):register_source(self.control,self.tokens['lab:codex'],'claude',manifest('claude'),NOOP)
        with self.assertRaises(ValueError):register_source(self.control,self.tokens['lab:codex'],'codex',manifest('kimi'),NOOP)
    def test_version_binding_immutable(self):
        m=manifest('codex');token=self.tokens['lab:codex'];register_source(self.control,token,'codex',m,NOOP)
        self.assertTrue(register_source(self.control,token,'codex',m,NOOP)['already_registered'])
        with self.assertRaises(ValueError):register_source(self.control,token,'codex',m,NOOP+'\n# changed')
    def test_cache_probe_executes_without_live_database_writes(self):
        data=fake_snapshot();cache=Store(self.root/'live_cache');cache.add_candles(data)
        report={'runtime':{'latest_inputs':{'EURUSD':{**data,'source':'MT5_SHARED_COLLECTOR'}}}}
        m=manifest('codex');token=self.tokens['lab:codex'];register_source(self.control,token,'codex',m,NOOP)
        result=probe(self.control,token,'codex',m,report,cache.path,'EURUSD',now=ASOF)
        self.assertEqual(result['status'],'COMPLETE');self.assertEqual(result['live_writes'],0)
        self.assertTrue(result['resources']['enforced']);self.assertEqual(cache.signals(),[]);self.assertEqual(cache.outbox(),[])
        report['runtime']['latest_inputs']['EURUSD']['asof']=ASOF-61
        self.assertEqual(probe(self.control,token,'codex',m,report,cache.path,'EURUSD',now=ASOF)['status'],'INPUT_REJECTED')
    def test_causal_replay_never_supplies_future_bar_extremes(self):
        data=fake_snapshot();m15=[dict(b) for b in data['frames']['M15']];h1=tuple(immutable(b) for b in data['frames']['H1'])
        position=len(m15)-1;at=m15[position]['utc'];meta={**data['metadata'],'broker_symbol':'EURUSD'}
        first=causal_snapshot('EURUSD',at,tuple(immutable(b) for b in m15),h1,position,len(h1)-1,meta,'test')
        m15[position].update(high=1e12,low=.000001,close=1e9)
        second=causal_snapshot('EURUSD',at,tuple(immutable(b) for b in m15),h1,position,len(h1)-1,meta,'test')
        self.assertEqual(first['frames'],second['frames']);self.assertEqual(first['quote'],second['quote'])
        self.assertTrue(all(b['utc']+900<=at for b in first['frames']['M15']))
    def test_all_actual_codex_candidates_valid_and_hash_bound(self):
        candidates=json.loads((ROOT/'quant_labs/next_phase/candidates.json').read_text(encoding='utf-8'))
        self.assertEqual({r['target_net_r'] for r in candidates},{2,3,4,5,7,9,None})
        for row in candidates:
            source=Path(row['source']).read_text(encoding='utf-8');validate_source(source)
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),row['source_sha256'])

if __name__=='__main__':unittest.main()
