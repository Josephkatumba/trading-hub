from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone, time, timedelta
from pathlib import Path
import json
import logging
import os
import threading
import time as monotonic_time
from typing import Any
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

import market_data
from scanner import analyze_symbol
from strategies import CORE_FIELDS, REGISTRY as STRATEGIES, TRENDLINE, MarketInput
from macro import fundamentals_snapshot
from observations import (confirmation_events, record_markets,
                          recent_observations, setup_history, lifecycle_events,
                          record_lifecycle_transition, setup_episodes,
                          latest_broker_symbols, observation_index_stats, outcome_watch_snapshots,
                          performance_observations, snapshots_by_observation_id)
from outcomes import (MARKET_OUTCOMES_FILE, TRADE_OUTCOMES_FILE, append_market_outcome, configured_horizons,
                      derive_market_outcome, list_records, record_trade_outcome,
                      resolve_due_market_outcomes)
from analyst import analyze_snapshot
from performance import performance_report
from market_time import combined_normalization_status, mt5_epoch_to_utc_iso, normalize_mt5_epoch, utc_iso
from ml_dataset import audit_live_dataset
from strategy_lab import strategy_lab_report

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

LOGGER = logging.getLogger("trading_hub.engine")
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173",
                        "http://localhost:4173", "http://127.0.0.1:4173")


def configured_cors_origins() -> list[str]:
    raw = os.getenv("TRADING_HUB_CORS_ORIGINS")
    origins = [part.strip() for part in raw.split(",") if part.strip()] if raw is not None else list(DEFAULT_CORS_ORIGINS)
    for origin in origins:
        parsed = urlsplit(origin)
        if (origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc or
                parsed.path or parsed.query or parsed.fragment):
            raise ValueError("TRADING_HUB_CORS_ORIGINS must contain explicit HTTP(S) origins without paths or wildcards")
    return origins


