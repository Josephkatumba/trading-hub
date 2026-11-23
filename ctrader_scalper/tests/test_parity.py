"""C# cBot SignalCore vs Python reference: identical candidates on real data.

Compiles cbot/TradeDenScalper.cs + cbot/tests/SignalParity.cs with the
Windows .NET Framework compiler against cTrader's cAlgo.API.dll (found
automatically, or via CALGO_API_DLL). Skips when either is unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.market import INSTRUMENTS, load_m1  # noqa: E402
from engine.strategy import build_frames, generate_candidates  # noqa: E402

CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
BUILD = ROOT / "build" / "parity"


def find_api_dll() -> Path | None:
    env = os.environ.get("CALGO_API_DLL")
    if env and Path(env).exists():
        return Path(env)
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Spotware" / "cTrader"
    hits = sorted(base.glob("*/app_*/algohost.netframework/cAlgo.API.dll"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def build_harness() -> Path:
    api = find_api_dll()
    if not CSC.exists() or api is None:
        raise unittest.SkipTest("csc.exe or cAlgo.API.dll (netframework) not available")
    BUILD.mkdir(parents=True, exist_ok=True)
    exe = BUILD / "SignalParity.exe"
    shutil.copy(api, BUILD / "cAlgo.API.dll")
    cmd = [str(CSC), "-nologo", "-nowarn:1685", "-target:exe", f"-r:{api}", f"-out:{exe}",
           str(ROOT / "cbot" / "TradeDenScalper.cs"), str(ROOT / "cbot" / "tests" / "SignalParity.cs")]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise AssertionError("C# build failed:\n" + res.stdout + res.stderr)
    return exe


class ParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = build_harness()

    def check_symbol(self, symbol: str):
        m1 = load_m1(symbol)
        frames = build_frames(m1)
        fmt = "%Y-%m-%dT%H:%M:%S"
        paths = {}
        for name, df in (("m5", frames["m5"]), ("m15", frames["m15"]), ("m1", m1)):
            out = df[["time", "open", "high", "low", "close"] + (["spread_px"] if name == "m5" else [])].copy()
            out["time"] = out["time"].dt.strftime(fmt)
            paths[name] = BUILD / f"{symbol}_{name}.csv"
            out.to_csv(paths[name], index=False, float_format="%.10g")
        result = BUILD / f"{symbol}_cs_candidates.csv"
        crypto = "1" if INSTRUMENTS[symbol].crypto else "0"
        subprocess.run([str(self.exe), str(paths["m5"]), str(paths["m15"]), str(paths["m1"]), crypto, str(result)], check=True)
        cs = pd.read_csv(result, parse_dates=["time"])
        py = generate_candidates(symbol, m1)
        self.assertGreater(len(py), 100, "too few candidates to be a meaningful parity test")
        key = ["time", "side", "setup"]
        merged = py.merge(cs, on=key, how="outer", suffixes=("_py", "_cs"), indicator=True)
        only = merged[merged["_merge"] != "both"]
        both = merged[merged["_merge"] == "both"]
        match_rate = len(both) / max(len(py), len(cs))
        score_eq = (both["score_py"] == both["score_cs"]).mean()
        anchor_err = ((both["anchor_py"] - both["anchor_cs"]).abs() / both["atr_py"]).max()
        print(f"{symbol}: py={len(py)} cs={len(cs)} matched={len(both)} only_one_side={len(only)} "
              f"score_equal={score_eq:.4f} max_anchor_err_atr={anchor_err:.2e}")
        self.assertGreaterEqual(match_rate, 0.999, only.head(10).to_string())
        self.assertGreaterEqual(score_eq, 0.999)
        self.assertLess(anchor_err, 1e-6)

    def test_xauusd(self):
        self.check_symbol("XAUUSD")

    def test_eurusd(self):
        self.check_symbol("EURUSD")

    def test_btcusd(self):
        self.check_symbol("BTCUSD")


if __name__ == "__main__":
    unittest.main()
