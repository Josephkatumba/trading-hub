from __future__ import annotations

from datetime import datetime, timezone, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from scanner import analyze_symbol
from macro import fundamentals_snapshot
from observations import record_markets, recent_observations

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

app = FastAPI(title="Trading Hub Market Engine", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

SYMBOL_ALIASES = {
    "XAUUSD": ["XAUUSD", "GOLD"],
    "NAS100": ["NAS100", "US100", "USTEC", "NAS"],
    "US500": ["US500", "SPX500", "SP500"],
    "BTCUSD": ["BTCUSD", "BTCUSDm", "BTCUSD.r"],
    "ETHUSD": ["ETHUSD", "ETHUSDm", "ETHUSD.r"],
    "EURUSD": ["EURUSD"],
    "GBPUSD": ["GBPUSD"],
    "USDJPY": ["USDJPY"],
    "USDCHF": ["USDCHF"],
    "USDCAD": ["USDCAD"],
    "AUDUSD": ["AUDUSD"],
    "NZDUSD": ["NZDUSD"],
    "XAGUSD": ["XAGUSD", "SILVER"],
    "EURJPY": ["EURJPY"],
    "GBPJPY": ["GBPJPY"],
}
WATCHLIST = list(SYMBOL_ALIASES)
ENGINE_STARTED = datetime.now(timezone.utc)

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("USDr", "").replace(".r", "").upper()


def mt5_symbol(symbol: str) -> str | None:
    if mt5 is None:
        return None
    candidates = SYMBOL_ALIASES.get(symbol, [symbol])
    for base in candidates:
        for candidate in [base, base + "r", base + ".r", base + "m", base + ".m"]:
            if mt5.symbol_info(candidate) is not None:
                return candidate
    return None


def _bar_dt(row: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(float(row["time"]), tz=timezone.utc)


def session_context(rows: list[dict[str, Any]], price: float) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    london_now = now_utc.astimezone(LONDON)
    ny_now = now_utc.astimezone(NEW_YORK)

    # Treat London and New York as independent local sessions. The important
    # strategy window is the period after London's close while New York is active.
    london_active = time(8, 0) <= london_now.time() < time(16, 30)
    ny_active = time(8, 0) <= ny_now.time() < time(17, 0)

    if ny_active and not london_active:
        session = "New York"
    elif london_active and ny_active:
        session = "London / New York Overlap"
    elif london_active:
        session = "London"
    elif time(0, 0) <= london_now.time() < time(8, 0):
        session = "Asia"
    else:
        session = "Off-hours"

    # Find the most recent London session represented in the M15 history.
    # Before London's open, this deliberately falls back to the previous
    # completed session instead of looking for bars on the new London date.
    london_bars = []
    london_date = None
    for days_back in range(8):
        candidate_date = london_now.date() - timedelta(days=days_back)
        candidate = []
        for row in rows:
            dt = _bar_dt(row).astimezone(LONDON)
            if dt.date() == candidate_date and time(8, 0) <= dt.time() < time(16, 30):
                candidate.append(row)
        if candidate:
            london_bars = candidate
            london_date = candidate_date
            break

    london_high = max((float(r["high"]) for r in london_bars), default=0.0)
    london_low = min((float(r["low"]) for r in london_bars), default=0.0)
    london_complete = bool(london_date) and (
        london_date < london_now.date() or london_now.time() >= time(16, 30)
    )

    alignment = None
    if london_complete and session == "New York" and london_high and london_low:
        # Use 0.35 ATR-ish proximity later in the scanner, while keeping this
        # context simple and explainable.
        distance_high = abs(price - london_high)
        distance_low = abs(price - london_low)
        span = max(london_high - london_low, 0.0000001)
        if distance_high <= span * 0.08:
            alignment = "New York is retesting the London high, watch for bearish confirmation"
        elif distance_low <= span * 0.08:
            alignment = "New York is retesting the London low, watch for bullish confirmation"

    return {
        "session": session,
        "london_high": london_high,
        "london_low": london_low,
        "london_complete": london_complete,
        "session_alignment": alignment,
        "london_date": london_date.isoformat() if london_date else None,
        "new_york_time": ny_now.isoformat(),
    }


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
            rates = mt5.copy_rates_from_pos(actual, mt5.TIMEFRAME_M15, 0, 300)
            h1_rates = mt5.copy_rates_from_pos(actual, mt5.TIMEFRAME_H1, 0, 160)
            if not tick or not info or rates is None or h1_rates is None:
                continue
            bid = float(tick.bid or 0)
            ask = float(tick.ask or 0)
            raw_last = float(info.last or 0)
            if (bid <= 0 and ask <= 0 and raw_last <= 0):
                continue

            price = (bid + ask) / 2 if bid and ask else float(info.last or bid or ask or 0)
            rows = [{
                "time": float(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            } for r in rates]
            higher_rows = [{
                "time": float(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            } for r in h1_rates]
            context = session_context(rows, price)
            current_spread = abs(ask - bid) if ask and bid else 0
            scan = analyze_symbol(
                actual,
                rows,
                spread=current_spread,
                session_context=context,
                higher_rows=higher_rows,
            )
            reference = float(rows[-97]["close"]) if len(rows) >= 97 else float(rows[0]["close"])
            change_pct = ((price - reference) / reference * 100) if reference else 0.0
            markets.append({
                "symbol": normalize_symbol(requested),
                "broker_symbol": actual,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread": current_spread,
                "change_pct": change_pct,
                **scan,
                **context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    finally:
        mt5.shutdown()
    record_markets(markets)
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
        "engine_version": "0.3.0",
        "strategy": "trendline-first-v3",
        "execution_enabled": False,
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
        "markets": markets,
        "fundamentals": fundamentals_snapshot(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/market/observations")
def observations(limit: int = 100):
    return {
        "observations": recent_observations(limit),
        "limit": max(1, min(limit, 1000)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