class LifecycleTransitionRequest(BaseModel):
    to_state: str = Field(min_length=1, max_length=24)
    reason_code: str = Field(default="MANUAL_REVIEW", min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


# One MT5 terminal connection is reused across requests. Previously every radar
# poll and health check called initialize()/shutdown(); a health check could
# then shut the connection down in the middle of a concurrent radar scan.
_MT5_LOCK = threading.RLock()
_MT5_SESSION: dict[str, Any] = {"initialized": False, "initializations": 0}


def ensure_mt5() -> tuple[bool, str | None]:
    """Return (connected, error), initializing or re-initializing only when needed."""
    if mt5 is None:
        return False, "MetaTrader5 package is unavailable"
    with _MT5_LOCK:
        if _MT5_SESSION["initialized"]:
            try:
                if mt5.terminal_info() is not None:
                    return True, None
            except Exception:
                LOGGER.exception("MT5 liveness check failed")
            # Terminal went away: drop the stale session and reconnect below.
            _MT5_SESSION["initialized"] = False
            try:
                mt5.shutdown()
            except Exception:
                LOGGER.exception("MT5 shutdown of stale session failed")
        try:
            connected = bool(mt5.initialize())
        except Exception as exc:
            LOGGER.exception("MT5 initialization failed")
            return False, str(exc)
        _MT5_SESSION["initializations"] += 1
        _MT5_SESSION["initialized"] = connected
        if connected:
            return True, None
        return False, str(getattr(mt5, "last_error", lambda: "MT5 terminal is unavailable")())


def close_mt5() -> None:
    with _MT5_LOCK:
        if mt5 is not None and _MT5_SESSION["initialized"]:
            try:
                mt5.shutdown()
            except Exception:
                LOGGER.exception("MT5 shutdown failed")
        _MT5_SESSION["initialized"] = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    close_mt5()


app = FastAPI(title="Trading Hub Market Engine", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type"],
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
    "GER40": ["GER40", "DE40", "DAX40"],   # IC Markets: DE40
}
# The official Trading Hub market universe (product-facing names; the broker's
# actual symbol is resolved through SYMBOL_ALIASES, e.g. GER40 -> DE40,
# NAS100 -> USTEC). Markets keep the product-facing name as "symbol" and the
# broker's name as "broker_symbol".
OFFICIAL_UNIVERSE = ("XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD",
                     "GBPJPY", "USDJPY", "NAS100", "US500", "GER40")
# Extra instruments scanned in addition (the former watchlist's other symbols).
# TRADING_HUB_EXTRA_SYMBOLS overrides them: a comma-separated list, or empty
# to scan only the official universe.
DEFAULT_EXTRA_SYMBOLS = ("USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "XAGUSD", "EURJPY")


def configured_watchlist(raw: str | None = None) -> list[str]:
    extras = DEFAULT_EXTRA_SYMBOLS if raw is None else [part.strip().upper() for part in raw.split(",") if part.strip()]
    watchlist = list(OFFICIAL_UNIVERSE)
    for symbol in extras:
        if symbol not in watchlist:
            watchlist.append(symbol)
    return watchlist


WATCHLIST = configured_watchlist(os.getenv("TRADING_HUB_EXTRA_SYMBOLS"))
ENGINE_STARTED = datetime.now(timezone.utc)
_SCAN_LOCK = threading.RLock()
_LAST_SCAN: dict[str, Any] = {"status": "NOT_SCANNED", "started_at": None,
                              "completed_at": None, "market_count": 0, "error": None,
                              "elapsed_ms": None}

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


# The bridge heartbeat file also contains login, server, balance and equity.
# Only these non-identifying fields may leave the engine.
BRIDGE_PUBLIC_FIELDS = ("bridge", "version", "terminal_build", "symbol", "execution_enabled")
BRIDGE_STALE_SECONDS = 60


def mt5_bridge_heartbeat() -> dict[str, Any]:
    """Read the optional MQL5 read-only bridge heartbeat (public-safe summary)."""
    configured = os.getenv("TRADING_HUB_BRIDGE_FILE")
    if configured:
        path = Path(configured)
    else:
        appdata = os.getenv("APPDATA")
        path = Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files" / "trading_hub_heartbeat.json" if appdata else None
    if path is None or not path.exists():
        return {"connected": False, "status": "OFFLINE"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = max(0.0, monotonic_time.time() - path.stat().st_mtime)
        status = "CONNECTED" if age <= BRIDGE_STALE_SECONDS else "STALE"
        public = {key: data[key] for key in BRIDGE_PUBLIC_FIELDS if key in data}
        return {"connected": status == "CONNECTED", "status": status, "age_seconds": round(age, 1), **public}
    except Exception as exc:
        return {"connected": False, "status": "UNREADABLE", "error": type(exc).__name__}


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("USDr", "").replace(".r", "").upper()


def mt5_symbol(symbol: str) -> str | None:
    if mt5 is None:
        return None

    candidates = SYMBOL_ALIASES.get(symbol, [symbol])

    # Prefer exact broker symbols first. IC Markets' Market Watch commonly
    # exposes clean names such as XAUUSD, USTEC, US500, EURUSD and BTCUSD.
    expanded = []
    for base in candidates:
        for candidate in [base, base + "r", base + ".r", base + "m", base + ".m"]:
            if candidate not in expanded:
                expanded.append(candidate)

    for candidate in expanded:
        try:
            # Selecting the symbol makes the Python MT5 bridge see symbols
            # that are available in the terminal but not currently selected.
            mt5.symbol_select(candidate, True)
            if mt5.symbol_info(candidate) is not None:
                return candidate
        except Exception:
            continue

    # Final fallback: discover the broker's actual symbol by matching the
    # requested base against the terminal's available symbol names.
    try:
        available = mt5.symbols_get() or []
        names = [str(item.name) for item in available]
        for base in candidates:
            base_upper = base.upper()
            matches = [
                name for name in names
                if name.upper() == base_upper
                or name.upper().startswith(base_upper)
                or name.upper().endswith(base_upper)
            ]
            for name in matches:
                try:
                    mt5.symbol_select(name, True)
                    if mt5.symbol_info(name) is not None:
                        return name
                except Exception:
                    continue
    except Exception:
        pass

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


_STRATEGY_SETUP_FIELDS = ("setup_id", "observation_id", "lifecycle_state", "episode_suppressed")


def _strategy_entry(result, setup: dict[str, Any] | None) -> dict[str, Any]:
    """One markets[i].strategies[] item: the strategy's decisions and its episode."""
    entry: dict[str, Any] = {"strategy_id": result.strategy_id, "strategy_version": result.strategy_version,
                             "mode": result.mode, "status": "OK" if result.ok else "ERROR"}
    if not result.ok:
        entry["error"] = type(result.error).__name__
        return entry
    entry.update({name: result.core(name) for name in CORE_FIELDS})
    entry["setup_family"] = result.payload.get("setup_family")
    entry.update({key: setup[key] for key in _STRATEGY_SETUP_FIELDS if setup and key in setup})
    return entry


def _attach_strategies(scanned: list[tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]]) -> None:
    for market, results, setups in scanned:
        market["strategies"] = [_strategy_entry(result, market if strategy_id == TRENDLINE else setups.get(strategy_id))
                                for strategy_id, result in results.items()]


def market_snapshot() -> list[dict[str, Any]]:
    started_clock = datetime.now(timezone.utc)
    started = monotonic_time.perf_counter()
    with _SCAN_LOCK:
        _LAST_SCAN.update(status="SCANNING", started_at=utc_iso(started_clock), error=None)
    if mt5 is None:
        with _SCAN_LOCK:
            _LAST_SCAN.update(status="MT5_UNAVAILABLE", completed_at=utc_iso(datetime.now(timezone.utc)),
                              market_count=0, error="MetaTrader5 package is unavailable",
                              elapsed_ms=round((monotonic_time.perf_counter() - started) * 1000, 2))
        return []
    initialized, initialize_error = ensure_mt5()
    if not initialized:
        with _SCAN_LOCK:
            _LAST_SCAN.update(status="MT5_OFFLINE", completed_at=utc_iso(datetime.now(timezone.utc)),
                              market_count=0, error=initialize_error,
                              elapsed_ms=round((monotonic_time.perf_counter() - started) * 1000, 2))
        return []

    markets: list[dict[str, Any]] = []
    # Setups of enabled strategies other than trendline; the top-level market
    # fields stay the trendline setup, so these are persisted as their own episodes.
    strategy_markets: list[dict[str, Any]] = []
    scanned: list[tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]] = []
    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    # Timeframes to collect: enabled strategies' declared needs + shared H4/D1 context.
    data_plan = market_data.plan_for(STRATEGIES)
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
            received_at = datetime.now(timezone.utc)
            source_basis = os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE")
            bar_provenance = normalize_mt5_epoch(rates[-1]["time"], source_basis)
            raw_tick_epoch = (float(tick.time_msc) / 1000 if getattr(tick, "time_msc", 0)
                              else float(tick.time) if getattr(tick, "time", 0) else None)
            tick_provenance = normalize_mt5_epoch(raw_tick_epoch, source_basis)
            source_timestamp_quality = combined_normalization_status(bar_provenance, tick_provenance)
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
            # Outcome bars only enter the UTC outcome engine when the MT5 clock
            # basis was explicitly verified. Scanner rows remain untouched.
            normalized_bars = []
            for raw_rate in rates:
                stamp = normalize_mt5_epoch(raw_rate["time"], source_basis)
                if stamp.get("normalization_status") != "VERIFIED":
                    normalized_bars = []
                    break
                normalized_bars.append({"time": datetime.fromisoformat(stamp["normalized_utc"]).timestamp(),
                    "open": float(raw_rate["open"]), "high": float(raw_rate["high"]),
                    "low": float(raw_rate["low"]), "close": float(raw_rate["close"])})
            if normalized_bars:
                bars_by_symbol[normalize_symbol(requested)] = normalized_bars
            higher_rows = [{
                "time": float(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            } for r in h1_rates]
            context = session_context(rows, price)
            current_spread = abs(ask - bid) if ask and bid else 0
            # Market context by timeframe (tick_volume kept as the broker reports it).
            # M15/H1 reuse the bars fetched above; the rows/higher_rows the trendline
            # strategy reads are unchanged.
            bars, unavailable = market_data.fetch_timeframes(mt5, actual, data_plan, fetched={
                "M15": market_data.bars_from_rates(rates), "H1": market_data.bars_from_rates(h1_rates)})
            # The registry runs the enabled strategies (only trendline). Market fields
            # stay the trendline payload exactly; strategy metadata is not added yet.
            results = STRATEGIES.evaluate(MarketInput(actual, rows, spread=current_spread,
                                                      session_context=context, higher_rows=higher_rows,
                                                      bars=bars, unavailable_timeframes=unavailable))
            trendline = results[TRENDLINE]
            if trendline.error is not None:
                raise trendline.error
            scan = trendline.payload
            reference = float(rows[-97]["close"]) if len(rows) >= 97 else float(rows[0]["close"])
            change_pct = ((price - reference) / reference * 100) if reference else 0.0
            tick_utc = tick_provenance.get("normalized_utc") if tick_provenance.get("normalization_status") == "VERIFIED" else None
            tick_age = ((received_at - datetime.fromisoformat(tick_utc)).total_seconds()
                        if tick_utc else None)
            candle_age = (raw_tick_epoch - float(rates[-1]["time"])) if raw_tick_epoch is not None else None
            source_time = (bar_provenance.get("normalized_utc")
                if source_timestamp_quality == "VERIFIED" else None)
            quote = {
                "symbol": normalize_symbol(requested),
                "broker_symbol": actual,
                "price": price,
                "bid": bid,
                "ask": ask,
                "spread": current_spread,
                "change_pct": change_pct,
            }
            provenance = {
                **context,
                "source_timestamp": source_time,
                "backend_received_at": utc_iso(received_at),
                "tick_age_seconds": tick_age,
                "candle_age_seconds": candle_age,
                "time_provenance": {"bar_open_time": bar_provenance,
                    "tick_time": tick_provenance,
                    "backend_received_at": utc_iso(received_at),
                    "observation_time": None,
                    "source_time_basis": source_basis or "UNVERIFIED",
                    "timezone_normalization_status": source_timestamp_quality,
                    "raw_mt5_tick_time_msc": int(tick.time_msc) if getattr(tick, "time_msc", 0) else None},
                "timeframe": "M15",
                "higher_timeframes": ["H1"],
                "received_bars": len(rows),
                "source": "MT5",
                "timestamp": utc_iso(datetime.now(timezone.utc)),
                "market_data": market_data.summary(bars, unavailable, requested in OFFICIAL_UNIVERSE),
            }
            market = {**quote, **scan, **provenance}
            setups: dict[str, dict[str, Any]] = {}
            for strategy_id, result in results.items():
                if strategy_id == TRENDLINE or not result.ok:
                    continue
                strategy = STRATEGIES.get(strategy_id)
                setups[strategy_id] = {**quote, **result.payload, **provenance, "timeframe": strategy.timeframe,
                    "higher_timeframes": list(strategy.higher_timeframes), "strategy_id": strategy_id,
                    "strategy_version": result.strategy_version, "strategy_mode": result.mode}
            markets.append(market)
            strategy_markets.extend(setups.values())
            scanned.append((market, results, setups))
    except Exception as exc:
        LOGGER.exception("Market scan failed")
        with _SCAN_LOCK:
            _LAST_SCAN.update(status="SCAN_ERROR", completed_at=utc_iso(datetime.now(timezone.utc)),
                              market_count=len(markets), error=str(exc),
                              elapsed_ms=round((monotonic_time.perf_counter() - started) * 1000, 2))
        return []
    try:
        record_markets(markets + strategy_markets)
        confirmations = confirmation_events()
        # Indexed equivalents of the former full-log scans: only snapshots that the
        # resolver can act on are loaded (see observations.outcome_watch_snapshots).
        horizons = configured_horizons()
        snapshots_by_id = snapshots_by_observation_id(str(row.get("observation_id")) for row in confirmations)
        existing_outcomes = list_records(MARKET_OUTCOMES_FILE)
        claimed = {str(snapshot.get("observation_id") or "") for snapshot in
                   (snapshots_by_id.get(str(row.get("observation_id"))) for row in confirmations) if snapshot}
        present = {(row.get("setup_id"), row.get("observation_id"), row.get("horizon"),
                    row.get("label_definition")) for row in existing_outcomes}
        watch_snapshots = outcome_watch_snapshots(claimed, {symbol for symbol, bars in bars_by_symbol.items() if bars},
                                                  present, horizons)
        due = resolve_due_market_outcomes(confirmations, snapshots_by_id, bars_by_symbol,
                                           existing_outcomes, horizons,
                                           watch_snapshots=watch_snapshots)
        for outcome in due:
            append_market_outcome(outcome)
    except Exception as exc:
        LOGGER.exception("Market scan persistence or outcome resolution failed")
        with _SCAN_LOCK:
            _LAST_SCAN.update(status="STORAGE_ERROR", completed_at=utc_iso(datetime.now(timezone.utc)),
                              market_count=len(markets), error=str(exc),
                              elapsed_ms=round((monotonic_time.perf_counter() - started) * 1000, 2))
        _attach_strategies(scanned)
        return markets
    _attach_strategies(scanned)
    with _SCAN_LOCK:
        _LAST_SCAN.update(status="CONNECTED" if markets else "NO_MARKETS",
                          completed_at=utc_iso(datetime.now(timezone.utc)), market_count=len(markets),
                          error=None, elapsed_ms=round((monotonic_time.perf_counter() - started) * 1000, 2))
    return markets


@app.get("/api/health")
def health():
    connected = False
    terminal = None
    account = None
    symbols = 0
    error = None
    bridge = mt5_bridge_heartbeat()

    if mt5 is not None:
        try:
            connected, error = ensure_mt5()
            if connected:
                info = mt5.terminal_info()
                acct = mt5.account_info()
                terminal = {
                    "connected": bool(info),
                    "version": ".".join(map(str, mt5.version() or [])) if mt5.version() else None,
                }
                # Never expose login/server: /api/health is readable by any allowed origin.
                account = {"available": acct is not None}
                symbols = int(mt5.symbols_total() or 0)
        except Exception as exc:
            error = str(exc)

    now = datetime.now(timezone.utc)
    with _SCAN_LOCK:
        scan = dict(_LAST_SCAN)
    last_scan = parse_health_time(scan.get("completed_at"))
    scan_age = max(0.0, (now - last_scan).total_seconds()) if last_scan else None
    freshness = ("UNKNOWN" if scan_age is None else "FRESH" if scan_age <= 30 else "STALE")
    data_dir = Path(__file__).resolve().parent / "data"
    storage = {}
    for name in ("setup_observations.jsonl", "setup_lifecycle.jsonl", "setup_confirmations.jsonl",
                 "market_outcomes.jsonl", "trade_outcomes.jsonl"):
        path = data_dir / name
        try:
            stat = path.stat()
            storage[name] = {"status": "AVAILABLE", "bytes": stat.st_size}
            if name == "setup_observations.jsonl":
                storage[name]["index"] = observation_index_stats()
        except FileNotFoundError:
            storage[name] = {"status": "NOT_CREATED", "bytes": 0}
        except OSError as exc:
            storage[name] = {"status": "UNAVAILABLE", "bytes": None, "error": str(exc)}

    return {
        "ok": True,
        "status": "CONNECTED" if connected else "DEGRADED",
        "service": "trading-hub-market-engine",
        "engine_version": "0.4.0",
        "strategy": "trendline-first-v3",
        "execution_enabled": False,
        "mt5_available": mt5 is not None,
        "mt5_connected": connected,
        "mt5_status": "CONNECTED" if connected else "OFFLINE" if mt5 is not None else "UNAVAILABLE",
        "scanner_status": "READY" if callable(analyze_symbol) else "UNAVAILABLE",
        "data_freshness": {"status": freshness, "last_scan_at": scan.get("completed_at"),
                           "age_seconds": scan_age, "market_count": scan.get("market_count", 0)},
        "last_scan": scan,
        "source_time_basis": os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE") or "UNVERIFIED",
        "storage": storage,
        "terminal": terminal,
        "account": account,
        "symbols": symbols,
        "bridge": bridge,
        "uptime_started": utc_iso(ENGINE_STARTED),
        "error": error,
    }


def parse_health_time(value: Any) -> datetime | None:
    from market_time import parse_aware_utc
    return parse_aware_utc(value)


@app.get("/api/market/diagnostics/mt5-time")
def mt5_time_diagnostic(symbols: str | None = None, bars: int = 8):
    """Read-only comparison of MT5 bar/tick epochs against the backend UTC clock."""
    from fastapi import HTTPException
    if mt5 is None:
        raise HTTPException(status_code=503, detail="MetaTrader5 package is unavailable")
    if not ensure_mt5()[0]:
        raise HTTPException(status_code=503, detail="MT5 terminal is unavailable")

    before = datetime.now(timezone.utc)
    try:
        broker_symbols: dict[str, str] = {}
        broker_symbols.update(latest_broker_symbols())
        requested = [part.strip().upper() for part in symbols.split(",") if part.strip()] if symbols else [
            symbol for symbol in ("XAUUSD", "EURUSD", "NAS100", "US500")
            if symbol in broker_symbols]
        requested = list(dict.fromkeys(requested))[:8]
        limit = max(3, min(int(bars), 12))
        result = []
        for symbol in requested:
            actual = broker_symbols.get(symbol)
            if not actual:
                continue
            rates = mt5.copy_rates_from_pos(actual, mt5.TIMEFRAME_M15, 0, limit)
            tick = mt5.symbol_info_tick(actual)
            sampled_at = datetime.now(timezone.utc)
            if rates is None:
                result.append({"symbol": symbol, "broker_symbol": actual,
                               "error": "MT5 returned no M15 rates"})
                continue
            candle_rows = []
            source_basis = os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE")
            for rate in rates:
                opened = datetime.fromtimestamp(float(rate["time"]), tz=timezone.utc)
                normalized = normalize_mt5_epoch(rate["time"], source_basis)
                candle_rows.append({"open_epoch": float(rate["time"]),
                    "open_time_utc": utc_iso(opened),
                    "interpreted_source_time": normalized["interpreted_source_time"],
                    "normalized_utc": normalized["normalized_utc"],
                    "normalization_status": normalized["normalization_status"],
                    "normalization_reason": normalized.get("normalization_reason"),
                    "source_time_basis": normalized.get("source_time_basis"),
                    "scheduled_close_utc": utc_iso(opened + timedelta(minutes=15)),
                    "open": float(rate["open"]), "high": float(rate["high"]),
                    "low": float(rate["low"]), "close": float(rate["close"])})
            tick_epoch = float(tick.time_msc) / 1000 if tick and getattr(tick, "time_msc", 0) else float(tick.time) if tick else None
            tick_utc = datetime.fromtimestamp(tick_epoch, tz=timezone.utc) if tick_epoch is not None else None
            tick_normalized = normalize_mt5_epoch(tick_epoch, source_basis)
            latest = max(candle_rows, key=lambda row: row["open_epoch"]) if candle_rows else None
            last_returned = candle_rows[-1] if candle_rows else None
            open_age = (sampled_at - datetime.fromtimestamp(latest["open_epoch"], tz=timezone.utc)).total_seconds() if latest else None
            result.append({"symbol": symbol, "broker_symbol": actual,
                "backend_utc_at_sample": utc_iso(sampled_at),
                "tick_timestamp_utc_epoch_interpretation": utc_iso(tick_utc) if tick_utc else None,
                "raw_tick_epoch": tick_epoch,
                "normalized_tick_utc": tick_normalized["normalized_utc"],
                "tick_normalization_status": tick_normalized["normalization_status"],
                "tick_normalization_reason": tick_normalized.get("normalization_reason"),
                "source_time_basis": tick_normalized.get("source_time_basis"),
                "tick_minus_backend_seconds": (tick_utc - sampled_at).total_seconds() if tick_utc else None,
                "latest_bar": latest,
                "last_returned_bar": last_returned,
                "rates_returned_chronologically": all(candle_rows[i]["open_epoch"] <= candle_rows[i + 1]["open_epoch"]
                                                        for i in range(len(candle_rows) - 1)),
                "latest_bar_open_age_seconds": open_age,
                "latest_bar_expected_close_age_seconds": open_age - 900 if open_age is not None else None,
                "latest_bar_open_to_tick_seconds": (tick_utc - datetime.fromtimestamp(latest["open_epoch"], tz=timezone.utc)).total_seconds()
                                                     if tick_utc and latest else None,
                "candle_timing_note": "MT5 rate time is treated as candle-open epoch; scheduled M15 close is open + 15 minutes.",
                "candles": candle_rows})
        after = datetime.now(timezone.utc)
        return {"diagnostic": "read_only_mt5_time", "source": "MT5",
                "python_utc_before": utc_iso(before), "python_utc_after": utc_iso(after),
                "symbols_requested": requested, "bars_per_symbol_requested": limit,
                  "server_clock_note": "No independent broker-server wall clock is exposed by the current integration; tick epoch is reported separately for comparison.",
                  "source_time_basis": source_basis or "UNVERIFIED",
                "markets": result}
    finally:
        pass  # MT5 connection is reused across requests; see ensure_mt5().


@app.get("/api/market/radar")
def radar():
    markets = market_snapshot()
    return {
        "source": "MT5",
        "live": bool(markets),
        "markets": markets,
        "timestamp": utc_iso(datetime.now(timezone.utc)),
        "engine_status": "CONNECTED" if markets else _LAST_SCAN.get("status", "UNKNOWN"),
        "mt5_status": "CONNECTED" if markets else _LAST_SCAN.get("status", "UNKNOWN"),
        "error": _LAST_SCAN.get("error"),
        "strategy_registry": STRATEGIES.describe(),
    }


@app.get("/api/market/strategies")
def strategy_registry():
    """Registered strategies and their status (LIVE / DISABLED); only LIVE ones produce setups."""
    return {"strategies": STRATEGIES.describe(), "timestamp": utc_iso(datetime.now(timezone.utc))}


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
        "timestamp": utc_iso(datetime.now(timezone.utc)),
    }

@app.get("/api/market/observations")
def observations(limit: int = Query(default=100, ge=1, le=1000)):
    return {
        "observations": recent_observations(limit),
        "limit": max(1, min(limit, 1000)),
        "timestamp": utc_iso(datetime.now(timezone.utc)),
    }


@app.get("/api/market/setup-episodes")
def setup_episode_feed(bucket: str = Query(default="current", pattern="^(current|confirmed|closed|all)$"),
                       limit: int = Query(default=100, ge=1, le=500), include_shadow: bool = False):
    """Persistent Observatory buckets; existing radar and history routes remain unchanged.
    Shadow-mode strategy episodes are only included on request (Strategy Lab review)."""
    episodes = setup_episodes(bucket, limit, include_shadow=include_shadow)
    payload = ({name: [row for row in episodes if row.get("bucket") == name]
                for name in ("current", "confirmed", "closed")} if bucket == "all" else {"episodes": episodes})
    return {"bucket": bucket, **payload,
            "timestamp": utc_iso(datetime.now(timezone.utc))}


@app.get("/api/market/setups/{setup_id}")
def setup_detail(setup_id: str):
    snapshots = setup_history(setup_id)
    return {"setup_id": setup_id, "snapshots": snapshots,
            "lifecycle_events": lifecycle_events(setup_id),
            "confirmation_events": confirmation_events(setup_id),
            "market_outcomes": list_records(MARKET_OUTCOMES_FILE, setup_id),
            "trade_outcomes": list_records(TRADE_OUTCOMES_FILE, setup_id)}


@app.get("/api/market/setups/{setup_id}/history")
def setup_event_history(setup_id: str):
    return {"setup_id": setup_id, "snapshots": setup_history(setup_id),
            "lifecycle_events": lifecycle_events(setup_id),
            "confirmation_events": confirmation_events(setup_id)}


@app.get("/api/market/setups/{setup_id}/lifecycle")
def setup_lifecycle_history(setup_id: str):
    return {"setup_id": setup_id, "lifecycle_events": lifecycle_events(setup_id)}


@app.get("/api/market/setups/{setup_id}/analysis")
def setup_analysis(setup_id: str, observation_id: str | None = None):
    snapshots = [row for row in setup_history(setup_id)
                 if row.get("record_type") == "setup_snapshot"]
    if observation_id:
        snapshot = next((row for row in snapshots if row.get("observation_id") == observation_id), None)
    else:
        snapshot = snapshots[-1] if snapshots else None
    if not snapshot:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Recorded setup snapshot not found")
    return analyze_snapshot(snapshot)


@app.get("/api/market/performance")
def setup_performance(date: str | None = Query(default=None, min_length=10, max_length=10),
                      days: int = Query(default=1, ge=1, le=30)):
    if date:
        try:
            from datetime import date as date_type
            date_type.fromisoformat(date)
        except ValueError as exc:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="date must use YYYY-MM-DD") from exc
    return performance_report(confirmation_events(), list_records(MARKET_OUTCOMES_FILE),
        performance_observations(), report_date=date, days=days,
        horizons=configured_horizons())


