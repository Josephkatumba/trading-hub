"""Bounded MT5 candle reads, verified UTC conversion and existing historical overlays."""
from datetime import datetime, timezone
import os
import math
from fastapi import APIRouter, Query, HTTPException
from market_time import normalize_mt5_epoch
from outcome_identity import unique_outcomes

router = APIRouter()
TIMEFRAMES = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def normalize_candles(rates, basis):
    candles = {}
    for r in rates:
        stamp = normalize_mt5_epoch(r["time"], basis)
        if stamp.get("normalization_status") != "VERIFIED":
            continue
        epoch = int(datetime.fromisoformat(stamp["normalized_utc"]).timestamp())
        prices = {k: float(r[k]) for k in ("open", "high", "low", "close")}
        if not all(math.isfinite(v) for v in prices.values()) or not (
                prices["low"] <= min(prices["open"], prices["close"]) <=
                max(prices["open"], prices["close"]) <= prices["high"]):
            continue
        candles[epoch] = {"time": epoch, **prices}
    return [candles[t] for t in sorted(candles)]


@router.get("/api/market/chart")
def intelligence_chart(symbol: str = Query("XAUUSD", max_length=32),
                       timeframe: str = Query("M15", pattern="^(M5|M15|H1|H4|D1)$"),
                       limit: int = Query(300, ge=20, le=500)):
    import main
    from observations import setup_episodes
    from outcomes import outcomes_for_setups, MARKET_OUTCOMES_FILE
    if symbol not in main.WATCHLIST:
        raise HTTPException(422, "Unknown instrument")
    with main._SCAN_LOCK:
        connected, _ = main.ensure_mt5()
        if not connected:
            raise HTTPException(503, "Market feed unavailable")
        actual = main.resolve_mt5_symbol(symbol)
        code = getattr(main.mt5, "TIMEFRAME_" + timeframe, None)
        if not actual or code is None:
            raise HTTPException(503, "Instrument/timeframe unavailable")
        rates = main.mt5.copy_rates_from_pos(actual, code, 0, limit)
        if rates is None or not len(rates):
            raise HTTPException(503, "Candle history unavailable")
        candles = normalize_candles(rates, os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE"))
        info = main.mt5.symbol_info(actual)
    if not candles:
        raise HTTPException(503, "Candle time basis unverified")
    episodes = [r for r in setup_episodes("all", 200, per_strategy=True) if r.get("symbol") == symbol]
    ids = [r["setup_id"] for r in episodes]
    outcomes = unique_outcomes(outcomes_for_setups(ids, MARKET_OUTCOMES_FILE))[-1000:]
    from observations import snapshots_by_observation_id
    snapshots = snapshots_by_observation_id(r.get("observation_id") for r in outcomes)
    overlays = []
    for row in outcomes:
        snapshot = snapshots.get(str(row.get("observation_id")))
        units = {"15m": 900, "1h": 3600, "4h": 14400, "24h": 86400}.get(row.get("horizon"))
        if not snapshot or not units:
            continue
        observed = datetime.fromisoformat(snapshot["observed_at"])
        if observed.tzinfo is None:
            continue
        frame = TIMEFRAMES.get(row.get("timeframe"), 900)
        end = math.ceil((observed.timestamp() + units) / frame) * frame
        overlays.append({**row, "symbol": symbol, "observed_at": snapshot["observed_at"],
                         "horizon_end": datetime.fromtimestamp(end, timezone.utc).isoformat()})
    return {"symbol": symbol, "timeframe": timeframe, "candles": candles,
            "digits": getattr(info, "digits", None), "tick_size": getattr(info, "trade_tick_size", None),
            "episodes": episodes, "outcomes": overlays, "source": "MT5", "time_basis": "verified UTC",
            "timestamp": datetime.now(timezone.utc).isoformat()}
