from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

WATCHLIST = ["XAUUSD", "NAS100", "US500", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY"]


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("USDr", "").replace(".r", "").upper()


def mt5_symbol(symbol: str) -> str | None:
    if mt5 is None:
        return None
    for candidate in [symbol, symbol + "r", symbol + ".r"]:
        info = mt5.symbol_info(candidate)
        if info is not None:
            return candidate
    return None


def market_snapshot() -> list[dict[str, Any]]:
    if mt5 is None or not mt5.initialize():
        return []

    markets = []
    try:
        for requested in WATCHLIST:
            actual = mt5_symbol(requested)
            if not actual:
                continue
            tick = mt5.symbol_info_tick(actual)
            info = mt5.symbol_info(actual)
            if not tick or not info:
                continue

            bid = float(tick.bid or 0)
            ask = float(tick.ask or 0)
            price = (bid + ask) / 2 if bid and ask else float(info.last or bid or ask or 0)
            markets.append({
                "symbol": normalize_symbol(requested),
                "broker_symbol": actual,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread": abs(ask - bid) if ask and bid else 0,
                "state": "WATCHING",
                "score": 0,
                "setup": "Scanner initializing",
                "reason": "Live quote received. Strategy engine is the next layer.",
                "session": "Live",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    finally:
        mt5.shutdown()
    return markets


@app.get("/api/health")
def health():
    return {"ok": True, "service": "trading-hub-market-engine", "mt5_available": mt5 is not None}


@app.get("/api/market/radar")
def radar():
    markets = market_snapshot()
    return {
        "source": "MT5",
        "live": bool(markets),
        "markets": markets,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
