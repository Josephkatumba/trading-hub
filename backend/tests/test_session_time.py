"""Phase 9: LEGACY vs CORRECTED session time.

The legacy path must stay identical to the pre-v4 production main.session_context,
frozen verbatim in tests/legacy_session_context.py (trendline-first-v3). The
corrected path converts bar times through the verified broker basis and is the
production path since trendline-first-v4. A/B regression tests pin what the
correction can and cannot change in the scanner.
"""
from __future__ import annotations

import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import legacy_session_context as frozen_v3  # noqa: E402
import main  # noqa: E402
import session_ab  # noqa: E402
import session_time as st  # noqa: E402
from strategies import LegacyTrendlineStrategy, TrendlineStrategy  # noqa: E402
from test_time_basis import BASIS, server_epoch, server_epoch_of  # noqa: E402

LONDON, NEW_YORK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
CORRECTED = st.corrected_bar_time(BASIS)


def frozen(now):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz else now.replace(tzinfo=None)
    return Frozen


def day_bars(day: tuple[int, int, int], london_high: float, early_high: float) -> list[dict]:
    """Broker M15 bars (server epochs) for one real day: flat 100, a spike to `early_high`
    at 06:00 London (outside the session) and to `london_high` at 12:00 London (inside)."""
    rows = []
    start = datetime(*day, 0, 0, tzinfo=LONDON)
    for i in range(96):
        instant = start + timedelta(minutes=15 * i)
        local = instant.astimezone(LONDON)
        high = london_high if (local.hour, local.minute) == (12, 0) else early_high if (local.hour, local.minute) == (6, 0) else 100.5
        rows.append({"time": server_epoch_of(instant), "open": 100.0, "high": high, "low": 99.5, "close": 100.0})
    return rows


class LegacyEquivalenceTests(unittest.TestCase):
    def samples(self):
        rng = random.Random(9)
        for fixture in g.load_fixtures():
            rows = fixture["rows"]
            if len(rows) < 2:
                continue
            base = datetime.fromtimestamp(rows[-1]["time"], timezone.utc)
            for _ in range(25):
                yield fixture, rows, base + timedelta(minutes=rng.randint(-72 * 60, 72 * 60))

    def test_legacy_port_is_identical_to_the_pre_v4_production_session_context(self):
        for fixture, rows, now in self.samples():
            with self.subTest(fixture=fixture["name"], now=now), mock.patch.object(frozen_v3, "datetime", frozen(now)):
                expected = frozen_v3.session_context(rows, rows[-1]["close"])
                self.assertEqual(st.session_context_legacy(rows, rows[-1]["close"], now), expected)
                self.assertEqual(LegacyTrendlineStrategy().session_context(rows, rows[-1]["close"], now, BASIS), expected,
                                 "v3 ignores the basis: raw epochs as UTC")

    def test_legacy_bar_time_is_the_pre_v4_bar_dt(self):
        self.assertIs(frozen_v3._bar_dt({"time": 1790286300}).tzinfo, timezone.utc)
        self.assertEqual(frozen_v3._bar_dt({"time": 1790286300}), st.legacy_bar_time({"time": 1790286300}))
        self.assertFalse(hasattr(main, "_bar_dt"), "production no longer reads raw epochs as UTC")

    def test_production_uses_the_corrected_path_of_the_live_trendline_version(self):
        self.assertEqual(main.STRATEGIES.get("trendline").version, "trendline-first-v4")
        for fixture, rows, now in self.samples():
            with self.subTest(fixture=fixture["name"], now=now), mock.patch.object(main, "datetime", frozen(now)),                  mock.patch.dict("os.environ", {"TRADING_HUB_MT5_SOURCE_TIMEZONE": BASIS}):
                production = main.session_context(rows, rows[-1]["close"])
                self.assertEqual(production, st.session_context_corrected(rows, rows[-1]["close"], now, BASIS))
                self.assertEqual(production, TrendlineStrategy().session_context(rows, rows[-1]["close"], now, BASIS))


