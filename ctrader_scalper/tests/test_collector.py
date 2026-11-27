"""TradeDen Collector cBot: must stay data-only (no trading API calls) and must compile."""
from __future__ import annotations

import re
import subprocess
import unittest

from test_parity import BUILD, CSC, ROOT, find_api_dll

SOURCE = ROOT / "cbot" / "TradeDenCollector.cs"

# Every cAlgo call that can create, change, cancel or close an order or position.
FORBIDDEN = [
    "ExecuteMarketOrder", "ExecuteMarketRangeOrder", "PlaceLimitOrder", "PlaceStopOrder", "PlaceStopLimitOrder",
    "ClosePosition", "ModifyPosition", "CancelPendingOrder", "ModifyPendingOrder", "ReversePosition",
    "ModifyStopLossPrice", "ModifyTakeProfitPrice", "ModifyStopLossPips", "ModifyTakeProfitPips", "ModifyVolume",
    "ModifyTrailingStop", "ModifyStopLossTriggerMethod", "ExecuteMarketOrderAsync", "ClosePositionAsync",
    "PendingOrders", "TradeOperation", "TradeResult",
]


def _code_only(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


class CollectorSafetyTest(unittest.TestCase):
    def test_no_trading_api_in_source(self):
        code = _code_only(SOURCE.read_text(encoding="utf-8"))
        hits = [name for name in FORBIDDEN if re.search(r"\b" + name + r"\b", code)]
        self.assertEqual(hits, [], f"collector must be data-only; found {hits}")
        # Position objects expose .Close()/.Modify*(); none may be called.
        self.assertIsNone(re.search(r"\.\s*(Close|Modify\w*|Reverse|Cancel)\s*\(", code))

    def test_live_account_refused_by_default(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertRegex(code, r'Parameter\("Allow live account", DefaultValue = false')
        self.assertIn("if (Account.IsLive && !AllowLive)", code)

    def test_compiles_against_calgo_api(self):
        api = find_api_dll()
        if not CSC.exists() or api is None:
            self.skipTest("csc.exe or cAlgo.API.dll not available")
        BUILD.mkdir(parents=True, exist_ok=True)
        res = subprocess.run([str(CSC), "-nologo", "-nowarn:1685", "-target:library", f"-r:{api}",
                              f"-out:{BUILD / 'TradeDenCollector.dll'}", str(SOURCE)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
