"""Closed-episode summaries + lifecycle index give the same scans as the former full reads.

_record_markets now loads full rows only for OPEN episodes; closed episodes are
answered from compact summaries kept by the observation index, and lifecycle
state comes from a lifecycle index (see observations._EpisodeTable). Each test
drives randomized scan rounds (recurring trendlines, near-price repeats, no-
trendline markets, direction flips, stale expiry, manual lifecycle transitions,
legacy rows) through the frozen pre-index module (tests/legacy_observations.py)
and the current module with pinned time/UUIDs, and requires identical market
outputs after every round and byte-identical JSONL files at the end, apart from
the Phase 3 strategy fields (golden_support.without_strategy_fields), which must
carry only trendline values here.
"""
from __future__ import annotations

import json
import math
import random
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import jsonl_index  # noqa: E402
import legacy_observations as legacy  # noqa: E402
import observations as current  # noqa: E402

SYMBOLS = ("XAUUSD", "EURUSD", "NAS100", "LEGACY")
ANCHOR_PAIRS = (("08:00", "09:00"), ("08:00", "10:00"), ("09:00", "11:00"))


def legacy_rows() -> list[dict]:
    """Pre-episode rows (no record_type) for LEGACY, incl. one without trendline."""
    return [{"symbol": "LEGACY", "direction": "LONG", "state": "DEVELOPING", "price": 2630.0, "atr": 5.0,
             "timestamp": "2026-09-23T10:00:00Z", "setup_family": "BREAK"},
            {"symbol": "LEGACY", "direction": "SHORT", "state": "CONFIRMING", "price": 2660.0, "atr": 5.0,
             "timestamp": "2026-09-23T10:15:00Z", "trendline_state": "REVERSAL", "strategy_valid": True,
             "trendline_identity": {"orientation": "ASCENDING_SUPPORT", "fingerprint": "legacyfp"}}]


def random_market(rng: random.Random, symbol: str) -> dict:
    direction = rng.choice(("LONG", "SHORT"))
    state = rng.choice(("WATCHING", "DEVELOPING", "CONFIRMING", "CONFIRMING", "NO SETUP"))
    valid = state == "CONFIRMING" and rng.random() < 0.5
    price = 2600.0 + rng.choice((0, 3, 6, 9, 30, 60)) + rng.choice((0.0, 0.5, 1.25))
    family = rng.choice(("BREAK", "REVERSAL"))
    invalidation = price - 10 if direction == "LONG" else price + 10
    row = {"symbol": symbol, "timeframe": "M15", "direction": direction, "state": state, "price": price,
           "atr": rng.choice((2.0, 5.0, None)), "score": 70, "score_breakdown": {"trendline": 20},
           "strategy_valid": valid, "trendline_gate": True, "confirmation_alignment": valid,
           "rr": 2.0 if valid else None, "setup_family": family, "trendline_state": family,
           "setup": "Trendline " + family.lower(), "invalidation_hint": invalidation if rng.random() < 0.8 else None,
           "entry": price, "stop_loss": invalidation, "take_profit": price + 30 if direction == "LONG" else price - 30}
    if rng.random() < 0.7:
        first, second = rng.choice(ANCHOR_PAIRS)
        row["trendline_identity"] = {"orientation": "ASCENDING_SUPPORT" if direction == "SHORT" else "DESCENDING_RESISTANCE",
                                     "anchors": [{"time": "2026-09-24T" + first + ":00Z", "price": 2590.0},
                                                 {"time": "2026-09-24T" + second + ":00Z", "price": 2595.0}]}
    return row


