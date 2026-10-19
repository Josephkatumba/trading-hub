"""T-036: no strategy limit, promotion gate, qualification registry and lifecycle report, expansion candidates."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from strategy_bank import engine, expansion, qualification, rules

try:
    from test_strategy_bank import frames, truncated
except ImportError:
    from tests.test_strategy_bank import frames, truncated


def dummy_spec(key, decide=lambda ctx, i: None, status=rules.RESEARCH):
    return {"key": key, "name": key.replace("_", " ").title(), "status": status, "decide": decide, "timeframe": "H1",
            "instruments": rules.ALL, "entry": "x", "indicators": "x", "confirmation": "x", "stop": "x",
            "take_profit": "2R", "min_rr": 1.5, "invalidation": "x", "data": ["H1"]}


class TempRegistry(unittest.TestCase):
    """Isolates the qualification registry and bank store in a temporary data directory."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.dir = Path(self._temp.name)
        self._specs, self._by_key = list(rules.SPECS), dict(rules.BY_KEY)
        self.patches = [mock.patch.object(qualification, "path", lambda: self.dir / "qualification.jsonl"),
                        mock.patch.object(engine, "bank_dir", lambda: self.dir)]
        for p in self.patches:
            p.start()
        qualification._CACHE.update(path=None, mtime=None, rows=[])

    def tearDown(self):
        for p in self.patches:
            p.stop()
        rules.SPECS[:] = self._specs
        rules.BY_KEY.clear()
        rules.BY_KEY.update(self._by_key)
        qualification._CACHE.update(path=None, mtime=None, rows=[])
        self._temp.cleanup()


class NoLimitTests(TempRegistry):
    def test_register_any_number_of_strategies(self):
        start = len(rules.SPECS)
        for k in range(40):                                   # well past the old 20
            spec = rules.register(dummy_spec(f"dummy_{k}"))
            self.assertEqual(spec["n"], start + k + 1)
        self.assertEqual(len(rules.SPECS), start + 40)
        self.assertIn("dummy_39", {s["key"] for s in rules.scanned()})
        self.assertEqual(len(engine.statistics(engine.BankStore(self.dir))), start + 40)

    def test_registration_rules(self):
        with self.assertRaises(ValueError):
            rules.register(dummy_spec("ema_crossover"))                     # duplicate key
        with self.assertRaises(ValueError):
            rules.register(dummy_spec("direct_alert", status=rules.EXPERIMENTAL))   # never straight to alerting
        bad = dummy_spec("incomplete")
        del bad["stop"]
        with self.assertRaises(ValueError):
            rules.register(bad)
        with self.assertRaises(ValueError):
            rules.register(dummy_spec("no_decide", decide=None))


