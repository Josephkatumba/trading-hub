from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from scanner import analyze_symbol
from macro import fundamentals_snapshot

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

app = FastAPI(title="Trading Hub Market Engine", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

SYMBOL_ALIASES = {\n    "XAUUSD": ["XAUUSD", "GOLD"],\n    "NAS100": ["NAS100", "US100", "USTEC", "NAS"],\n    "US500": ["US500", "SPX500", "SP500"],\n    "BTCUSD": ["BTCUSD", "BTCUSDm", "BTCUSD.r"],\n    "ETHUSD": ["ETHUSD", "ETHUSDm", "ETHUSD.r"],\n    "EURUSD": ["EURUSD"],\n    "GBPUSD": ["GBPUSD"],\n    "USDJPY": ["USDJPY"],\n}\nWATCHLIST = list(SYMBOL_ALIASES)
ENGINE_STARTED = datetime.now(timezone.utc)


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("USDr", "").replace(".r", "").upper()


def mt5_symbol(symbol: str) -> str | None:\n    if mt5 is None:\n        return None\n    candidates = SYMBOL_ALIASES.get(symbol, [symbol])\n    for base in candidates:\n        for candidate in [base, base + "r", base + ".r", base + "m", base + ".m"]:\n            info = mt5.symbol_info(candidate)\n            if info is not None:\n                return candidate\n    return None