def run(module, root: Path, seed: int, rounds: int, seed_rows=(), between=None) -> tuple[list[str], dict[str, bytes]]:
    """Scan rounds through `module`; returns per-round market outputs and the final files."""
    root.mkdir(parents=True, exist_ok=True)
    if seed_rows:
        (root / "setup_observations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in seed_rows), encoding="utf-8")
    rng = random.Random(seed)
    outputs: list[str] = []
    with g.isolated_store(module, root):
        now = g.BASE_NOW
        for index in range(rounds):
            now += timedelta(hours=26) if rng.random() < 0.06 else timedelta(minutes=15)
            g.FrozenClock.current = now
            batch = [random_market(rng, symbol) for symbol in SYMBOLS if rng.random() < 0.85]
            module.record_markets(batch)
            outputs.append(g.canonical(comparable(module, batch)))
            if rng.random() < 0.2:
                # Manual transitions, incl. non-terminal ones that move the lifecycle
                # ahead of the latest snapshot's lifecycle_state.
                target = next((m["setup_id"] for m in batch if m.get("setup_id") and not m.get("episode_suppressed")), None)
                to_state = rng.choice(("RESOLVED", "CONFIRMED", "ACTIVE", "ACTIVE"))
                try:
                    event = module.record_lifecycle_transition(target, to_state, "MANUAL") if target else None
                    outputs.append("transition:" + g.canonical(event))
                except ValueError as exc:
                    outputs.append("rejected:" + str(exc))
            if between:
                between(index, root)
    files = {name: (root / name).read_bytes() if (root / name).exists() else b"" for name in g.PERSISTED_FILES}
    if module is current:
        found = [item for data in files.values() for item in g.jsonl_strategy_fields(data)]
        assert g.only_trendline_fields(found), "unexpected strategy field values"
        files = {name: g.without_strategy_bytes(data) for name, data in files.items()}
    return outputs, files


def comparable(module, markets: list[dict]) -> list[dict]:
    """Market outputs minus the Phase 3 strategy fields (only trendline values allowed)."""
    if module is not current:
        return markets
    found = g.strategy_fields(markets)
    assert not found or g.only_trendline_fields(found), found
    return g.without_strategy_fields(markets)


def forget_process_state(root: Path) -> None:
    """Simulate a backend restart: drop the in-memory indexes and episode tables for `root`."""
    for key in [key for key in jsonl_index._REGISTRY if Path(key[0]).parent == root.resolve()]:
        del jsonl_index._REGISTRY[key]
    current._EPISODE_TABLES.clear()


def fresh_table() -> current._EpisodeTable:
    table = current._EpisodeTable(current._observation_index(), current._lifecycle_index())
    table.refresh()
    return table


def table_state(table: current._EpisodeTable) -> dict:
    buckets = {key: (bucket.count, bucket.by_fingerprint, bucket.unlined)
               for key, bucket in table.buckets.items() if bucket.count}
    return {"keys": table.keys, "open": sorted(table.open), "closed": table.closed, "last_to": table.last_to,
            "latest": {key: position for key, (position, _) in table.latest.items()}, "buckets": buckets,
            "irregular": table.irregular, "broken": table.broken}


class ClosedEpisodeIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assertSameRun(self, seed, rounds, seed_rows=(), between=None, forbid_fallback=True):
        expected = run(legacy, self.root / f"legacy{seed}", seed, rounds, seed_rows)
        patch = mock.patch.object(current, "_FullEpisodeView", side_effect=AssertionError("full-row fallback used"))
        if forbid_fallback:
            patch.start()
        try:
            actual = run(current, self.root / f"current{seed}", seed, rounds, seed_rows, between)
        finally:
            if forbid_fallback:
                patch.stop()
        for index, (old, new) in enumerate(zip(expected[0], actual[0])):
            self.assertEqual(new, old, f"seed {seed}: output {index} differs")
        self.assertEqual(len(actual[0]), len(expected[0]))
        self.assertEqual(actual[1], expected[1], f"seed {seed}: persisted records differ")
        return actual

    def test_randomized_scans_match_the_former_full_reads(self):
        suppressed = closed = 0
        for seed in range(6):
            outputs, files = self.assertSameRun(seed, 70, legacy_rows())
            suppressed += sum(bool(m.get("episode_suppressed")) for o in outputs if o.startswith("[") for m in json.loads(o))
            closed += files["setup_lifecycle.jsonl"].count(b'"to_state":"INVALIDATED"') + files["setup_lifecycle.jsonl"].count(b'"to_state":"EXPIRED"')
        # The generator must actually exercise suppression and episode closing.
        self.assertGreater(suppressed, 20)
        self.assertGreater(closed, 50)

    def test_incremental_table_equals_a_fresh_rebuild_and_summaries_match_full_rows(self):
        def check(index, root):
            if index % 10 != 9:
                return
            table = current._EPISODE_TABLES[(current._observation_index(), current._lifecycle_index())]
            table.refresh()  # take in this round's appends, as the next scan would
            self.assertEqual(table_state(table), table_state(fresh_table()), f"round {index}")
            # Every closed-episode summary equals what the former code read from the full row.
            rows = current._observation_index().load(table.latest[key][0] for key in table.keys)
            for key, row in zip(table.keys, rows):
                episode = current._episode_from_row(key, row, table.latest[key][1]["rt"])
                old_tl = (episode.get("episode_identity") or {}).get("trendline_identity")
                old_price = episode.get("reference_price", episode.get("price"))
                fields = table.latest[key][1]["ep"]
                self.assertEqual(("fp" in fields, fields.get("fp")), (bool(old_tl), old_tl.get("fingerprint") if old_tl else None))
                self.assertEqual(fields["px"], None if old_price is None else float(old_price))
        self.assertSameRun(11, 80, legacy_rows(), between=check)

    def test_restart_with_deleted_or_outdated_sidecars_rebuilds_the_summaries(self):
        def restart(index, root):
            if index == 24:      # sidecars deleted while the backend is down
                shutil.rmtree(root / ".index", ignore_errors=True)
                forget_process_state(root)
            elif index == 49:    # sidecar from the previous summary schema (v2: no strategy in "ep")
                sidecar = root / ".index" / "setup_observations.jsonl.idx.json"
                body = json.loads(json.loads(sidecar.read_text(encoding="utf-8"))["body"])
                body["schema"] = "observations-v2"
                for row in body["rows"]:
                    if isinstance(row.get("ep"), dict):
                        row["ep"].pop("st", None)
                text = json.dumps(body, separators=(",", ":"))
                sidecar.write_text(json.dumps({"checksum": jsonl_index._sha(text.encode()), "body": text}), encoding="utf-8")
                forget_process_state(root)
        with self.assertLogs("trading_hub.jsonl_index", "WARNING") as logs:
            self.assertSameRun(21, 75, legacy_rows(), between=restart)
        self.assertTrue(any("version/schema mismatch" in line for line in logs.output))
        index_dir = self.root / "current21" / ".index"
        for name, schema in (("setup_observations.jsonl", current._OBSERVATION_INDEX_SCHEMA), ("setup_lifecycle.jsonl", "lifecycle-v1")):
            body = json.loads(json.loads((index_dir / (name + ".idx.json")).read_text(encoding="utf-8"))["body"])
            self.assertEqual(body["schema"], schema)

    def test_replaced_lifecycle_file_resets_the_derived_state(self):
        def replace(index, root):
            if index == 30:
                path = root / "setup_lifecycle.jsonl"
                lines = path.read_bytes().splitlines(keepends=True)
                path.write_bytes(b"".join(lines[: len(lines) // 2]))
        # Truncating history changes what counts as open, for both implementations alike.
        legacy_run = run(legacy, self.root / "legacy", 31, 60, legacy_rows(), between=replace)
        with self.assertLogs("trading_hub.jsonl_index", "WARNING"):
            current_run = run(current, self.root / "current", 31, 60, legacy_rows(), between=replace)
        self.assertEqual(current_run, legacy_run)

    def test_first_matching_closed_episode_wins_in_first_appearance_order(self):
        # A and B share a trendline, C and D are near-price repeats without one;
        # A and C reappear later, so latest-row order differs from first appearance.
        line = {"orientation": "DESCENDING_RESISTANCE", "anchors": [{"time": "2026-09-24T08:00:00Z", "price": 2590.0},
                                                                   {"time": "2026-09-24T09:00:00Z", "price": 2595.0}]}
        from episode_identity import trendline_identity

        def closed(sid, minutes, identity, price):
            return {"record_type": "setup_snapshot", "setup_id": sid, "observation_id": f"obs_{sid}_{minutes}",
                    "observed_at": (g.BASE_NOW - timedelta(minutes=minutes)).isoformat(), "symbol": "XAUUSD",
                    "direction": "LONG", "timeframe": "M15", "lifecycle_state": "DETECTED", "reference_price": price,
                    "episode_identity": {"trendline_identity": identity}}
        rows = [closed("A", 90, trendline_identity({"trendline_identity": line}), 2600.0),
                closed("C", 85, None, 2601.0), closed("B", 80, trendline_identity({"trendline_identity": line}), 2600.0),
                closed("D", 75, None, 2600.5), closed("A", 70, trendline_identity({"trendline_identity": line}), 2600.0),
                closed("C", 65, None, 2601.0)]
        events = [{"setup_id": sid, "to_state": "INVALIDATED"} for sid in ("B", "D", "A", "C")]
        for name, module in (("legacy", legacy), ("current", current)):
            root = self.root / name
            root.mkdir()
            (root / "setup_observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            (root / "setup_lifecycle.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
            with g.isolated_store(module, root):
                lined = {**random_market(random.Random(0), "XAUUSD"), "direction": "LONG", "state": "DEVELOPING",
                         "price": 2640.0, "trendline_identity": line}
                unlined = {**lined, "price": 2600.8, "atr": 1.0}
                unlined.pop("trendline_identity")
                module.record_markets([lined])
                module.record_markets([unlined])
            with self.subTest(module=name):
                self.assertEqual((lined["setup_id"], lined.get("episode_suppressed")), ("A", True))
                self.assertEqual((unlined["setup_id"], unlined.get("episode_suppressed")), ("C", True))

    def test_rows_without_an_exact_summary_use_the_full_row_path(self):
        irregular = legacy_rows() + [{"record_type": "setup_snapshot", "setup_id": "stp_nan", "observation_id": "obs_nan",
            "observed_at": "2026-09-24T11:00:00Z", "symbol": "XAUUSD", "direction": "LONG", "timeframe": "M15",
            "lifecycle_state": "DETECTED", "reference_price": math.nan, "episode_identity": {"trendline_identity": None}}]
        with mock.patch.object(current, "_FullEpisodeView", wraps=current._FullEpisodeView) as fallback:
            self.assertSameRun(41, 40, irregular, forbid_fallback=False)
        self.assertGreater(fallback.call_count, 0)


if __name__ == "__main__":
    unittest.main()
