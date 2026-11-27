"""Synthetic admission tests use isolated stores only; never the live ledger."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quant_labs.paper_integration.guards import install, KEYS, nonoverlapping
from quant_live.store import Store

ROOT = Path(__file__).resolve().parents[2]

def models():
    result = []
    import hashlib
    for key in KEYS:
        folder = ROOT / 'quant_labs/state/labs/codex/strategies' / key
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        source = (folder / 'model.py').read_text(encoding='utf-8')
        result.append(dict(lab='codex', key=key, version='0.1.0', manifest=manifest, source=source,
                           sha=hashlib.sha256(source.encode()).hexdigest()))
    return result

class CodexPaperAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        install(self.store, models(), {'purpose': 'ISOLATED SYNTHETIC TEST ONLY'})

    def signal(self, sid, at, model=KEYS[0], symbol='BTCUSD'):
        return dict(signal_id=sid, lab='codex', model_key=model, model_version='0.1.0', symbol=symbol,
                    timeframe='M15', signal_bar_closed_at=at, entry_at=at, deadline=at+21600,
                    input_sha256='ISOLATED_SYNTHETIC_FIXTURE')

    def outcome(self, sid, result):
        with self.store.db() as db:
            db.execute('INSERT INTO outcomes(signal,body,sha,at) VALUES(?,?,?,?)', (sid,json.dumps(result),'test',1))

    def test_overlap_and_duplicate_excluded_with_atomic_guard(self):
        self.assertTrue(self.store.record(self.signal('first',1000), True))
        self.assertFalse(self.store.record(self.signal('first',1000), True))
        self.assertFalse(self.store.record(self.signal('overlap',1900), True))
        self.assertEqual(len(self.store.signals()), 1)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM codex_forward_rejections').fetchone()[0],1)

    def test_known_exit_releases_at_exit_but_unknown_revision_relocks(self):
        self.store.record(self.signal('first',1000), True)
        self.outcome('first',dict(status='TP',simulated_net_r=2,exit_at=1800))
        self.assertFalse(self.store.record(self.signal('before',1700), True))
        self.assertTrue(self.store.record(self.signal('after',1800), True))
        self.outcome('first',dict(status='AMBIGUOUS',simulated_net_r=None,exit_at=None))
        self.assertFalse(self.store.record(self.signal('revision',2000), True))

    def test_missing_outcome_locks_to_original_deadline_not_forever(self):
        self.store.record(self.signal('first',1000), True)
        self.assertFalse(self.store.record(self.signal('before',22599), True))
        self.assertTrue(self.store.record(self.signal('after',22600), True))

    def test_models_markets_and_unrelated_production_unchanged(self):
        self.store.record(self.signal('first',1000), True)
        self.assertTrue(self.store.record(self.signal('variant',1100,model=KEYS[1]), True))
        self.assertTrue(self.store.record(self.signal('market',1100,symbol='EURUSD'), True))
        self.assertFalse(self.store.record(self.signal('badmarket',1100,symbol='ETHUSD'), True))
        self.assertTrue(self.store.record(self.signal('unrelated',1100,model='compression_escape',symbol='ETHUSD'), True))

    def test_each_model_registered_experimental_with_no_alerts_and_immutable_source(self):
        for model in models():
            self.store.register(model['manifest'],model['source'],model['manifest']['authorship'])
            self.store.register(model['manifest'],model['source'],model['manifest']['authorship'])
            registered = self.store.model('codex',model['key'],'0.1.0')
            self.assertEqual(registered['source'],model['source'])
            self.assertEqual((registered['status'],registered['scan_enabled'],registered['alert_enabled']),('EXPERIMENTAL',1,0))
        self.assertEqual(len(self.store.models()),7)

    def test_forward_metrics_rebuild_after_late_ambiguity_and_exclude_duplicates(self):
        first={**self.signal('first',1000),'confirmed':True}
        second={**self.signal('second',2000),'confirmed':True}
        known={'first':dict(simulated_net_r=2,exit_at=1900)}
        accepted,excluded=nonoverlapping([first,first,second],known)
        self.assertEqual([s['signal_id'] for s in accepted],['first','second'])
        self.assertEqual(excluded,['first'])
        accepted,excluded=nonoverlapping([first,second],{'first':dict(simulated_net_r=None,exit_at=None)})
        self.assertEqual([s['signal_id'] for s in accepted],['first'])
        self.assertEqual(excluded,['second'])
