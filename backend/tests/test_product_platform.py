"""Phase 1 product layer: plans, evidence tiers, execution policy and /api/platform routes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient

import commercial
from commercial_store import CommercialStore
from product import api, evidence, execution_policy as ep, plans
from strategy_bank import qualification


def good_order(**over):
    order = {"side": "BUY", "entry": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "risk_pct": 0.25,
             "strategy_tier": "VALIDATED"}
    order.update(over)
    return order


def demo_account(**over):
    account = {"is_demo": True, "is_live": False, "daily_loss_pct": 0.0, "open_positions": 0, "consecutive_losses": 0}
    account.update(over)
    return account


ENABLED = ep.config_from_env({"TRADEDEN_EXECUTION_ENABLED": "1"})


class PlanTests(unittest.TestCase):
    def test_catalogue_is_provisional_and_billing_inactive(self):
        cat = plans.catalogue()
        self.assertFalse(cat["billing_active"])
        self.assertTrue(cat["prices_provisional"])
        self.assertEqual([(p["code"], p["price_usd_month"]) for p in cat["plans"]],
                         [("FREE", 0), ("TRADER", 19), ("PROFESSIONAL", 49), ("AUTOMATED", 99)])
        self.assertNotIn("live", {p["execution"] for p in cat["plans"]})

    def test_legacy_mapping_matches_enforced_commercial_limits(self):
        self.assertEqual(plans.plan_for_legacy("pro").code, "TRADER")
        self.assertEqual(plans.plan_for_legacy("pro").price_usd_month, commercial.PRO_PRICE_USD)
        self.assertEqual(set(plans.plan_for_legacy("free").symbols), set(commercial.FREE_SYMBOLS))
        for unknown in (None, "", "enterprise", "PRO "):
            self.assertEqual(plans.plan_for_legacy(unknown).code, "FREE")

    def test_ungrantable_plans_and_unknown_capabilities(self):
        self.assertFalse(plans.PLANS["PROFESSIONAL"].grantable)
        self.assertFalse(plans.PLANS["AUTOMATED"].grantable)
        self.assertFalse(plans.allows(plans.PLANS["AUTOMATED"], "live_execution"))
        self.assertFalse(plans.allows(plans.PLANS["FREE"], "exports"))
        self.assertTrue(plans.allows(plans.PLANS["TRADER"], "exports"))


class EvidenceTests(unittest.TestCase):
    STRONG = {"resolved": 400, "expectancy_r": 0.4, "profit_factor": 1.9, "r_std": 1.2}

    def test_thresholds_match_qualification_gate(self):
        self.assertEqual((evidence.MIN_FORWARD_SIGNALS, evidence.MIN_EXPECTANCY_R, evidence.MIN_PROFIT_FACTOR),
                         (qualification.MIN_FORWARD_SIGNALS, qualification.MIN_EXPECTANCY_R, qualification.MIN_PROFIT_FACTOR))

    def test_labels_never_make_a_strategy_validated(self):
        for status in ("PRODUCTION", "APPROVED_EXPERIMENTAL", "QUALIFIED", "FORWARD_TESTING", None):
            self.assertEqual(evidence.classify(status, None, "CEO-1")["tier"], "EXPERIMENTAL")
        weak = {"resolved": 200, "expectancy_r": -0.1, "profit_factor": 0.8}
        result = evidence.classify("PRODUCTION", weak)
        self.assertEqual(result["tier"], "EXPERIMENTAL")
        self.assertIn("not a validated edge", result["reasons"][0])
        self.assertEqual(evidence.classify("FORWARD_TESTING", {"resolved": 59, "expectancy_r": 1, "profit_factor": 3})["tier"],
                         "EXPERIMENTAL")

    def test_threshold_noise_is_not_validation(self):
        # Recorded Strategy Bank numbers (2026-11-24): clears the alert gate, not significance.
        marginal = {"resolved": 115, "expectancy_r": 0.0565, "profit_factor": 1.112, "r_std": 1.2}
        self.assertEqual(evidence.classify("APPROVED_EXPERIMENTAL", marginal, tested=16)["tier"], "EXPERIMENTAL")
        self.assertIn("not distinguishable from zero", evidence.classify("APPROVED_EXPERIMENTAL", marginal, tested=16)["reasons"][-1])
        self.assertEqual(evidence.classify("FORWARD_TESTING", self.STRONG, tested=16)["tier"], "VALIDATED")
        # More strategies tested -> a stricter bound, never a looser one.
        self.assertGreater(evidence.lower_bound(self.STRONG, 1), evidence.lower_bound(self.STRONG, 100))
        self.assertIsNone(evidence.lower_bound({"resolved": 80, "expectancy_r": 0.2}, 1))

    def test_validated_and_production_need_evidence_and_approval(self):
        self.assertEqual(evidence.classify("FORWARD_TESTING", self.STRONG)["tier"], "VALIDATED")
        self.assertEqual(evidence.classify("QUALIFIED", self.STRONG, None)["tier"], "VALIDATED")
        self.assertEqual(evidence.classify("QUALIFIED", self.STRONG, "  ")["tier"], "VALIDATED")
        self.assertEqual(evidence.classify("QUALIFIED", self.STRONG, "CEO-7")["tier"], "PRODUCTION")
        self.assertEqual(evidence.classify("ARCHIVED", self.STRONG)["tier"], "ARCHIVED")
        self.assertEqual(evidence.classify("UNSUPPORTED")["tier"], "ARCHIVED")

    def test_catalogue_uses_latest_transition_and_honest_statement(self):
        rows = [{"key": "a", "to": "FORWARD_TESTING", "at": "1"}, {"key": "a", "to": "ARCHIVED", "at": "2"},
                {"key": "b", "to": "PRODUCTION", "at": "1", "name": "Trend"}]
        items = evidence.catalogue(rows, lambda key: {"resolved": 3, "expectancy_r": 0.4, "profit_factor": 2.0})
        self.assertEqual({i["key"]: i["tier"] for i in items}, {"a": "ARCHIVED", "b": "EXPERIMENTAL"})
        self.assertEqual(evidence.summary(items)["statement"], "No strategy has demonstrated a validated edge.")

    def test_forward_stats_matches_qualification_formula(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"TRADING_HUB_DATA_DIR": tmp}):
            folder = Path(tmp) / "strategy_bank"
            folder.mkdir()
            rows = [{"signal_id": f"s{i}", "strategy_key": "k", "symbol": "XAUUSD", "confirmed_at": str(i),
                     "outcome_status": status, "r_multiple": r}
                    for i, (status, r) in enumerate([("TARGET_HIT", 2), ("STOP_HIT", -1), ("TIME_EXIT", 0.3),
                                                     ("EXPIRED", None), ("STOP_HIT", -1)])]
            (folder / "signals.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            reference = qualification.forward_evidence("k")
            reference.pop("measured_at")
            stats = evidence.forward_stats(rows)["k"]
            self.assertIsNotNone(stats.pop("r_std"))
            self.assertEqual(stats, reference)


class ExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_disabled_by_default_and_live_mode_refused(self):
        self.assertFalse(ep.config_from_env({}).enabled)
        self.assertFalse(ep.config_from_env({"TRADEDEN_EXECUTION_ENABLED": "true"}).enabled)
        live = ep.config_from_env({"TRADEDEN_EXECUTION_ENABLED": "1", "TRADEDEN_EXECUTION_MODE": "live"})
        self.assertFalse(live.enabled)
        self.assertTrue(live.problems)
        decision = ep.evaluate(good_order(), demo_account(), ep.config_from_env({}), None)
        self.assertFalse(decision.allowed)
        self.assertIn("disabled", decision.reasons[0])
        self.assertFalse(ep.LIVE_TRADING_SUPPORTED)

    def test_limits_are_clamped_to_hard_ceilings(self):
        config = ep.config_from_env({"TRADEDEN_EXECUTION_ENABLED": "1", "TRADEDEN_MAX_RISK_PER_TRADE_PCT": "5",
                                     "TRADEDEN_MAX_DAILY_LOSS_PCT": "nan", "TRADEDEN_MAX_OPEN_POSITIONS": "-2"})
        self.assertEqual(config.limits.risk_per_trade_pct, ep.HARD_CEILINGS["risk_per_trade_pct"])
        self.assertEqual(config.limits.daily_loss_pct, ep.DEFAULTS["daily_loss_pct"])
        self.assertEqual(config.limits.max_open_positions, ep.DEFAULTS["max_open_positions"])
        self.assertEqual(len(config.problems), 3)

    def test_valid_demo_order_passes_only_when_everything_holds(self):
        self.assertTrue(ep.evaluate(good_order(), demo_account(), ENABLED, None).allowed)
        failing = [
            (good_order(), demo_account(is_live=True)),
            (good_order(), demo_account(is_demo=None)),
            (good_order(), {k: v for k, v in demo_account().items() if k != "is_live"}),
            (good_order(stop_loss=None), demo_account()),
            (good_order(stop_loss=101), demo_account()),
            (good_order(side="SELL"), demo_account()),
            (good_order(take_profit=99.5), demo_account()),
            (good_order(risk_pct=0.5), demo_account()),
            (good_order(risk_pct=None), demo_account()),
            (good_order(), demo_account(daily_loss_pct=0.9)),
            (good_order(), demo_account(daily_loss_pct=None)),
            (good_order(), demo_account(open_positions=1)),
            (good_order(), demo_account(consecutive_losses=2)),
            (good_order(), demo_account(open_positions="0")),
            (good_order(strategy_tier="EXPERIMENTAL"), demo_account()),
            (good_order(entry=float("nan")), demo_account()),
        ]
        for order, account in failing:
            with self.subTest(order=order, account=account):
                self.assertFalse(ep.evaluate(order, account, ENABLED, None).allowed)

    def test_forward_experiment_allows_experimental_strategy_on_demo_only(self):
        order = good_order(strategy_tier="EXPERIMENTAL", forward_experiment=True)
        self.assertTrue(ep.evaluate(order, demo_account(), ENABLED, None).allowed)
        self.assertFalse(ep.evaluate(order, demo_account(is_live=True, is_demo=False), ENABLED, None).allowed)

    def test_emergency_stop_blocks_and_is_audited(self):
        ep.engage_emergency_stop("drill", folder=self.folder)
        state = ep.emergency_stop_state(self.folder)
        self.assertEqual(state["reason"], "drill")
        self.assertFalse(ep.evaluate(good_order(), demo_account(), ENABLED, state).allowed)
        self.assertFalse(ep.status(ENABLED, self.folder)["execution_enabled"])
        with self.assertRaises(ValueError):
            ep.release_emergency_stop(" ", folder=self.folder)
        self.assertIsNotNone(ep.release_emergency_stop("drill over", folder=self.folder))
        self.assertIsNone(ep.emergency_stop_state(self.folder))
        events = [json.loads(l)["event"] for l in (self.folder / "audit.jsonl").read_text().splitlines()]
        self.assertEqual(events, ["EMERGENCY_STOP_ENGAGED", "EMERGENCY_STOP_RELEASED"])

    def test_corrupt_stop_file_counts_as_engaged(self):
        (self.folder / "EMERGENCY_STOP").write_text("{not json")
        self.assertIsNotNone(ep.emergency_stop_state(self.folder))


class PlatformRouteTests(unittest.TestCase):
    def test_private_mode_routes(self):
        app = FastAPI()
        app.include_router(api.router)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"TRADING_HUB_DATA_DIR": tmp}, clear=False):
            os.environ.pop("TRADEDEN_EXECUTION_ENABLED", None)
            client = TestClient(app)
            self.assertEqual(len(client.get("/api/platform/plans").json()["plans"]), 4)
            status = client.get("/api/platform/execution/status").json()
            self.assertFalse(status["execution_enabled"])
            self.assertFalse(status["live_trading_supported"])
            self.assertFalse(status["adapters"]["mt5"]["orders"])
            ev = client.get("/api/platform/strategies/evidence").json()
            self.assertEqual(ev["counts"]["VALIDATED"] + ev["counts"]["PRODUCTION"], 0)
            self.assertTrue(client.get("/api/platform/modules").json()["modules"])

    def test_commercial_mode_exposes_only_the_plan_catalogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = CommercialStore("sqlite:///" + str(Path(tmp) / "users.db"))
            db.migrate()
            env = {"TRADING_HUB_AUTH_MODE": "oidc", "TRADING_HUB_DATABASE_URL": "postgresql+psycopg://not-used",
                   "TRADING_HUB_OIDC_ISSUER": "https://identity.test/", "TRADING_HUB_OIDC_CLIENT_ID": "client",
                   "TRADING_HUB_OIDC_CLIENT_SECRET": "test-only", "TRADING_HUB_PUBLIC_ORIGIN": "https://app.test",
                   "TRADING_HUB_SESSION_SECRET": "test-only-long-state-signing-key-123456789"}
            with patch.dict(os.environ, env), patch.object(commercial, "store", return_value=db):
                app = FastAPI()
                commercial.install(app)
                app.include_router(api.router)
                with TestClient(app, base_url="https://app.test") as client:
                    self.assertEqual(client.get("/api/platform/plans").status_code, 200)
                    self.assertEqual(client.get("/api/platform/execution/status").status_code, 401)
                    token, _ = db.login("https://identity.test/", "alice")
                    client.cookies.set(commercial.COOKIE, token)
                    for path in ("/api/platform/execution/status", "/api/platform/strategies/evidence",
                                 "/api/platform/modules"):
                        self.assertEqual(client.get(path).status_code, 403, path)
            db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