class PromotionGateTests(TempRegistry):
    def signal(self, key, minutes=0, direction="LONG"):
        t = datetime(2026, 10, 20, 10, tzinfo=timezone.utc) + timedelta(minutes=minutes)
        return {"signal_id": f"s_{key}_{minutes}", "strategy_key": key, "strategy_name": key, "symbol": "EURUSD",
                "direction": direction, "confirmed_at": t.isoformat()}

    def test_research_signals_never_alert_or_block_approved_strategies(self):
        rules.register(dummy_spec("shadow_idea"))
        store = engine.BankStore(self.dir)
        bank = engine.Bank(store)
        research = self.signal("shadow_idea")
        bank._attach(research, 0)
        store.put_signal(research)
        self.assertEqual(research["alert"], "research only (not alerted)")
        self.assertNotIn("opportunity_id", research)                       # it did not open an opportunity
        approved = self.signal("ema_crossover", minutes=30)                # T-034 strategy: unchanged behaviour
        bank._attach(approved, 0)
        self.assertEqual(approved["alert"], "primary")
        later = self.signal("shadow_idea", minutes=45)
        bank._attach(later, 0)
        self.assertEqual(later["alert"], "research only (not alerted)")
        opp = store.opportunities[approved["opportunity_id"]]
        self.assertEqual(opp["strategies"], ["ema_crossover"])              # only the approved strategy owns it
        self.assertEqual(opp["research_strategies"], ["shadow_idea"])

    def test_promotion_requires_forward_evidence_and_approval(self):
        rules.register(dummy_spec("candidate"))
        key = "candidate"
        qualification.transition(key, qualification.RESEARCHING, "start")
        with self.assertRaises(ValueError):
            qualification.promote(key, qualification.QUALIFIED, approval="CEO")          # skips forward testing
        qualification.promote(key, qualification.BACKTESTED, approval="")
        qualification.promote(key, qualification.FORWARD_TESTING, approval="")
        self.assertFalse(rules.alerting(rules.BY_KEY[key]))
        weak = {"signals": 80, "resolved": 70, "expectancy_r": 0.01, "profit_factor": 1.02}
        strong = {"signals": 80, "resolved": 70, "expectancy_r": 0.12, "profit_factor": 1.3}
        with mock.patch.object(qualification, "forward_evidence", return_value=weak):
            with self.assertRaises(ValueError):
                qualification.promote(key, qualification.QUALIFIED, approval="CEO 2026-11-30")
        with mock.patch.object(qualification, "forward_evidence", return_value=strong):
            with self.assertRaises(ValueError):
                qualification.promote(key, qualification.QUALIFIED, approval="  ")       # no approval reference
            qualification.promote(key, qualification.QUALIFIED, approval="CEO 2026-11-30")
        self.assertTrue(rules.alerting(rules.BY_KEY[key]))
        qualification.demote(key, qualification.FORWARD_TESTING, "forward expectancy fell below zero")
        self.assertFalse(rules.alerting(rules.BY_KEY[key]))
        steps = [(r["from"], r["to"]) for r in qualification.history(key)]
        self.assertEqual(steps[-2:], [("FORWARD_TESTING", "QUALIFIED"), ("QUALIFIED", "FORWARD_TESTING")])
        self.assertEqual(qualification.history(key)[-2]["approval"], "CEO 2026-11-30")


class LifecycleReportTests(TempRegistry):
    def test_window_events_and_counts(self):
        t = lambda d, h=12: datetime(2026, 10, d, h, tzinfo=timezone.utc).isoformat()
        qualification.transition("a", qualification.APPROVED_EXPERIMENTAL, "baseline", at=t(1))
        qualification.transition("b", qualification.RESEARCHING, "new idea", at=t(5))
        qualification.transition("b", qualification.BACKTESTED, "passed", at=t(6))
        qualification.transition("b", qualification.FORWARD_TESTING, "admitted", at=t(6, 13))
        qualification.transition("c", qualification.RESEARCHING, "new idea", at=t(6))
        qualification.transition("c", qualification.ARCHIVED, "rejected on train", at=t(6, 14))
        qualification.transition("d", qualification.QUALIFIED, "x", at=t(2))
        qualification.transition("d", qualification.FORWARD_TESTING, "demoted", at=t(6, 15))
        start, end = datetime(2026, 10, 6, tzinfo=timezone.utc), datetime(2026, 10, 7, tzinfo=timezone.utc)
        r = qualification.lifecycle_report(start, end)
        self.assertEqual([e["key"] for e in r["registered"]], ["c"])
        self.assertEqual([(e["key"], e["to"]) for e in r["promoted"]], [("b", "BACKTESTED"), ("b", "FORWARD_TESTING")])
        self.assertEqual([e["key"] for e in r["demoted"]], ["d"])
        self.assertEqual([e["key"] for e in r["rejected"]], ["c"])
        self.assertEqual(len(r["transitions"]), 5)
        self.assertEqual(r["counts"]["registered"], 4)
        self.assertEqual(r["counts"]["actively_evaluated"], 2)          # b, d forward testing
        self.assertEqual(r["counts"]["qualified_to_signal"], 1)         # a
        self.assertEqual(r["counts"]["rejected_archived"], 1)           # c
        early = qualification.lifecycle_report(datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 3, tzinfo=timezone.utc))
        self.assertEqual(early["counts"]["qualified_to_signal"], 2)      # a and d (as of that window end)

    def test_sync_baselines_the_bank_once(self):
        with mock.patch.object(qualification, "data_directory", lambda: self.dir):
            added = qualification.sync()
            self.assertEqual(added, len(rules.SPECS))
            self.assertEqual(qualification.sync(), 0)
        self.assertEqual(qualification.current_status("ema_crossover"), qualification.APPROVED_EXPERIMENTAL)
        self.assertEqual(qualification.current_status("trendline_bounce"), qualification.PRODUCTION)
        self.assertEqual(qualification.current_status("vwap_reversion"), qualification.UNSUPPORTED)
        self.assertEqual(qualification.current("ema_crossover")["at"], qualification.T034_COMMITTED_AT)


