"""Compiles the cBot with cbot/tests/SafetyTests.cs against cTrader's cAlgo.API.dll and runs the safety suite."""
from __future__ import annotations

import shutil
import subprocess
import unittest

from test_parity import BUILD, CSC, ROOT, find_api_dll


class SafetyTest(unittest.TestCase):
    def test_execution_safeguards(self):
        api = find_api_dll()
        if not CSC.exists() or api is None:
            self.skipTest("csc.exe or cAlgo.API.dll not available")
        BUILD.mkdir(parents=True, exist_ok=True)
        exe = BUILD / "SafetyTests.exe"
        shutil.copy(api, BUILD / "cAlgo.API.dll")
        res = subprocess.run([str(CSC), "-nologo", "-nowarn:1685", "-target:exe", f"-r:{api}", f"-out:{exe}",
                              str(ROOT / "cbot" / "TradeDenScalper.cs"), str(ROOT / "cbot" / "tests" / "SafetyTests.cs")],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        print(run.stdout.strip())
        self.assertEqual(run.returncode, 0, run.stdout)


if __name__ == "__main__":
    unittest.main()
