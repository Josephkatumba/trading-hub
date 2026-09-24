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


# Phase 3 (strategy-aware persistence) ADDS exactly these fields to what
# record_markets writes, and nothing else: strategy_id + strategy_evidence on
# snapshots, strategy_id on confirmations, strategy_id inside episode_identity
# (also echoed on the market dict). Comparisons with the frozen pre-strategy
# implementation remove exactly these and require everything else unchanged.
STRATEGY_RECORD_FIELDS = {"setup_snapshot": ("strategy_id", "strategy_evidence"),
                          "setup_confirmation": ("strategy_id",)}


def without_strategy_fields(value):
    """`value` (record, market, episode or a list of them) minus the Phase 3 fields."""
    if isinstance(value, list):
        return [without_strategy_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    added = STRATEGY_RECORD_FIELDS.get(value.get("record_type"), ())
    result = {key: item for key, item in value.items() if key not in added}
    identity = result.get("episode_identity")
    if isinstance(identity, dict) and "strategy_id" in identity:
        result["episode_identity"] = {key: item for key, item in identity.items() if key != "strategy_id"}
    return result


def strategy_fields(value) -> list:
    """The Phase 3 field values carried by `value` (see without_strategy_fields)."""
    if isinstance(value, list):
        return [found for item in value for found in strategy_fields(item)]
    if not isinstance(value, dict):
        return []
    found = [(key, value[key]) for key in STRATEGY_RECORD_FIELDS.get(value.get("record_type"), ()) if key in value]
    identity = value.get("episode_identity")
    if isinstance(identity, dict) and "strategy_id" in identity:
        found.append(("episode_identity.strategy_id", identity["strategy_id"]))
    return found


def without_strategy_bytes(data: bytes) -> bytes:
    """JSONL bytes with the Phase 3 fields removed from the records that carry them.

    Records are re-serialized exactly as observations._append writes them, keeping
    each line's own terminator (text-mode appends write CRLF on Windows), so the
    result is byte-comparable with the pre-strategy implementation's output.
    """
    out = []
    for line in data.splitlines(keepends=True):
        try:
            record = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        if strategy_fields(record):
            ending = line[len(line.rstrip(b"\r\n")):]
            out.append(json.dumps(without_strategy_fields(record), separators=(",", ":"), default=str).encode() + ending)
        else:
            out.append(line)
    return b"".join(out)


def jsonl_strategy_fields(data: bytes) -> list:
    found = []
    for line in data.splitlines():
        try:
            found.extend(strategy_fields(json.loads(line)))
        except ValueError:
            continue  # blank / corrupt lines carry no fields (readers skip them too)
    return found


# What a trendline-only run writes into those fields.
TRENDLINE_STRATEGY_FIELDS = [("strategy_id", "trendline"), ("strategy_evidence", {}),
                             ("episode_identity.strategy_id", "trendline")]


def only_trendline_fields(found: list) -> bool:
    return bool(found) and all(item in TRENDLINE_STRATEGY_FIELDS for item in found)


def trendline_only_registry():
    """The registry as it was before shadow strategies: trendline only, LIVE.
    Used where a test asserts trendline behaviour in isolation."""
    from strategies import LIVE, StrategyRegistry, TrendlineStrategy
    registry = StrategyRegistry()
    registry.register(TrendlineStrategy(), enabled=True, mode=LIVE)
    return registry


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