class ExpansionTests(TempRegistry):
    def test_only_admitted_candidates_are_registered_as_research(self):
        self.assertEqual(expansion.register_admitted(), [])
        key = "turtle_soup_n55"
        qualification.transition(key, qualification.FORWARD_TESTING, "admitted")
        self.assertEqual(expansion.register_admitted(), [key])
        self.assertEqual(expansion.register_admitted(), [])                 # idempotent
        self.assertEqual(rules.BY_KEY[key]["status"], rules.RESEARCH)
        self.assertFalse(rules.alerting(rules.BY_KEY[key]))

    def test_candidates_are_causal(self):
        fr = frames(days=150, seed=13, vol=0.002)
        full = rules.Ctx("EURUSD", fr)
        checked = 0
        for key, spec in expansion.CANDIDATES.items():
            tf = spec["timeframe"]
            n = len(full.a[tf]["close"])
            fired = [i for i in range(400, n) if spec["decide"](full, i)]
            for i in fired[:3] + list(range(400, n, max(1, (n - 400) // 4))):
                close_t = full.close_utc(tf, i)
                part = rules.Ctx("EURUSD", truncated(fr, close_t))
                a, b = spec["decide"](full, i), spec["decide"](part, len(part.a[tf]["close"]) - 1)
                self.assertEqual(a is None, b is None, f"{key} looks ahead at bar {i}")
                if a is not None:
                    self.assertEqual(a.direction, b.direction)
                    for x, y in ((a.stop, b.stop), (a.target, b.target)):
                        if x is not None:
                            self.assertAlmostEqual(x, y, places=7, msg=key)
                checked += 1
        self.assertGreater(checked, 40)


class RegistryEventsTests(TempRegistry):
    def test_report_interface_shape_and_window(self):
        from research import registry_events
        t = lambda d, h=12: datetime(2026, 10, d, h, tzinfo=timezone.utc).isoformat()
        qualification.transition("a", qualification.APPROVED_EXPERIMENTAL, "baseline", name="EMA Crossover", at=t(1))
        qualification.transition("b", qualification.RESEARCHING, "new", name="Idea B", at=t(5))
        qualification.transition("b", qualification.BACKTESTED, "passed", at=t(6))
        qualification.transition("c", qualification.RESEARCHING, "new", name="Idea C", at=t(6))
        qualification.transition("c", qualification.ARCHIVED, "rejected on train", at=t(6, 14))
        ledger = self.dir / "research" / "ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({"recorded_at": t(6, 15), "kind": "t036-bank-expansion", "name": "T036 idea: idea_c",
                                      "train": {"expectancy_r": 0.3}, "validation": {"expectancy_r": -0.08},
                                      "verdict": "REJECTED ON VALIDATION"}) + "\n", encoding="utf-8")
        with mock.patch("storage_config.data_directory", lambda: self.dir):
            r = registry_events(datetime(2026, 10, 6, tzinfo=timezone.utc), datetime(2026, 10, 7, tzinfo=timezone.utc))
            empty = registry_events(datetime(2031, 1, 1, tzinfo=timezone.utc), datetime(2031, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(set(r), {"new", "testing", "promoted", "demoted", "rejected", "counts", "discoveries"})
        self.assertEqual([e["name"] for e in r["new"]], ["Idea C"])
        self.assertEqual(r["testing"], ["Idea B"])
        self.assertEqual([(e["name"], e["to"]) for e in r["promoted"]], [("Idea B", "BACKTESTED")])
        self.assertEqual([e["name"] for e in r["rejected"]], ["Idea C"])
        self.assertEqual(r["counts"], {"registered": 3, "actively evaluated": 1, "qualified to signal": 1, "rejected/archived": 1})
        self.assertEqual(r["discoveries"], ["idea: idea_c: training +0.30R per trade, validation -0.08R per trade; rejected on validation."])
        self.assertEqual((empty["new"], empty["promoted"], empty["rejected"], empty["discoveries"]), ([], [], [], []))


if __name__ == "__main__":
    unittest.main()
