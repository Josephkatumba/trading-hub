"""Phase 9 adoption: trendline-first-v4 (corrected session time) end to end.

The same fixtures are scanned through main.market_snapshot under the historical
configuration (trendline-first-v3: LegacyTrendlineStrategy, raw epochs as UTC)
and the registered one (trendline-first-v4: bar times through the verified MT5
basis) at scan instants across Asia, London, the overlap and New York.

A  the v3 configuration reproduces the pre-v4 production session context exactly;
B  v4 selects the London session in real London time (session_time.corrected);
C  DST: skipped / repeated hours are not guessed, all regimes keep 08:00-16:30 London;
D  v4 is the LIVE trendline, labels its records, and production uses its session path;
E  historical records (v3 goldens, the real store) are never rewritten or relabelled;
F  Support & Resistance decisions are identical; only the shared market session
   context recorded on its snapshots is the corrected one;
G/H only the Phase 9 fields differ: London range / alignment, the session score
   (+/-2, New York only) with the total score and reason text, and the version label.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import legacy_session_context as frozen_v3  # noqa: E402
import main  # noqa: E402
import observations  # noqa: E402
import session_time as st  # noqa: E402
from strategies import REGISTRY, LegacyTrendlineStrategy, TrendlineStrategy  # noqa: E402
from test_market_data import IC_MARKETS, FakeBroker, fixture_for, with_volume  # noqa: E402
from test_session_time import day_bars, frozen  # noqa: E402
from test_time_basis import BASIS, server_epoch  # noqa: E402

LONDON = ZoneInfo("Europe/London")
REAL_DATA = g.BACKEND / "data"
SCAN_HOURS = (3, 9, 12, 16, 17.5, 19, 20.5)            # UTC on 2026-09-24: Asia .. late New York
SESSION_FIELDS = ("london_high", "london_low", "london_complete", "london_date", "session_alignment")
# Everything v4 may change in a market dict; all other fields must be identical.
ALLOWED_MARKET_DIFFS = {*SESSION_FIELDS, "score", "score_breakdown", "reason", "strategy_version", "strategies"}
ALLOWED_SNAPSHOT_DIFFS = {"session." + f for f in SESSION_FIELDS} | {"score", "score_breakdown.session", "rule_evidence.reason",
                                                                      "strategy_version"}
ALLOWED_LIFECYCLE_DIFFS = {"reason"}                     # the lifecycle event echoes the scanner's reason text


def flat(record: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in record.items():
        if isinstance(value, dict) and value:
            out.update(flat(value, prefix + key + "."))
        else:
            out[prefix + key] = value
    return out


def changed(a: dict, b: dict) -> set:
    return {key for key in set(a) | set(b) if a.get(key) != b.get(key)}


def scan(now: datetime, legacy: bool, root: Path | None = None, basis: str | None = BASIS):
    """One market_snapshot pass over the official universe at `now`; (markets, persisted files)."""
    tmp = tempfile.TemporaryDirectory() if root is None else None
    store = Path(tmp.name) if tmp else root
    env = {"TRADING_HUB_MT5_SOURCE_TIMEZONE": basis} if basis else {}
    main._MT5_SESSION.update(initialized=False, initializations=0)
    try:
        with g.isolated_store(observations, store), (g.legacy_trendline(main, observations) if legacy else g._nothing()), \
             mock.patch.dict(os.environ, env), mock.patch.object(main, "mt5", FakeBroker(IC_MARKETS)), \
             mock.patch.object(main, "datetime", g.FrozenClock.make()), \
             mock.patch.object(main, "WATCHLIST", list(main.OFFICIAL_UNIVERSE)), \
             mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            if not basis:
                os.environ.pop("TRADING_HUB_MT5_SOURCE_TIMEZONE", None)
            g.FrozenClock.current = now
            markets = main.market_snapshot()
        files = {name: (store / name).read_bytes() for name in g.PERSISTED_FILES if (store / name).exists()}
    finally:
        main._MT5_SESSION.update(initialized=False, initializations=0)
        if tmp:
            tmp.cleanup()
    return markets, files


def m15_rows(symbol: str) -> list[dict]:
    return with_volume(fixture_for(symbol)["rows"], 1)[-300:]


def real_store_prefixes() -> dict:
    """(size, sha256 of those bytes) of each real JSONL file: appends by a running engine are fine."""
    out = {}
    for path in sorted(REAL_DATA.glob("*.jsonl")) if REAL_DATA.exists() else ():
        data = path.read_bytes()
        out[path.name] = (len(data), hashlib.sha256(data).hexdigest())
    return out


_REAL_BEFORE: dict = {}


def setUpModule():
    _REAL_BEFORE.update(real_store_prefixes())


class TrendlineV4EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = []
        for hours in SCAN_HOURS:
            now = datetime(2026, 9, 24, tzinfo=timezone.utc) + timedelta(hours=hours)
            cls.runs.append((now, scan(now, legacy=True), scan(now, legacy=False)))

    # D ----------------------------------------------------------------------------------------
    def test_v4_is_the_live_trendline_and_v3_stays_available_unregistered(self):
        self.assertEqual((TrendlineStrategy.version, LegacyTrendlineStrategy.version), ("trendline-first-v4", "trendline-first-v3"))
        self.assertEqual(TrendlineStrategy.strategy_id, LegacyTrendlineStrategy.strategy_id)
        self.assertEqual(REGISTRY.get("trendline").version, "trendline-first-v4")
        self.assertEqual(REGISTRY.live(), ["trendline"])
        self.assertEqual(REGISTRY.registered(), ["trendline", "support_resistance"])
        # Everything but the version label and the session reader is the same strategy.
        for name in ("timeframe", "higher_timeframes", "lifecycle", "data_requirements", "evaluate"):
            self.assertEqual(getattr(TrendlineStrategy, name), getattr(LegacyTrendlineStrategy, name), name)
        # (index stats stubbed: health must not build index sidecars in the real data directory)
        with mock.patch.object(main, "mt5", None), mock.patch.object(main, "observation_index_stats", return_value={}):
            self.assertEqual(main.health()["strategy"], "trendline-first-v4")

    def test_v4_records_and_markets_carry_v4_and_the_v3_configuration_carries_v3(self):
        for now, (old, old_files), (new, new_files) in self.runs:
            self.assertEqual({m["strategy_version"] for m in old}, {"trendline-first-v3"})
            self.assertEqual({m["strategy_version"] for m in new}, {"trendline-first-v4"})
            for files, version in ((old_files, "trendline-first-v3"), (new_files, "trendline-first-v4")):
                snapshots = [json.loads(line) for line in files["setup_observations.jsonl"].splitlines()]
                self.assertEqual({s["strategy_version"] for s in snapshots if s["strategy_id"] == "trendline"}, {version})
                self.assertEqual({s["strategy_version"] for s in snapshots if s["strategy_id"] == "support_resistance"}, {"sr-levels-v1"})

    # A / B ------------------------------------------------------------------------------------
    def test_v3_reproduces_and_v4_corrects_the_session_context_end_to_end(self):
        for now, (old, _), (new, _) in self.runs:
            for legacy_market, market in zip(old, new):
                rows = m15_rows(market["symbol"])
                with self.subTest(now=now, symbol=market["symbol"]), mock.patch.object(frozen_v3, "datetime", frozen(now)):
                    v3 = frozen_v3.session_context(rows, legacy_market["price"])
                    v4 = st.session_context_corrected(rows, market["price"], now, BASIS)
                    self.assertEqual({k: legacy_market[k] for k in v3}, v3)
                    self.assertEqual({k: market[k] for k in v4}, v4)

    def test_v4_london_range_is_the_real_london_session(self):
        for now, _, (new, _) in self.runs:
            for market in new:
                if not market["london_date"]:
                    continue
                window = [row for row in m15_rows(market["symbol"])
                          if (t := st.corrected_bar_time(BASIS)(row)) is not None
                          and t.astimezone(LONDON).date().isoformat() == market["london_date"]
                          and (8, 0) <= (t.astimezone(LONDON).hour, t.astimezone(LONDON).minute) < (16, 30)]
                with self.subTest(now=now, symbol=market["symbol"]):
                    self.assertTrue(window)
                    self.assertEqual((market["london_high"], market["london_low"]),
                                     (max(r["high"] for r in window), min(r["low"] for r in window)))

    # G / H ------------------------------------------------------------------------------------
    def test_only_the_phase9_fields_differ_in_markets(self):
        seen = set()
        for now, (old, _), (new, _) in self.runs:
            for a, b in zip(old, new):
                diff = changed(a, b)
                seen |= diff
                with self.subTest(now=now, symbol=a["symbol"]):
                    self.assertLessEqual(diff, ALLOWED_MARKET_DIFFS)
                    self.assertEqual(changed(a["score_breakdown"], b["score_breakdown"]) - {"session"}, set())
                    if "score" in diff or "session_alignment" in diff:
                        self.assertEqual(a["session"], "New York")
                        self.assertIn(abs(b["score_breakdown"]["session"] - a["score_breakdown"]["session"]), (2,))
                    else:
                        self.assertNotIn("reason", diff)
                    # The strategy summaries: S/R identical, trendline only version / score / session evidence.
                    for x, y in zip(a["strategies"], b["strategies"]):
                        if x["strategy_id"] != "trendline":
                            self.assertEqual(x, y)
                        else:
                            self.assertLessEqual(changed(x, y), {"strategy_version", "score", "evidence"})
                            self.assertLessEqual(changed(x["evidence"], y["evidence"]), {"session"})
        # The comparison is not vacuous: the London range and the session score both moved somewhere.
        self.assertLessEqual({"london_high", "session_alignment", "score", "reason", "strategy_version"}, seen)

    def test_decisions_levels_and_lifecycle_are_identical(self):
        decisions = ("state", "direction", "setup_family", "trendline_state", "entry", "stop_loss", "take_profit",
                     "invalidation_hint", "strategy_valid", "trendline_gate", "confirmation_alignment", "rr",
                     "setup_id", "lifecycle_state", "session", "new_york_time")
        for now, (old, old_files), (new, new_files) in self.runs:
            for a, b in zip(old, new):
                with self.subTest(now=now, symbol=a["symbol"]):
                    self.assertEqual({k: a.get(k) for k in decisions}, {k: b.get(k) for k in decisions})
            self.assertEqual(sorted(old_files), sorted(new_files))   # same files, so the same confirmations exist

    def test_only_the_phase9_fields_differ_in_persisted_records(self):
        allowed = {"setup_observations.jsonl": ALLOWED_SNAPSHOT_DIFFS, "setup_lifecycle.jsonl": ALLOWED_LIFECYCLE_DIFFS,
                   "setup_confirmations.jsonl": {"strategy_version"}}
        for now, (_, old_files), (_, new_files) in self.runs:
            for name, data in old_files.items():
                old_rows, new_rows = data.splitlines(), new_files[name].splitlines()
                with self.subTest(now=now, file=name):
                    self.assertEqual(len(old_rows), len(new_rows))
                    for x, y in zip(old_rows, new_rows):
                        x, y = flat(json.loads(x)), flat(json.loads(y))
                        diff = changed(x, y)
                        self.assertLessEqual(diff, allowed[name])
                        if x.get("strategy_id") == "support_resistance":
                            self.assertLessEqual(diff, {"session." + f for f in SESSION_FIELDS})

    # F ----------------------------------------------------------------------------------------
    def test_support_resistance_decisions_are_unchanged(self):
        # S/R does not read the session context; its shadow snapshots record the scan's shared
        # market session context, which is the corrected one under v4 (and nothing else changes).
        for now, (_, old_files), (_, new_files) in self.runs:
            old = [flat(json.loads(line)) for line in old_files["setup_observations.jsonl"].splitlines()]
            new = [flat(json.loads(line)) for line in new_files["setup_observations.jsonl"].splitlines()]
            sr_old = [r for r in old if r.get("strategy_id") == "support_resistance"]
            sr_new = [r for r in new if r.get("strategy_id") == "support_resistance"]
            self.assertEqual(len(sr_old), len(sr_new))
            self.assertTrue(sr_old)
            for x, y in zip(sr_old, sr_new):
                strip = lambda r: {k: v for k, v in r.items() if not k.startswith("session.")}  # noqa: E731
                self.assertEqual(strip(x), strip(y))

    def test_missing_basis_fails_closed_without_changing_decisions(self):
        now = datetime(2026, 9, 24, 20, 30, tzinfo=timezone.utc)
        (legacy, _), (unset, _) = scan(now, legacy=True), scan(now, legacy=False, basis=None)
        for a, b in zip(legacy, unset):
            self.assertEqual((b["london_high"], b["london_low"], b["london_date"], b["session_alignment"]), (0.0, 0.0, None, None))
            self.assertEqual({k: a[k] for k in ("state", "direction", "entry", "stop_loss", "take_profit", "strategy_valid")},
                             {k: b[k] for k in ("state", "direction", "entry", "stop_loss", "take_profit", "strategy_valid")})


class DSTTests(unittest.TestCase):
    """C: the production session path (TrendlineStrategy / main.session_context) in every DST regime."""

    def session(self, rows, now):
        with mock.patch.object(main, "datetime", frozen(now)), mock.patch.dict(os.environ, {"TRADING_HUB_MT5_SOURCE_TIMEZONE": BASIS}):
            production = main.session_context(rows, rows[-1]["close"])
        self.assertEqual(production, TrendlineStrategy().session_context(rows, rows[-1]["close"], now, BASIS))
        return production

    def test_london_window_in_every_regime(self):
        for label, day in (("summer", (2026, 7, 14)), ("winter", (2026, 1, 13)), ("US DST, EU not", (2026, 3, 17)),
                           ("EU DST, US not", (2025, 10, 29)), ("day after EU spring-forward", (2026, 3, 30)),
                           ("day after US fall-back", (2026, 11, 2))):
            with self.subTest(label):
                rows = day_bars(day, london_high=105.0, early_high=110.0)
                ctx = self.session(rows, datetime(*day, 17, 0, tzinfo=LONDON).astimezone(timezone.utc))
                self.assertEqual((ctx["london_high"], ctx["london_low"], ctx["london_date"], ctx["london_complete"]),
                                 (105.0, 99.5, "-".join(f"{p:02d}" for p in day), True))

    def test_skipped_and_repeated_hours_are_not_guessed_and_crypto_weekends_are_kept(self):
        spring = [{"time": server_epoch(2026, 3, 8, h, m), "open": 1, "high": 1, "low": 1, "close": 1} for h, m in ((8, 45), (9, 15), (10, 0))]
        corrected = st.corrected_bar_time(BASIS)
        self.assertEqual([corrected(r) is None for r in spring], [False, True, False])
        self.assertIsNone(corrected({"time": server_epoch(2026, 11, 1, 8, 30)}))
        mixed = day_bars((2026, 3, 7), 105.0, 110.0) + spring
        self.assertEqual(self.session(mixed, datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc))["london_high"], 105.0)
        # Sunday boundary: broker midnight is 17:00 New York; a Saturday crypto London session is used as recorded.
        saturday = day_bars((2026, 7, 18), london_high=105.0, early_high=110.0)
        self.assertEqual(self.session(saturday, datetime(2026, 7, 19, 17, 0, tzinfo=LONDON).astimezone(timezone.utc))["london_date"],
                         "2026-07-18")


class HistoricalRecordTests(unittest.TestCase):
    """E: v4 appends; it never rewrites or relabels what v3 wrote."""

    def test_v4_scans_append_to_a_v3_store_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in g.PERSISTED_FILES:
                shutil.copyfile(g.PERSISTENCE_GOLDEN / name, root / name)
            before = {name: (root / name).read_bytes() for name in g.PERSISTED_FILES}
            scan(datetime(2026, 9, 24, 20, 30, tzinfo=timezone.utc), legacy=False, root=root)
            with g.isolated_store(observations, root):
                episodes = observations.setup_episodes("all", 500)
            for name, old in before.items():
                data = (root / name).read_bytes()
                with self.subTest(file=name):
                    self.assertEqual(data[:len(old)], old, "existing bytes unchanged")
                    old_versions = {json.loads(l).get("strategy_version") for l in old.splitlines()} - {None}
                    self.assertLessEqual(old_versions, {"trendline-first-v3"})
                    appended = [json.loads(l) for l in data[len(old):].splitlines()]
                    self.assertLessEqual({r.get("strategy_version") for r in appended if r.get("strategy_id") == "trendline"},
                                         {"trendline-first-v4"})
            self.assertTrue(len((root / "setup_observations.jsonl").read_bytes()) > len(before["setup_observations.jsonl"]))
            # Reading back resolves each record to the version it was written with.
            old_ids = {json.loads(l)["setup_id"] for l in before["setup_observations.jsonl"].splitlines()}
            with g.isolated_store(observations, root):
                for setup_id in list(old_ids)[:10]:
                    history = observations.setup_history(setup_id)
                    stored = [json.loads(l) for l in before["setup_observations.jsonl"].splitlines() if json.loads(l)["setup_id"] == setup_id]
                    self.assertEqual([h["strategy_version"] for h in history][:len(stored)], [s["strategy_version"] for s in stored])
            self.assertTrue(episodes)

    def test_the_v3_goldens_are_unchanged_in_git(self):
        import subprocess
        paths = [str(g.SCANNER_GOLDEN)] + [str(g.PERSISTENCE_GOLDEN / name) for name in g.PERSISTED_FILES]
        result = subprocess.run(["git", "status", "--porcelain", "--", *paths], cwd=g.BACKEND, capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("git unavailable")
        self.assertEqual(result.stdout.strip(), "")

    def test_real_store_prefix_is_untouched_by_this_suite(self):
        if not _REAL_BEFORE:
            self.skipTest("no real store")
        for name, (size, digest) in _REAL_BEFORE.items():
            with self.subTest(file=name):
                data = (REAL_DATA / name).read_bytes()
                self.assertGreaterEqual(len(data), size)
                self.assertEqual(hashlib.sha256(data[:size]).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
