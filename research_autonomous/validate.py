"""Persist test evidence separately from run-time source snapshots."""
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import unittest
from .experiment import BASE

def main():
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromName('research_autonomous.test_foundation')
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    evidence={'at':datetime.now(timezone.utc).isoformat(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
              'passed':result.wasSuccessful(),'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in BASE.glob('*.py')},'log':stream.getvalue()}
    (BASE/'validation.json').write_text(json.dumps(evidence,indent=2))
    print(stream.getvalue())
    if not result.wasSuccessful():raise SystemExit(1)
if __name__=='__main__':main()
