"""Isolated regression runner; opt into expensive local-store equivalence tests."""
import argparse
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import unittest

parser = argparse.ArgumentParser()
parser.add_argument("--with-live-store", action="store_true")
parser.add_argument("--verbose", action="store_true", help="Show each test to locate stalls")
parser.add_argument("--timeout", type=int, default=120, help="Per-test/discovery hard timeout with thread traces")
args = parser.parse_args()
backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
sys.path.insert(0, str(backend / "tests"))

with tempfile.TemporaryDirectory() as temporary:
    os.environ["TRADING_HUB_DATA_DIR"] = temporary
    # Isolate owner process intent as well as market data before importing main.
    os.environ['TRADEDEN_CONTROL_FILE'] = str(Path(temporary) / 'control.json')
    from ops.control import set_state
    set_state('RUNNING', 'Isolated test fixture only')
    # A locally activated paper consumer must not change legacy fixture assumptions.
    # Live-consumer tests explicitly opt in within their own isolated test scope.
    os.environ["TRADEDEN_QUANT_LIVE_ENABLED"] = "0"
    if args.timeout > 0:
        faulthandler.dump_traceback_later(args.timeout, exit=True)
    suite = unittest.defaultTestLoader.discover(str(backend / "tests"))
    def isolated(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                yield from isolated(item)
            elif args.with_live_store or "RealStoreEquivalence" not in item.id():
                yield item
    class BoundedResult(unittest.TextTestResult):
        def startTest(self, test):
            if args.timeout > 0:
                faulthandler.dump_traceback_later(args.timeout, exit=True)
            super().startTest(test)

        def stopTest(self, test):
            faulthandler.cancel_dump_traceback_later()
            super().stopTest(test)

    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, resultclass=BoundedResult).run(unittest.TestSuite(isolated(suite)))
    faulthandler.cancel_dump_traceback_later()
    sys.exit(not result.wasSuccessful())
