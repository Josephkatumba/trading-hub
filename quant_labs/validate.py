"""Write explicit milestone validation evidence; no live platform access."""
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import unittest

def main():
    root=Path(__file__).resolve().parent;stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('quant_labs.tests'))
    record={'at':datetime.now(timezone.utc).isoformat(),'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'log':stream.getvalue(),'test_sha256':hashlib.sha256((root/'tests.py').read_bytes()).hexdigest()}
    (root/'verification/tests.json').write_text(json.dumps(record,indent=2))
    print(stream.getvalue())
    if not result.wasSuccessful():raise SystemExit(1)
if __name__=='__main__':main()
