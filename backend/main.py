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

WATCHLIST = ["XAUUSD", "NAS100", "US500", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY"]
ENGINE_STARTED = datetime.now(timezone.utc)


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
            rates = mt5.copy_rates_from_pos(actual, mt5.TIMEFRAME_M15, 0, 250)
            if not tick or not info or rates is None:
                continue

            bid = float(tick.bid or 0)
            ask = float(tick.ask or 0)
            price = (bid + ask) / 2 if bid and ask else float(info.last or bid or ask or 0)
            rows = [{"open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in rates]
            scan = analyze_symbol(actual, rows)
            markets.append({
                "symbol": normalize_symbol(requested),
                "broker_symbol": actual,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread": abs(ask - bid) if ask and bid else 0,
                **scan,
                "session": "Live",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    finally:
        mt5.shutdown()
    return markets


@app.get("/api/health")
def health():
    connected = False
    terminal = None
    account = None
    symbols = 0
    error = None

    if mt5 is not None:
        try:
            connected = bool(mt5.initialize())
            if connected:
                info = mt5.terminal_info()
                acct = mt5.account_info()
                terminal = {
                    "connected": bool(info),
                    "version": ".".join(map(str, mt5.version() or [])) if mt5.version() else None,
                }
                account = {
                    "login": int(acct.login) if acct else None,
                    "server": str(acct.server) if acct else None,
                }
                symbols = int(mt5.symbols_total() or 0)
        except Exception as exc:
            error = str(exc)
        finally:
            try:
                mt5.shutdown()
            except Exception:
                pass

    return {
        "ok": True,
        "service": "trading-hub-market-engine",
        "mt5_available": mt5 is not None,
        "mt5_connected": connected,
        "terminal": terminal,
        "account": account,
        "symbols": symbols,
        "uptime_started": ENGINE_STARTED.isoformat(),
        "error": error,
    }


@app.get("/api/market/radar")
def radar():
    markets = market_snapshot()
    return {
        "source": "MT5",
        "live": bool(markets),
        "markets": markets,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/fundamentals")
def fundamentals():
    return fundamentals_snapshot()


@app.get("/api/market/context")
def context():
    markets = market_snapshot()
    return {
        "live": bool(markets),
        "markets": [
            {
                "symbol": m["symbol"],
                "price": m["price"],
                "bid": m["bid"],
                "ask": m["ask"],
                "spread": m["spread"],
                "state": m.get("state"),
                "score": m.get("score"),
                "reason": m.get("reason"),
                "timestamp": m.get("timestamp"),
            }
            for m in markets
        ],
        "fundamentals": fundamentals_snapshot(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