@app.get("/api/market/strategy-lab")
def strategy_lab(recent: int = Query(default=25, ge=1, le=200)):
    """Per-strategy setups, confirmations and verified outcomes (read-only; strategies never mixed)."""
    return {**strategy_lab_report(list_records(MARKET_OUTCOMES_FILE), recent_limit=recent),
            "timestamp": utc_iso(datetime.now(timezone.utc))}


@app.get("/api/market/ml-dataset/audit")
def ml_dataset_audit():
    """Read-only quality and readiness report; does not write or train."""
    return audit_live_dataset()


@app.post("/api/market/setups/{setup_id}/lifecycle")
def transition_setup(setup_id: str, payload: LifecycleTransitionRequest):
    try:
        return record_lifecycle_transition(setup_id, payload.to_state.upper(),
            payload.reason_code, payload.reason, payload.metadata)
    except ValueError as exc:
        from fastapi import HTTPException
        status = 404 if str(exc) == "Unknown setup_id" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/market/outcomes")
def market_outcomes(setup_id: str | None = None):
    return {"outcomes": list_records(MARKET_OUTCOMES_FILE, setup_id), "configured_horizons": configured_horizons()}


@app.get("/api/market/trade-outcomes")
def trade_outcomes(setup_id: str | None = None):
    return {"outcomes": list_records(TRADE_OUTCOMES_FILE, setup_id)}


