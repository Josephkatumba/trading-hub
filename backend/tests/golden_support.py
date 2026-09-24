"""Shared helpers for the trendline baseline (golden) tests.

Phase 0 of the multi-strategy work: these tests freeze what the existing
trendline engine does today, so every later phase can prove it did not change
it. Golden files are regenerated ONLY by tests/tools/regen_golden.py, and a
regenerated golden must be reviewed like a behaviour change.
"""
from __future__ import annotations

import json
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
BACKEND = TESTS.parent
sys.path.insert(0, str(BACKEND))

FIXTURES = TESTS / "fixtures"
SCANNER_FIXTURES = FIXTURES / "scanner"
SCANNER_GOLDEN = FIXTURES / "golden" / "scanner_golden.json"
PERSISTENCE_GOLDEN = FIXTURES / "golden" / "persistence"
OFFICIAL_SCAN = ["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "NAS100", "US500", "GER40"]
PERSISTED_FILES = ("setup_observations.jsonl", "setup_lifecycle.jsonl", "setup_confirmations.jsonl")
BASE_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def load_fixtures() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(SCANNER_FIXTURES.glob("*.json"))]


def canonical(value) -> str:
    """Stable text form used for exact comparison (float repr round-trips exactly)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=True)


def scan(fixture: dict) -> dict:
    from scanner import analyze_symbol
    return analyze_symbol(fixture["symbol"], fixture["rows"], spread=fixture.get("spread", 0.0),
                          session_context=fixture.get("session_context"), higher_rows=fixture.get("higher_rows"))


def market_from_scan(fixture: dict, result: dict, symbol: str | None = None) -> dict:
    """The market dict main.market_snapshot hands to record_markets (minus live-only fields)."""
    last = fixture["rows"][-1]
    price = float(last["close"])
    return {"symbol": symbol or fixture["symbol"], "broker_symbol": fixture.get("broker_symbol") or fixture["symbol"],
            "price": price, "bid": price, "ask": price, "spread": fixture.get("spread", 0.0), "change_pct": 0.0,
            **result, **(fixture.get("session_context") or {}),
            "source_timestamp": None, "backend_received_at": BASE_NOW.isoformat(),
            "tick_age_seconds": None, "candle_age_seconds": None,
            "time_provenance": {"source_time_basis": "UNVERIFIED", "timezone_normalization_status": "UNVERIFIED"},
            "source": "MT5", "timestamp": BASE_NOW.isoformat()}


def persistence_rounds() -> list[list[dict]]:
    """Three scan rounds through record_markets, built only from fixtures:
    round 1 opens episodes, round 2 continues them, round 3 swaps each symbol to
    a different fixture so direction/family changes and invalidations occur."""
    fixtures = [f for f in load_fixtures() if f["name"] != "synthetic_insufficient_data"]
    scans = [(f, scan(f)) for f in fixtures]
    symbols = [f"SYM{index:02d}" for index in range(len(scans))]
    first = [market_from_scan(f, r, symbols[i]) for i, (f, r) in enumerate(scans)]
    rotated = scans[1:] + scans[:1]
    third = [market_from_scan(f, r, symbols[i]) for i, (f, r) in enumerate(rotated)]
    return [first, [dict(m) for m in first], third]


class FrozenClock:
    """Replaces observations.datetime so now() is controllable per round."""
    current = BASE_NOW

    @classmethod
    def make(cls):
        clock = cls

        class Frozen(datetime):
            @classmethod
            def now(cls_, tz=None):
                return clock.current if tz else clock.current.replace(tzinfo=None)
        return Frozen


@contextmanager
def isolated_store(module, root: Path):
    """Point an observations-like module at a temp store; restore afterwards."""
    names = ("DATA_DIR", "LOG_FILE", "LIFECYCLE_FILE", "CONFIRMATIONS_FILE")
    saved = {name: getattr(module, name) for name in names}
    module.DATA_DIR = root
    module.LOG_FILE = root / "setup_observations.jsonl"
    module.LIFECYCLE_FILE = root / "setup_lifecycle.jsonl"
    module.CONFIRMATIONS_FILE = root / "setup_confirmations.jsonl"
    FrozenClock.current = BASE_NOW
    counter = iter(range(10**9))
    patches = [mock.patch.object(module, "datetime", FrozenClock.make()),
               mock.patch("uuid.uuid4", side_effect=lambda: uuid.UUID(int=next(counter)))]
    for patch in patches:
        patch.start()
    try:
        yield
    finally:
        for patch in patches:
            patch.stop()
        for name, value in saved.items():
            setattr(module, name, value)


def run_persistence(module, root: Path) -> dict[str, bytes]:
    with isolated_store(module, root):
        for index, markets in enumerate(persistence_rounds()):
            FrozenClock.current = BASE_NOW + timedelta(minutes=15 * index)
            module.record_markets(json.loads(json.dumps(markets)))
    return {name: (root / name).read_bytes() if (root / name).exists() else b"" for name in PERSISTED_FILES}
