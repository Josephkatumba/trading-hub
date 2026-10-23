"""Tests for maintenance tools on temporary folders only (real state is never touched)."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from .relocate_runtime import relocate, hashes, is_junction

BASE = Path(__file__).resolve().parents[1]


class RelocateRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Fixture state outside OneDrive: freshly created synced folders stay locked while uploading,
        # which tests the environment rather than the tool. The real run retries those locks.
        self.src = tempfile.TemporaryDirectory(prefix='tradeden_reloc_state_')
        self.dst = tempfile.TemporaryDirectory(prefix='tradeden_reloc_test_')                      # local
        self.state = Path(self.src.name)
        job = self.state / 'runtime' / 'job1'
        job.mkdir(parents=True)
        (job / 'request.json').write_text('{"a":1}')
        (job / 'worker-result.json').write_text('{"status":"FAILED"}')
        (self.state / 'm5' / 'runtime' / 'job2').mkdir(parents=True)
        (self.state / 'm5' / 'runtime' / 'job2' / 'request.json').write_text('{"b":2}')
        for db in (self.state / 'control.sqlite3', self.state / 'm5' / 'control_m5.sqlite3'):
            c = sqlite3.connect(db)
            c.execute('CREATE TABLE jobs(id TEXT, state TEXT)')
            c.commit()
            c.close()
        self.before = hashes(self.state / 'runtime')

    def tearDown(self):
        for link in (self.state / 'runtime', self.state / 'm5' / 'runtime'):
            if is_junction(link):
                os.rmdir(link)  # removes the junction only, never its target
        self.src.cleanup()
        self.dst.cleanup()

    def test_dry_run_changes_nothing(self):
        report = relocate(self.state, self.dst.name)
        self.assertEqual(report['folders']['v1']['status'], 'DRY_RUN')
        self.assertFalse(is_junction(self.state / 'runtime'))

    def test_apply_preserves_hashes_evidence_and_is_idempotent(self):
        report = relocate(self.state, self.dst.name, apply=True)
        self.assertEqual(report['folders']['v1']['status'], 'RELOCATED')
        self.assertTrue(is_junction(self.state / 'runtime'))
        self.assertEqual(hashes(self.state / 'runtime'), self.before)
        self.assertEqual(hashes(Path(self.dst.name) / 'v1'), self.before)
        archive = self.state / report['folders']['v1']['evidence_archive']
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(sorted(z.namelist()), sorted(self.before))
        (self.state / 'runtime' / 'job3').mkdir()  # new writes land in the local target
        self.assertTrue((Path(self.dst.name) / 'v1' / 'job3').is_dir())
        again = relocate(self.state, self.dst.name, apply=True)
        self.assertEqual(again['folders']['v1']['status'], 'ALREADY_RELOCATED')
        self.assertEqual(len(json.loads((self.state / 'runtime_location.json').read_text())['history']), 2)

    def test_refuses_while_job_running(self):
        c = sqlite3.connect(self.state / 'control.sqlite3')
        c.execute("INSERT INTO jobs VALUES('x','RUNNING')")
        c.commit()
        c.close()
        with self.assertRaises(RuntimeError):
            relocate(self.state, self.dst.name, apply=True)
        self.assertFalse(is_junction(self.state / 'runtime'))


if __name__ == '__main__':
    unittest.main()