@app.post("/api/market/trade-outcomes")
def create_trade_outcome(payload: dict[str, Any]):
    # Explicit execution/simulation payload only; radar snapshots never create these.
    try:
        if not setup_history(str(payload.get("setup_id", ""))):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Setup not found")
        return record_trade_outcome(payload)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/market/setups/{setup_id}/market-outcomes/derive")
def derive_setup_market_outcome(setup_id: str, observation_id: str, horizon: str):
    if horizon not in configured_horizons():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Unsupported horizon")
    snapshot = next((row for row in setup_history(setup_id) if row.get("record_type") == "setup_snapshot" and row.get("observation_id") == observation_id), None)
    if not snapshot:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Setup snapshot not found")
    if (snapshot.get("time_provenance") or {}).get("timezone_normalization_status") != "VERIFIED":
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Snapshot source time is unverified; outcome derivation is quarantined")
    existing = [row for row in list_records(MARKET_OUTCOMES_FILE, setup_id)
                if row.get("observation_id") == observation_id and row.get("horizon") == horizon]
    if existing:
        return existing[-1]
    if not ensure_mt5()[0]:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="MT5 unavailable")
    try:
        actual = mt5_symbol(str(snapshot.get("broker_symbol") or snapshot["symbol"]))
        if not actual:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Broker symbol unavailable")
        timeframe = str(snapshot.get("timeframe") or "M15")
        tf = getattr(mt5, "TIMEFRAME_" + timeframe, mt5.TIMEFRAME_M15)
        observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
        horizon_minutes = {"15m": 15, "1h": 60, "4h": 240, "24h": 1440}[horizon]
        rates = mt5.copy_rates_range(actual, tf, observed, observed + timedelta(minutes=horizon_minutes))
        source_basis = os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE")
        bars = []
        for rate in (rates or []):
            normalized = normalize_mt5_epoch(rate["time"], source_basis)
            if normalized["normalization_status"] != "VERIFIED":
                bars = []
                break
            bars.append({"time": datetime.fromisoformat(normalized["normalized_utc"]).timestamp(),
                "high": float(rate["high"]), "low": float(rate["low"]), "close": float(rate["close"])})
    finally:
        pass  # MT5 connection is reused across requests; see ensure_mt5().
    outcome = derive_market_outcome(snapshot, horizon, bars, timeframe)
    if outcome is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="No post-observation candles available yet")
    append_market_outcome(outcome)
    return outcome