class CorrectedSessionTests(unittest.TestCase):
    def test_corrected_london_window_uses_real_london_time_in_every_dst_regime(self):
        for label, day in (("summer", (2026, 7, 14)), ("winter", (2026, 1, 13)), ("US DST, EU not", (2026, 3, 17)),
                           ("EU DST, US not (Oct 27-31 2025)", (2025, 10, 29))):
            with self.subTest(label):
                rows = day_bars(day, london_high=105.0, early_high=110.0)
                after_close = datetime(*day, 17, 0, tzinfo=LONDON).astimezone(timezone.utc)
                corrected = st.session_context_corrected(rows, 100.0, after_close, BASIS)
                self.assertEqual((corrected["london_high"], corrected["london_low"], corrected["london_date"], corrected["london_complete"]),
                                 (105.0, 99.5, "-".join(f"{p:02d}" for p in day), True))
                legacy = st.session_context_legacy(rows, 100.0, after_close)
                self.assertEqual(legacy["london_high"], 110.0, "legacy's early window includes the 06:00 London spike")

    def test_session_labels_are_unchanged_and_alignment_only_in_new_york_after_london(self):
        rows = day_bars((2026, 7, 14), london_high=105.0, early_high=100.5)
        for hour, session in ((7, "Asia"), (9, "London"), (14, "London / New York Overlap"), (17, "New York"), (23, "Off-hours")):
            now = datetime(2026, 7, 14, hour, 0, tzinfo=LONDON).astimezone(timezone.utc)
            with self.subTest(hour=hour):
                self.assertEqual(st.session_context_corrected(rows, 105.0, now, BASIS)["session"], session)
                self.assertEqual(st.session_context_legacy(rows, 105.0, now)["session"], session)
        new_york = datetime(2026, 7, 14, 17, 0, tzinfo=LONDON).astimezone(timezone.utc)
        self.assertIn("retesting the London high", st.session_context_corrected(rows, 104.9, new_york, BASIS)["session_alignment"])
        self.assertIsNone(st.session_context_corrected(rows, 102.0, new_york, BASIS)["session_alignment"])

    def test_dst_gap_repeated_hour_broker_midnight_and_weekend_bars(self):
        spring = [{"time": server_epoch(2026, 3, 8, h, m), "open": 1, "high": 1, "low": 1, "close": 1} for h, m in ((8, 45), (9, 15), (10, 0))]
        self.assertEqual([CORRECTED(row) is None for row in spring], [False, True, False], "the skipped hour is not guessed")
        autumn = {"time": server_epoch(2026, 11, 1, 8, 30), "open": 1, "high": 1, "low": 1, "close": 1}
        self.assertIsNone(CORRECTED(autumn), "the repeated hour is ambiguous")
        # Broker midnight is 17:00 New York the previous day.
        midnight = CORRECTED({"time": server_epoch(2026, 7, 15, 0, 0)})
        self.assertEqual(midnight.astimezone(NEW_YORK).strftime("%Y-%m-%d %H:%M"), "2026-07-14 17:00")
        # 24/7 weekend data: a Saturday London session exists for crypto and is used as recorded.
        saturday = day_bars((2026, 7, 18), london_high=105.0, early_high=110.0)
        sunday_ny = datetime(2026, 7, 19, 17, 0, tzinfo=LONDON).astimezone(timezone.utc)
        self.assertEqual(st.session_context_corrected(saturday, 104.9, sunday_ny, BASIS)["london_date"], "2026-07-18")
        # A window crossing the DST gap works; invalid bars are simply skipped.
        mixed = day_bars((2026, 3, 7), 105.0, 110.0) + spring
        self.assertEqual(st.session_context_corrected(mixed, 100.0, datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc), BASIS)["london_high"], 105.0)

    def test_missing_session_data_and_unusable_basis_fail_closed(self):
        rows = day_bars((2026, 7, 14), 105.0, 110.0)
        far_future = datetime(2026, 8, 30, 20, 0, tzinfo=timezone.utc)
        for ctx in (st.session_context_corrected(rows, 100.0, far_future, BASIS), st.session_context_legacy(rows, 100.0, far_future)):
            self.assertEqual((ctx["london_high"], ctx["london_low"], ctx["london_date"], ctx["session_alignment"]), (0.0, 0.0, None, None))
        unusable = st.session_context_corrected(rows, 100.0, datetime(2026, 7, 14, 21, 0, tzinfo=timezone.utc), "Mars/Olympus")
        self.assertEqual((unusable["london_date"], unusable["session_alignment"]), (None, None))
        self.assertEqual(set(unusable), set(st.session_context_legacy(rows, 100.0, far_future)))


