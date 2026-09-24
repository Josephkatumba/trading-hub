from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from market_time import utc_iso

TE_BASE = "https://api.tradingeconomics.com"


def _get_json(url: str):
    req = Request(url, headers={"User-Agent": "TradingHub/0.1"})
    with urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def fundamentals_snapshot():
    """Optional macro layer. Uses Trading Economics when an API key is configured."""
    key = os.getenv("TRADING_ECONOMICS_API_KEY", "").strip()
    if not key:
        return {
            "configured": False,
            "provider": "Trading Economics",
            "status": "API key not configured",
            "events": [],
            "timestamp": utc_iso(datetime.now(timezone.utc)),
        }

    try:
        url = f"{TE_BASE}/calendar/country/united%20states?c={quote(key)}&d1=now&d2=now"
        data = _get_json(url)
        events = []
        for item in data if isinstance(data, list) else []:
            events.append({
                "country": item.get("Country"),
                "event": item.get("Event"),
                "importance": item.get("Importance"),
                "date": item.get("Date"),
                "actual": item.get("Actual"),
                "forecast": item.get("Forecast"),
                "previous": item.get("Previous"),
                "unit": item.get("Unit"),
            })
        return {
            "configured": True,
            "provider": "Trading Economics",
            "status": "LIVE",
            "events": events[:30],
            "timestamp": utc_iso(datetime.now(timezone.utc)),
        }
    except Exception as exc:
        return {
            "configured": True,
            "provider": "Trading Economics",
            "status": "ERROR",
            "error": str(exc),
            "events": [],
            "timestamp": utc_iso(datetime.now(timezone.utc)),
        }
