"""Phase 8: broker time basis, canonical UTC and read-only outcome re-verification.

The broker (IC Markets, ICMarketsSC-Demo) stamps MT5 bars/ticks with its server
wall clock = New York wall clock + 7h (UTC+3 in US summer time, UTC+2 in US
winter time; see TIMESTAMP_AUDIT_REPORT.md). Basis: "America/New_York+07:00".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import main  # noqa: E402
import time_reverification as tr  # noqa: E402
from market_time import normalize_mt5_epoch, parse_aware_utc, parse_source_basis, utc_iso  # noqa: E402

BASIS = "America/New_York+07:00"
NEW_YORK, LONDON, BERLIN = ZoneInfo("America/New_York"), ZoneInfo("Europe/London"), ZoneInfo("Europe/Berlin")
BACKEND = Path(__file__).resolve().parents[1]


def server_epoch(y, mo, d, h, mi=0) -> float:
    """MT5 epoch for a server wall-clock time (MT5 encodes server wall time as if UTC)."""
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def to_utc(epoch, basis=BASIS):
    result = normalize_mt5_epoch(epoch, basis)
    return parse_aware_utc(result["normalized_utc"]) if result["normalization_status"] == "VERIFIED" else None


def server_epoch_of(instant: datetime) -> float:
    """Inverse used by fixtures: the MT5 epoch the broker writes for a real instant."""
    wall = instant.astimezone(NEW_YORK).replace(tzinfo=None) + timedelta(hours=7)
    return wall.replace(tzinfo=timezone.utc).timestamp()


class ConversionTests(unittest.TestCase):
    def test_new_york_plus_seven_across_us_and_eu_daylight_saving(self):
        cases = {  # server wall -> real UTC
            (2026, 7, 15, 16, 30): datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc),   # summer: UTC+3
            (2026, 1, 15, 16, 30): datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc),   # winter: UTC+2
            (2026, 3, 16, 11, 0): datetime(2026, 3, 16, 8, 0, tzinfo=timezone.utc),      # US DST on, EU off: UTC+3
            (2025, 10, 29, 11, 0): datetime(2025, 10, 29, 8, 0, tzinfo=timezone.utc),    # US DST on, EU off: UTC+3
            (2025, 11, 5, 11, 0): datetime(2025, 11, 5, 9, 0, tzinfo=timezone.utc),      # both off: UTC+2
        }
        for wall, expected in cases.items():
            with self.subTest(wall=wall):
                self.assertEqual(to_utc(server_epoch(*wall)), expected)
        # The exchange opens that identified the basis land on their local clock times.
        self.assertEqual(to_utc(server_epoch(2026, 1, 15, 16, 30)).astimezone(NEW_YORK).strftime("%H:%M"), "09:30")
        self.assertEqual(to_utc(server_epoch(2026, 7, 15, 16, 30)).astimezone(NEW_YORK).strftime("%H:%M"), "09:30")
        self.assertEqual(to_utc(server_epoch(2026, 3, 16, 11, 0)).astimezone(BERLIN).strftime("%H:%M"), "09:00")
        self.assertEqual(to_utc(server_epoch(2026, 7, 15, 10, 0)).astimezone(BERLIN).strftime("%H:%M"), "09:00")

    def test_dst_gap_and_repeated_hour_fail_closed(self):
        gap = normalize_mt5_epoch(server_epoch(2026, 3, 8, 9, 30), BASIS)        # US spring-forward: server 09:00-10:00 absent
        self.assertEqual((gap["normalization_status"], gap["normalization_reason"]), ("INVALID", "NONEXISTENT_LOCAL_SOURCE_TIME"))
        repeated = normalize_mt5_epoch(server_epoch(2026, 11, 1, 8, 30), BASIS)  # US fall-back: server 08:00-09:00 twice
        self.assertEqual((repeated["normalization_status"], repeated["normalization_reason"]), ("UNVERIFIED", "AMBIGUOUS_LOCAL_SOURCE_TIME"))
        self.assertEqual(to_utc(server_epoch(2026, 3, 8, 10, 0)), datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(to_utc(server_epoch(2026, 11, 1, 9, 0)), datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc))

    def test_other_bases_unset_and_malformed_inputs(self):
        epoch = server_epoch(2026, 9, 24, 21, 45)
        self.assertEqual(normalize_mt5_epoch(epoch, None)["normalization_status"], "UNVERIFIED")
        self.assertEqual(normalize_mt5_epoch(epoch, "")["normalization_reason"], "SOURCE_TIME_BASIS_UNVERIFIED")
        self.assertEqual(to_utc(epoch, "UTC"), datetime(2026, 9, 24, 21, 45, tzinfo=timezone.utc))
        self.assertEqual(to_utc(epoch, "Europe/Athens"), datetime(2026, 9, 24, 18, 45, tzinfo=timezone.utc))
        self.assertEqual(normalize_mt5_epoch("not-an-epoch", BASIS)["normalization_status"], "INVALID")
        self.assertEqual(normalize_mt5_epoch(float("nan"), BASIS)["normalization_status"], "INVALID")
        self.assertEqual(normalize_mt5_epoch(None, BASIS)["normalization_status"], "MISSING")
        self.assertEqual(normalize_mt5_epoch(epoch, "Mars/Olympus+07:00")["normalization_status"], "UNVERIFIED")
        self.assertEqual(parse_source_basis(BASIS), ("America/New_York", timedelta(hours=7)))
        self.assertEqual(parse_source_basis("Etc/GMT-3"), ("Etc/GMT-3", timedelta(0)))
        self.assertEqual(parse_source_basis("America/New_York-01:30"), ("America/New_York", -timedelta(hours=1, minutes=30)))

    def test_canonical_timestamps_are_timezone_aware_utc(self):
        stamp = normalize_mt5_epoch(server_epoch(2026, 9, 24, 21, 45), BASIS)["normalized_utc"]
        self.assertTrue(stamp.endswith("+00:00"))
        self.assertEqual(parse_aware_utc(stamp).utcoffset(), timedelta(0))
        self.assertIsNone(parse_aware_utc("2026-09-24T18:45:00"), "naive timestamps are rejected, never guessed")
        with self.assertRaises(ValueError):
            utc_iso(datetime(2026, 9, 24, 18, 45))

    def test_same_source_timestamp_converts_identically_under_any_host_timezone(self):
        code = ("import sys, json; sys.path.insert(0, '.'); from market_time import normalize_mt5_epoch; "
                "print(json.dumps([normalize_mt5_epoch(e, 'America/New_York+07:00') for e in (1790286300, 1768494600.5, 1772962200)]))")
        outputs = set()
        for tz in ("UTC", "Africa/Kampala", "America/Los_Angeles", "Asia/Tokyo", "EST5EDT"):
            env = {**os.environ, "TZ": tz}
            outputs.add(subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, text=True, capture_output=True, check=True).stdout)
        self.assertEqual(len(outputs), 1)


class BoundaryTests(unittest.TestCase):
    def test_candle_boundaries_map_to_exact_utc_boundaries(self):
        for day in ((2026, 1, 13), (2026, 3, 17), (2026, 7, 14)):
            for hour in range(0, 24, 4):                                          # H4 opens at server 00,04,...,20
                utc = to_utc(server_epoch(*day, hour))
                self.assertEqual((utc.minute, utc.second), (0, 0))
            # D1 opens at server midnight = 17:00 New York, the FX day roll, in every DST regime.
            self.assertEqual(to_utc(server_epoch(*day, 0)).astimezone(NEW_YORK).strftime("%H:%M"), "17:00")
            for minute in (0, 15, 30, 45):                                        # M15 / H1 keep their minute grid
                self.assertEqual(to_utc(server_epoch(*day, 12, minute)).minute, minute)
        # Consecutive server H4 opens stay exactly 4h apart in real time (no DST change mid-week).
        opens = [to_utc(server_epoch(2026, 3, 17, h)) for h in (0, 4, 8, 12, 16, 20)]
        self.assertEqual({(b - a) for a, b in zip(opens, opens[1:])}, {timedelta(hours=4)})

    def test_london_and_new_york_session_boundaries_in_server_time(self):
        def server_time(instant):
            return datetime.fromtimestamp(server_epoch_of(instant), timezone.utc).strftime("%H:%M")
        for label, day, london_open in (("summer", (2026, 7, 14), "10:00"), ("winter", (2026, 1, 13), "10:00"),
                                        ("US DST, EU not", (2026, 3, 17), "11:00")):
            with self.subTest(label):
                london = datetime(*day, 8, 0, tzinfo=LONDON)
                self.assertEqual(server_time(london), london_open)
                self.assertEqual(server_time(datetime(*day, 16, 30, tzinfo=LONDON)),
                                 (datetime(2000, 1, 1, int(london_open[:2])) + timedelta(hours=8, minutes=30)).strftime("%H:%M"))
                self.assertEqual(server_time(datetime(*day, 8, 0, tzinfo=NEW_YORK)), "15:00")       # NY 08:00 always server 15:00
                self.assertEqual(server_time(datetime(*day, 17, 0, tzinfo=NEW_YORK)), "00:00")      # NY 17:00 always server midnight
                self.assertEqual(to_utc(server_epoch_of(london)), london.astimezone(timezone.utc))  # round trip

    def test_session_logic_follows_the_basis_and_fails_closed_without_it(self):
        """Since trendline-first-v4 the London session is selected through the basis (Phase 9);
        without a basis the London range is unavailable instead of guessed."""
        import session_time
        fixture = next(f for f in g.load_fixtures() if f["name"] == "real_XAUUSD")
        rows, price = fixture["rows"], fixture["rows"][-1]["close"]
        now = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz else now.replace(tzinfo=None)
        with mock.patch.object(main, "datetime", Frozen):
            with mock.patch.dict(os.environ, {"TRADING_HUB_MT5_SOURCE_TIMEZONE": BASIS}):
                verified = main.session_context(rows, price)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TRADING_HUB_MT5_SOURCE_TIMEZONE", None)
                unset = main.session_context(rows, price)
        self.assertEqual(verified, session_time.session_context_corrected(rows, price, now, BASIS))
        self.assertEqual(verified["london_date"], "2026-09-24")
        self.assertEqual((unset["london_high"], unset["london_low"], unset["london_date"], unset["session_alignment"]),
                         (0.0, 0.0, None, None))
        self.assertEqual((unset["session"], unset["new_york_time"]), (verified["session"], verified["new_york_time"]))

def snapshot(observed: datetime, *, strategy_id="trendline", raw=True, direction="LONG", verified=False):
    bar_open = observed.replace(minute=(observed.minute // 15) * 15, second=0, microsecond=0)
    provenance = {"backend_received_at": utc_iso(observed - timedelta(milliseconds=100)), "timezone_normalization_status": "UNVERIFIED"}
    if raw:
        provenance["bar_open_time"] = {"raw_mt5_epoch": server_epoch_of(bar_open), "normalization_status": "UNVERIFIED"}
        provenance["tick_time"] = {"raw_mt5_epoch": server_epoch_of(observed) - 0.5, "normalization_status": "UNVERIFIED"}
    row = {"record_type": "setup_snapshot", "setup_id": "s-" + strategy_id + direction, "observation_id": "o-" + strategy_id + direction,
           "observed_at": utc_iso(observed), "source_timestamp": None, "symbol": "XAUUSD", "direction": direction, "timeframe": "M15",
           "strategy_id": strategy_id, "reference_price": 100.0, "proposed_entry": 100.0,
           "proposed_stop_loss": 98.0 if direction == "LONG" else 102.0, "invalidation_price": 98.0 if direction == "LONG" else 102.0,
           "proposed_take_profit": 106.0 if direction == "LONG" else 94.0, "rule_evidence": {"strategy_valid": True},
           "time_provenance": provenance, "data_quality": {"source": "MT5", "timestamp_quality": "UNVERIFIED", "received_bars": 300}}
    if strategy_id != "trendline":
        row["shadow"] = True
    return row


def confirmation(snap: dict) -> dict:
    return {"record_type": "setup_confirmation", "setup_id": snap["setup_id"], "observation_id": snap["observation_id"],
            "confirmed_at": snap["observed_at"], "symbol": snap["symbol"], "direction": snap["direction"],
            "strategy_id": snap["strategy_id"], **({"shadow": True} if snap.get("shadow") else {})}


def server_bars(start: datetime, closes: list[float]) -> list[dict]:
    """Raw MT5 M15 rates (server-time epochs) starting at a real instant."""
    return [{"time": server_epoch_of(start + timedelta(minutes=15 * i)), "open": c, "high": c + 0.2, "low": c - 0.2, "close": c}
            for i, c in enumerate(closes)]


class ReverificationTests(unittest.TestCase):
    OBSERVED = datetime(2026, 9, 23, 12, 7, 30, tzinfo=timezone.utc)

    def test_verified_view_rebuilds_provenance_from_raw_epochs_without_touching_the_record(self):
        original = snapshot(self.OBSERVED)
        before = json.dumps(original, sort_keys=True)
        view, reason = tr.verified_view(original, BASIS)
        self.assertIsNone(reason)
        self.assertEqual(json.dumps(original, sort_keys=True), before, "the stored record is not mutated")
        self.assertEqual(view["source_timestamp"], "2026-09-23T12:00:00+00:00")
        self.assertEqual(view["time_provenance"]["timezone_normalization_status"], "VERIFIED")
        self.assertEqual((view["data_quality"]["timestamp_quality"], view["data_quality"]["flags"]), ("VERIFIED", []))
        self.assertAlmostEqual(view["data_quality"]["tick_age_seconds"], 0.4, places=3)   # tick 0.4 s before receipt
        # A wrong basis is caught by the existing quality rules (future source time).
        wrong, _ = tr.verified_view(original, "Etc/GMT-2")
        self.assertIn("FUTURE_SOURCE_TIMESTAMP", wrong["data_quality"]["flags"])

    def test_old_new_ambiguous_and_malformed_records(self):
        self.assertEqual(tr.verified_view(snapshot(self.OBSERVED, raw=False), BASIS), (None, "NO_RAW_MT5_EPOCH"))
        already = snapshot(self.OBSERVED)
        already["time_provenance"]["timezone_normalization_status"] = "VERIFIED"
        self.assertIs(tr.verified_view(already, BASIS)[0], already, "records already verified are used as recorded")
        ambiguous = snapshot(datetime(2026, 11, 1, 5, 40, tzinfo=timezone.utc))   # server 08:40 on the US fall-back Sunday
        self.assertEqual(tr.verified_view(ambiguous, BASIS), (None, "SOURCE_TIME_UNVERIFIED:AMBIGUOUS_LOCAL_SOURCE_TIME"))
        malformed = snapshot(self.OBSERVED)
        malformed["time_provenance"]["bar_open_time"]["raw_mt5_epoch"] = "garbage"
        self.assertEqual(tr.verified_view(malformed, BASIS)[1], "SOURCE_TIME_INVALID:INVALID_MT5_EPOCH_OR_SOURCE_TIME_BASIS")

    def test_target_and_stop_hits_are_derived_verified_and_kept_per_strategy(self):
        long_trend = snapshot(self.OBSERVED)                                   # LONG: target 106, stop 98
        short_sr = snapshot(self.OBSERVED, strategy_id="support_resistance", direction="SHORT")  # SHORT: target 94, stop 102
        old = snapshot(self.OBSERVED, raw=False)
        old["setup_id"], old["observation_id"] = "s-old", "o-old"
        rising = [100.0 + 0.5 * i for i in range(120)]                          # reaches 106 within ~3h: LONG target, SHORT stop
        bars, dropped = tr.normalized_bars(server_bars(self.OBSERVED + timedelta(minutes=8), rising), BASIS)
        self.assertEqual(dropped, 0)
        legacy_outcome = {"record_type": "market_outcome", "setup_id": "s-trendlineLONG", "observation_id": "o-trendlineLONG",
                          "horizon": "4h", "label": "WIN"}
        report = tr.reverify_outcomes([long_trend, short_sr, old], [confirmation(long_trend), confirmation(short_sr), confirmation(old)],
                                      [legacy_outcome], {"XAUUSD": bars}, BASIS, now=self.OBSERVED + timedelta(days=2))
        trend, sr = report["strategies"]["trendline"], report["strategies"]["support_resistance"]
        self.assertEqual(trend["before"], {"unverified": 1, "pending": 1})
        self.assertEqual(trend["after"], {"verified_target": 1, "time_unverifiable": 1})
        self.assertEqual(trend["time_unverifiable"], {"NO_RAW_MT5_EPOCH": 1})
        self.assertEqual(trend["stored_outcomes_still_quarantined"], 1, "stored legacy outcomes are not promoted")
        self.assertEqual((sr["confirmations"], sr["before"], sr["after"]), (1, {"pending": 1}, {"verified_stop": 1}))
        self.assertGreater(report["derived_outcome_records"], 0)

    def test_dst_invalid_bars_are_dropped_not_guessed(self):
        raw = [{"time": server_epoch(2026, 3, 8, h, m), "open": 1, "high": 1, "low": 1, "close": 1}
               for h, m in ((8, 45), (9, 0), (9, 15), (10, 0), (10, 15))]
        bars, dropped = tr.normalized_bars(raw, BASIS)
        self.assertEqual(dropped, 2)
        # server 08:45 = 01:45 EST = 06:45 UTC; server 10:00 = 03:00 EDT = 07:00 UTC (09:00-09:59 does not exist)
        self.assertEqual([datetime.fromtimestamp(b["time"], timezone.utc).strftime("%H:%M") for b in bars], ["06:45", "07:00", "07:15"])

    def test_outcomes_do_not_depend_on_the_host_timezone(self):
        code = ("import sys, json; sys.path[:0] = ['.', 'tests']; from datetime import timedelta; import test_time_basis as t; "
                "import time_reverification as tr; s = t.snapshot(t.ReverificationTests.OBSERVED); "
                "bars, _ = tr.normalized_bars(t.server_bars(t.ReverificationTests.OBSERVED + timedelta(minutes=8), [100.0 + 0.5 * i for i in range(120)]), t.BASIS); "
                "r = tr.reverify_outcomes([s], [t.confirmation(s)], [], {'XAUUSD': bars}, t.BASIS, now=t.ReverificationTests.OBSERVED + timedelta(days=2)); "
                "print(json.dumps(r['strategies'], sort_keys=True))")
        outputs = set()
        for tz in ("UTC", "Africa/Kampala", "America/Los_Angeles", "Asia/Tokyo"):
            outputs.add(subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env={**os.environ, "TZ": tz},
                                       text=True, capture_output=True, check=True).stdout)
        self.assertEqual(len(outputs), 1)
        self.assertIn('"verified_target": 1', outputs.pop())


if __name__ == "__main__":
    unittest.main()