class ABRegressionTests(unittest.TestCase):
    def pair(self, fixture_name, now, legacy_ctx=None, corrected_ctx=None):
        fixture = next(f for f in g.load_fixtures() if f["name"] == fixture_name)
        rows, higher = fixture["rows"], fixture["higher_rows"]
        patches = []
        if legacy_ctx is not None:
            patches.append(mock.patch.object(session_ab, "compute_session_context",
                                             side_effect=lambda r, p, n, t: legacy_ctx if t is st.legacy_bar_time else corrected_ctx))
        for patch in patches:
            patch.start()
        try:
            return session_ab.run_pair(fixture["symbol"], rows, higher, now, st.legacy_bar_time, CORRECTED)
        finally:
            for patch in patches:
                patch.stop()

    def test_equal_scanner_inputs_give_identical_scans(self):
        pair = self.pair("real_XAUUSD", datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc))   # Asia: no alignment either way
        self.assertEqual(pair["scan_changed"], [])
        self.assertEqual(pair["legacy"]["scan"], pair["corrected"]["scan"])

    def test_alignment_difference_changes_only_the_session_score_by_two(self):
        base = {"session": "New York", "london_high": 1.0, "london_low": 0.5, "london_complete": True, "london_date": "2026-09-24",
                "new_york_time": "2026-09-24T12:00:00-04:00"}
        legacy_ctx = {**base, "session_alignment": "New York is retesting the London high, watch for bearish confirmation"}
        corrected_ctx = {**base, "session_alignment": None}
        for fixture in ("real_XAUUSD", "real_EURUSD", "real_GER40", "synthetic_07_confirming_break_long_valid", "synthetic_02_developing_reversal_any_any"):
            with self.subTest(fixture=fixture):
                pair = self.pair(fixture, datetime(2026, 9, 24, 16, 0, tzinfo=timezone.utc), legacy_ctx, corrected_ctx)
                self.assertEqual(pair["scan_changed"], ["score", "session_score"] if pair["legacy"]["scan"]["score"] < 100 else ["session_score"])
                self.assertEqual((pair["legacy"]["scan"]["session_score"], pair["corrected"]["scan"]["session_score"]), (5, 3))
                for field in ("state", "direction", "setup_family", "entry", "stop_loss", "take_profit", "invalidation_hint", "strategy_valid"):
                    self.assertEqual(pair["legacy"]["scan"][field], pair["corrected"]["scan"][field], field)
                self.assertTrue(pair["reason_changed"])

    def test_counterfactual_outcome_uses_the_unchanged_engine(self):
        observed = datetime(2026, 9, 23, 12, 7, 30, tzinfo=timezone.utc)
        plan = {"direction": "LONG", "entry": 100.0, "stop_loss": 98.0, "take_profit": 106.0, "invalidation_hint": 98.0}
        bars = [{"time": (observed + timedelta(minutes=8 + 15 * i)).timestamp(), "open": 100 + 0.5 * i, "high": 100.2 + 0.5 * i,
                 "low": 99.8 + 0.5 * i, "close": 100 + 0.5 * i} for i in range(120)]
        self.assertEqual(session_ab.counterfactual_outcome("XAUUSD", plan, observed, bars, observed + timedelta(days=2))[0], "verified_target")
        falling = [{**bar, "high": bar["high"] - 2 * (bar["open"] - 100), "low": bar["low"] - 2 * (bar["open"] - 100)} for bar in bars]
        self.assertEqual(session_ab.counterfactual_outcome("XAUUSD", plan, observed, falling, observed + timedelta(days=2))[0], "verified_stop")


if __name__ == "__main__":
    unittest.main()
