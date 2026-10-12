import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import commercial
from beta_preflight import configuration_checks
from commercial_store import CommercialStore


class BetaReadinessTests(unittest.TestCase):
    def test_preflight_redacts_secrets_and_fails_without_services(self):
        with patch.dict(os.environ, {}, clear=True):
            checks = configuration_checks()
        self.assertFalse(all(checks.values()))
        self.assertTrue(all(isinstance(v, bool) for v in checks.values()))

    def test_invitation_subject_and_issuer_and_revocation(self):
        with patch.dict(os.environ, {"TRADING_HUB_PRIVATE_BETA":"1", "TRADING_HUB_BETA_SUBJECTS":'["alice"]',
                                     "TRADING_HUB_OIDC_ISSUER":"https://identity.test/"}):
            self.assertTrue(commercial.beta_allowed("https://identity.test/", "alice"))
            self.assertFalse(commercial.beta_allowed("https://other.test/", "alice"))
            self.assertFalse(commercial.beta_allowed("https://identity.test/", "bob"))
        with patch.dict(os.environ, {"TRADING_HUB_PRIVATE_BETA":"1", "TRADING_HUB_BETA_SUBJECTS":"[]"}):
            from fastapi import FastAPI
            with self.assertRaises(RuntimeError): commercial.install(FastAPI())

    def test_database_schema_readiness_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            db = CommercialStore("sqlite:///" + str(Path(root)/"beta.db"))
            try:
                with self.assertRaises(Exception): db.healthy()
                db.migrate()
                self.assertTrue(db.healthy())
                fresh=([], {"status":"CONNECTED","market_count":1}, {"status":"FRESH","age_seconds":0})
                with patch.object(main, "latest_scan", return_value=fresh), patch.dict(os.environ, {"TRADING_HUB_AUTH_MODE":"oidc"}), patch.object(commercial,"store",return_value=db):
                    self.assertEqual(main.readiness().status_code,200)
                    with patch.object(db,"healthy",side_effect=RuntimeError("sensitive connection string")):
                        response=main.readiness()
                        self.assertEqual(response.status_code,503)
                        self.assertNotIn("sensitive",response.body.decode())
            finally: db.engine.dispose()

    def test_only_qualified_live_fresh_opportunities(self):
        plan={"mode":"LIVE","trade_qualified":True,"direction":"LONG","entry":100,"stop_loss":90,"take_profit":120,
              "round_trip_cost_price":0,"strategy_id":"smc"}
        market={"symbol":"XAUUSD","bid":100,"ask":100,"tick_age_seconds":0,"strategies":[plan,
                {**plan,"trade_qualified":False},{**plan,"mode":"SHADOW"},{**plan,"take_profit":110}]}
        freshness={"status":"FRESH","age_seconds":0}
        with patch.object(main,"latest_scan",return_value=([market],{},freshness)):
            self.assertEqual(len(main.trade_opportunities()["opportunities"]),1)
            self.assertEqual(len(market["strategies"]),4)
        with patch.object(main,"latest_scan",return_value=([market],{},{**freshness,"status":"STALE"})):
            self.assertEqual(main.trade_opportunities()["opportunities"],[])
        with patch.object(main,"latest_scan",return_value=([market],{},{**freshness,"age_seconds":301})):
            self.assertEqual(main.trade_opportunities()["opportunities"],[])
        market["tick_age_seconds"]=None
        with patch.object(main,"latest_scan",return_value=([market],{},freshness)):
            self.assertEqual(main.trade_opportunities()["opportunities"],[])
