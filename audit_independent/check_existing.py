"""Relevant existing regressions with all data writes redirected to a temporary store."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root/'backend/tests')]
with tempfile.TemporaryDirectory() as folder:
    os.environ['TRADING_HUB_DATA_DIR']=folder
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_signal_outcomes','test_strategy_bank','test_market_data','test_source_quality'])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(not result.wasSuccessful())
