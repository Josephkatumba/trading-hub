"""The indexed observation store returns the same logical results as the former full scans.

Every comparison runs the frozen pre-index implementation (tests/legacy_observations.py)
and the current observations.py against byte-identical copies of the same data, with
time and UUIDs pinned, on:
  * a synthetic store built to hit edge cases (legacy rows, mixed episode keys,
    duplicates, missing fields, blank/corrupt/non-object lines, VERIFIED rows), and
  * a copy of the real backend/data store when it exists (skipped otherwise).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import golden_support as g  # noqa: E402
import legacy_observations as legacy  # noqa: E402
import observations as current  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from performance import performance_report  # noqa: E402

REAL_DATA = BACKEND / "data"
FILES = ("setup_observations.jsonl", "setup_lifecycle.jsonl", "setup_confirmations.jsonl")
FROZEN_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)


def point(module, root: Path) -> None:
    module.DATA_DIR = root
    module.LOG_FILE = root / "setup_observations.jsonl"
    module.LIFECYCLE_FILE = root / "setup_lifecycle.jsonl"
    module.CONFIRMATIONS_FILE = root / "setup_confirmations.jsonl"


def legacy_id(symbol: str, direction: str | None) -> str:
    key = symbol + "|" + str(direction or "NONE")
    return "stp_legacy_" + hashlib.sha256(key.encode()).hexdigest()[:24]


def iso(minutes: int) -> str:
    return (FROZEN_NOW - timedelta(minutes=minutes)).isoformat()


def snapshot(sid, oid, minutes, symbol="XAUUSD", direction="LONG", valid=False, verified=False,
             state="DEVELOPING", **extra):
    row = {"record_type": "setup_snapshot", "schema_version": "1.0", "setup_id": sid,
           "observation_id": oid, "observed_at": iso(minutes), "source_timestamp": iso(minutes), "symbol": symbol,
           "broker_symbol": symbol + ".r", "direction": direction, "timeframe": "M15",
           "lifecycle_state": state, "price": 2650.0, "reference_price": 2650.0, "atr": 5.0,
           "rule_evidence": {"strategy_valid": valid, "invalidation_hint": 2640.0},
           "proposed_take_profit": 2680.0 if direction == "LONG" else 2620.0,
           "invalidation_price": 2640.0 if direction == "LONG" else 2660.0,
           "time_provenance": {"timezone_normalization_status": "VERIFIED" if verified else "UNVERIFIED"},
           "episode_identity": {"trendline_identity": {"orientation": "ASCENDING_SUPPORT", "fingerprint": sid}}}
    row.update(extra)
    return row


def synthetic_store(root: Path) -> None:
    lines: list[str] = []
    add = lambda row: lines.append(json.dumps(row))  # noqa: E731
    # Pre-episode legacy rows (no record_type), incl. one without symbol.
    add({"symbol": "EURUSD", "direction": "SHORT", "state": "DEVELOPING", "price": 1.17,
         "timestamp": iso(900), "strategy_valid": True})
    add({"symbol": "EURUSD", "direction": "SHORT", "state": "CONFIRMING", "price": 1.171,
         "timestamp": iso(890), "strategy_valid": True})
    add({"price": 1.0, "timestamp": iso(880)})
    lines.append("")                                   # blank line
    lines.append("{not json")                          # corrupt line
    lines.append("[1, 2, 3]")                          # valid JSON, not an object
    for i in range(6):
        add(snapshot("stp_a", f"obs_a{i}", 600 - i * 15, state="DEVELOPING" if i < 3 else "CONFIRMED",
                     valid=i >= 3, verified=True))
    add(snapshot("stp_b", "obs_b0", 500, symbol="GBPUSD", direction="SHORT", verified=True))
    add(snapshot("stp_b", "obs_b1", 20, symbol="GBPUSD", direction="SHORT", verified=True))
    add(snapshot("stp_c", "obs_c0", 400, symbol="NAS100", state="DETECTED"))
    del_obs = snapshot("stp_d", "obs_d0", 300, symbol="US500")
    del del_obs["observed_at"]                          # missing observed_at
    del_obs["timestamp"] = iso(300)
    add(del_obs)
    add(snapshot("", "obs_blank_sid", 290, symbol="US500"))        # falsy setup_id
    # A snapshot continuing a legacy episode id (mixed episode key kinds).
    add(snapshot(legacy_id("EURUSD", "SHORT"), "obs_leg_cont", 100, symbol="EURUSD", direction="SHORT"))
    add(snapshot("stp_a", "obs_a_dup", 5, verified=True))            # latest stp_a row
    add(snapshot("stp_e", "obs_a0", 4, symbol="XAGUSD"))             # duplicate observation id
    (root / "setup_observations.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    events = [
        {"record_type": "setup_lifecycle_event", "setup_id": "stp_a", "from_state": None, "to_state": "DETECTED", "occurred_at": iso(600)},
        {"record_type": "setup_lifecycle_event", "setup_id": "stp_a", "from_state": "DETECTED", "to_state": "CONFIRMED", "occurred_at": iso(555)},
        {"record_type": "setup_lifecycle_event", "setup_id": "stp_c", "from_state": "DETECTED", "to_state": "INVALIDATED", "occurred_at": iso(350)},
        {"record_type": "setup_lifecycle_event", "setup_id": "stp_d", "from_state": "DETECTED", "to_state": "EXPIRED", "occurred_at": iso(200)},
    ]
    (root / "setup_lifecycle.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    confirmations = [{"record_type": "setup_confirmation", "setup_id": "stp_a", "observation_id": "obs_a3",
                      "confirmed_at": iso(555), "symbol": "XAUUSD", "direction": "LONG", "setup_type": "REVERSAL",
                      "timeframe": "M15"},
                     {"record_type": "setup_confirmation", "setup_id": legacy_id("EURUSD", "SHORT"),
                      "observation_id": "legacy", "confirmed_at": iso(890), "symbol": "EURUSD"}]
    (root / "setup_confirmations.jsonl").write_text("".join(json.dumps(c) + "\n" for c in confirmations), encoding="utf-8")


class Harness:
    """Two byte-identical copies of a store: one for the legacy module, one for the current one."""

    def __init__(self, source: Path):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = Path(self.tmp.name) / "old"
        self.new_root = Path(self.tmp.name) / "new"
        for root in (self.old_root, self.new_root):
            root.mkdir()
            for name in FILES:
                if (source / name).exists():
                    shutil.copyfile(source / name, root / name)
        self.saved = [(module, {name: getattr(module, name) for name in
                                ("DATA_DIR", "LOG_FILE", "LIFECYCLE_FILE", "CONFIRMATIONS_FILE")})
                      for module in (legacy, current)]
        point(legacy, self.old_root)
        point(current, self.new_root)
        self.patches = [mock.patch.object(legacy, "datetime", FrozenDatetime),
                        mock.patch.object(current, "datetime", FrozenDatetime)]
        for patch in self.patches:
            patch.start()

    def close(self):
        for patch in self.patches:
            patch.stop()
        for module, values in self.saved:
            for name, value in values.items():
                setattr(module, name, value)
        self.tmp.cleanup()

    def all_ids(self) -> list[str]:
        ids = []
        for row in legacy.all_observations():
            for key in ("setup_id", "observation_id"):
                if row.get(key) is not None:
                    ids.append(str(row[key]))
            if not row.get("record_type"):
                ids.append(legacy_id(str(row.get("symbol", "UNKNOWN")), row.get("direction")))
        return list(dict.fromkeys(ids)) + ["does-not-exist", ""]


class EquivalenceMixin:
    source: Path
    id_sample: int | None = None

    def setUp(self):
        self.h = Harness(self.source)

    def tearDown(self):
        self.h.close()

    def ids(self):
        ids = self.h.all_ids()
        if self.id_sample and len(ids) > self.id_sample:
            step = len(ids) // self.id_sample
            ids = ids[::step][: self.id_sample] + ids[-3:]
        return ids

    def test_setup_history_matches(self):
        for sid in self.ids():
            self.assertEqual(current.setup_history(sid), legacy.setup_history(sid), sid)

    def test_lifecycle_events_match(self):
        for sid in self.ids():
            self.assertEqual(current.lifecycle_events(sid), legacy.lifecycle_events(sid), sid)

    def test_setup_episodes_match_every_bucket_and_limit(self):
        for bucket in ("current", "confirmed", "closed", "all"):
            for limit in (1, 7, 100, 500):
                new, old = current.setup_episodes(bucket, limit), legacy.setup_episodes(bucket, limit)
                # Phase 3 adds strategy_id to each episode: the record's own value, or
                # "trendline" (read-time mapping) for records written before it existed.
                self.assertEqual([row["strategy_id"] for row in new], [row.get("strategy_id") or "trendline" for row in old])
                strip = lambda rows: [{k: v for k, v in row.items() if k != "strategy_id"} for row in rows]  # noqa: E731
                self.assertEqual(strip(new), strip(old), (bucket, limit))

    def test_performance_report_matches(self):
        confirmations = legacy.confirmation_events()
        for report_date in (FROZEN_NOW.date().isoformat(), (FROZEN_NOW - timedelta(days=1)).date().isoformat()):
            for days in (1, 7):
                old = performance_report(confirmations, [], legacy.all_observations(), report_date=report_date, days=days)
                new = performance_report(confirmations, [], current.performance_observations(),
                                         report_date=report_date, days=days)
                self.assertEqual(new, old, (report_date, days))

    def test_broker_symbol_mapping_matches(self):
        old: dict[str, str] = {}
        for row in reversed(legacy.all_observations()):
            if row.get("symbol") and row.get("broker_symbol"):
                old.setdefault(str(row["symbol"]), str(row["broker_symbol"]))
        self.assertEqual(current.latest_broker_symbols(), old)

    def test_record_markets_writes_identical_records(self):
        rows = [row for row in legacy.all_observations() if row.get("record_type") == "setup_snapshot"]
        seeds = {}
        for row in rows:
            seeds[(row.get("symbol"), row.get("direction"))] = row
        markets = []
        for (symbol, direction), row in list(seeds.items())[:6]:
            markets.append({"symbol": symbol, "direction": direction, "state": "CONFIRMING", "timeframe": "M15",
                            "price": row.get("price") or 1.0, "atr": row.get("atr") or 1.0, "score": 70,
                            "setup_family": "REVERSAL", "trendline_state": "REVERSAL", "strategy_valid": False,
                            "invalidation_hint": row.get("invalidation_price"),
                            "trendline_identity": (row.get("episode_identity") or {}).get("trendline_identity")})
        markets.append({"symbol": "BRANDNEW", "direction": "LONG", "state": "WATCHING", "timeframe": "M15",
                        "price": 10.0, "atr": 0.1, "score": 40})
        # Records already in the store are compared byte for byte; only the records
        # appended here have the Phase 3 strategy fields removed before comparing.
        initial = {name: (self.h.new_root / name).stat().st_size if (self.h.new_root / name).exists() else 0 for name in FILES}
        for round_number in range(3):
            results = {}
            for module in (legacy, current):
                counter = iter(range(10**6))
                with mock.patch("uuid.uuid4", side_effect=lambda: uuid.UUID(int=next(counter))):
                    batch = json.loads(json.dumps(markets))
                    count = module.record_markets(batch)
                results[module.__name__] = (count, batch)
            # Identical except for the Phase 3 strategy fields (golden_support), all trendline.
            new_count, new_batch = results["observations"]
            self.assertTrue(g.only_trendline_fields(g.strategy_fields(new_batch)))
            self.assertEqual((new_count, g.without_strategy_fields(new_batch)), results["legacy_observations"], round_number)
            for name in FILES:
                old_bytes = (self.h.old_root / name).read_bytes() if (self.h.old_root / name).exists() else b""
                new_bytes = (self.h.new_root / name).read_bytes() if (self.h.new_root / name).exists() else b""
                cut = initial[name]
                self.assertEqual(new_bytes[:cut], old_bytes[:cut], (round_number, name))
                self.assertEqual(g.without_strategy_bytes(new_bytes[cut:]), old_bytes[cut:], (round_number, name))
                found = g.jsonl_strategy_fields(new_bytes[cut:])
                self.assertTrue(not found or g.only_trendline_fields(found), (round_number, name))

    def test_outcome_resolution_inputs_give_identical_outcomes(self):
        confirmations = legacy.confirmation_events()
        observations = legacy.all_observations()
        symbols = {str(row.get("symbol")) for row in observations if row.get("symbol")}
        base = FROZEN_NOW.timestamp() - 3 * 86400
        bars = {symbol: [{"time": base + i * 900, "open": 2650.0, "high": 2650.0 + (i % 40), "low": 2650.0 - (i % 30),
                          "close": 2650.0} for i in range(3 * 96)] for symbol in symbols}
        horizons = ("15m", "1h", "4h", "24h")
        for existing in ([], [{"setup_id": "stp_a", "observation_id": "obs_a0", "horizon": h,
                               "label_definition": "target-invalidation-first-v1"} for h in horizons]):
            old_by_id = {str(row.get("observation_id")): row for row in observations
                         if row.get("record_type") == "setup_snapshot"}
            old_watch = [row for row in observations if row.get("record_type") == "setup_snapshot"
                         and (row.get("rule_evidence") or {}).get("strategy_valid") is not True]
            new_by_id = current.snapshots_by_observation_id(str(row.get("observation_id")) for row in confirmations)
            claimed = {str(s.get("observation_id") or "") for s in
                       (new_by_id.get(str(row.get("observation_id"))) for row in confirmations) if s}
            present = {(r.get("setup_id"), r.get("observation_id"), r.get("horizon"), r.get("label_definition"))
                       for r in existing}
            new_watch = current.outcome_watch_snapshots(claimed, set(bars), present, horizons)
            strip = lambda rows: [{k: v for k, v in r.items() if k != "outcome_id"} for r in rows]  # noqa: E731
            old = resolve_due_market_outcomes(confirmations, old_by_id, bars, existing, horizons, now=FROZEN_NOW,
                                              watch_snapshots=old_watch)
            new = resolve_due_market_outcomes(confirmations, new_by_id, bars, existing, horizons, now=FROZEN_NOW,
                                              watch_snapshots=new_watch)
            self.assertEqual(strip(new), strip(old))
            if self.source is not REAL_DATA:
                self.assertGreater(len(old), 0, "synthetic comparison must not be vacuous")


class SyntheticStoreEquivalence(EquivalenceMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls._tmp.name)
        synthetic_store(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_synthetic_store_actually_produces_outcomes(self):
        # Guard: the outcome comparison above must not be vacuous.
        observations = legacy.all_observations()
        bars = {"XAUUSD": [{"time": FROZEN_NOW.timestamp() - 86400 + i * 900, "open": 2650.0,
                            "high": 2700.0, "low": 2649.0, "close": 2690.0} for i in range(96)]}
        watch = [r for r in observations if r.get("record_type") == "setup_snapshot"
                 and (r.get("rule_evidence") or {}).get("strategy_valid") is not True]
        by_id = {str(r.get("observation_id")): r for r in observations if r.get("record_type") == "setup_snapshot"}
        created = resolve_due_market_outcomes(legacy.confirmation_events(), by_id, bars, [], ("1h", "4h"),
                                              now=FROZEN_NOW, watch_snapshots=watch)
        self.assertGreater(len(created), 0)


@unittest.skipUnless((REAL_DATA / "setup_observations.jsonl").exists(), "no local observation store")
class RealStoreEquivalence(EquivalenceMixin, unittest.TestCase):
    source = REAL_DATA
    id_sample = 40


if __name__ == "__main__":
    unittest.main()
