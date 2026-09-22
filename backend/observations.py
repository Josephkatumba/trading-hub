from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_FILE = DATA_DIR / "setup_observations.jsonl"
_last_fingerprint: dict[str, str] = {}


def _fingerprint(market: dict[str, Any]) -> str:
    fields = {
        "symbol": market.get("symbol"),
        "state": market.get("state"),
        "setup": market.get("setup"),
        "direction": market.get("direction"),
        "score": market.get("score"),
        "trendline_state": market.get("trendline_state"),
        "strategy_valid": market.get("strategy_valid"),
        "entry": market.get("entry"),
        "stop_loss": market.get("stop_loss"),
        "take_profit": market.get("take_profit"),
        "rr": market.get("rr"),
    }
    return hashlib.sha1(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def record_markets(markets: list[dict[str, Any]]) -> int:
    """Persist only meaningful setup-state changes.

    This is intentionally append-only. It gives the future ML layer a clean
    observation stream without writing an identical snapshot every 10 seconds.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    now = datetime.now(timezone.utc).isoformat()

    for market in markets:
        state = str(market.get("state", "")).upper()
        if state not in {"WATCHING", "DEVELOPING", "CONFIRMING"}:
            continue

        symbol = str(market.get("symbol", "UNKNOWN"))
        fp = _fingerprint(market)
        if _last_fingerprint.get(symbol) == fp:
            continue

        _last_fingerprint[symbol] = fp
        rows.append({
            "observation_id": fp,
            "observed_at": now,
            **market,
            "outcome": None,
            "outcome_recorded_at": None,
        })

    if rows:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")

    return len(rows)


def recent_observations(limit: int = 100) -> list[dict[str, Any]]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 1000)):]
    result = []
    for line in reversed(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result
