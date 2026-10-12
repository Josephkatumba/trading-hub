"""Isolated regression runner; opt into expensive local-store equivalence tests."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest

parser = argparse.ArgumentParser()
parser.add_argument("--with-live-store", action="store_true")
args = parser.parse_args()
backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
sys.path.insert(0, str(backend / "tests"))

with tempfile.TemporaryDirectory() as temporary:
    os.environ["TRADING_HUB_DATA_DIR"] = temporary
    suite = unittest.defaultTestLoader.discover(str(backend / "tests"))
    def isolated(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                yield from isolated(item)
            elif args.with_live_store or "RealStoreEquivalence" not in item.id():
                yield item
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(isolated(suite)))
    sys.exit(not result.wasSuccessful())
