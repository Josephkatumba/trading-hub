import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert
from authlib.integrations.starlette_client import OAuth
from joserfc import jwt
from joserfc.jwk import RSAKey
import commercial
from commercial_store import CommercialStore, entitlements, journal, metadata
from trade_planning import apply_plan, quantize_level
from qualification import qualify, apply
from intelligence_chart import normalize_candles


class CommercialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = CommercialStore("sqlite:///" + str(Path(self.tmp.name) / "users.db"))
        self.db.migrate()
        self.env = patch.dict(os.environ, {"TRADING_HUB_AUTH_MODE": "oidc", "TRADING_HUB_DATABASE_URL": "postgresql+psycopg://not-used",
            "TRADING_HUB_OIDC_ISSUER": "https://identity.test/", "TRADING_HUB_OIDC_CLIENT_ID": "client",
            "TRADING_HUB_OIDC_CLIENT_SECRET": "test-only", "TRADING_HUB_PUBLIC_ORIGIN": "https://app.test",
            "TRADING_HUB_SESSION_SECRET": "test-only-long-state-signing-key-123456789"})
        self.env.start()
        self.storage = patch.object(commercial, "store", return_value=self.db)
        self.storage.start()
        self.app = FastAPI()
        commercial.install(self.app)
        @self.app.get("/api/market/radar")
        def radar():
            return {"markets": [{"symbol": "XAUUSD", "strategies": [{"score": 70}]}, {"symbol": "BTCUSD", "score": 90}]}
        @self.app.get("/api/market/chart")
        def chart():
            return {"symbol": "XAUUSD", "candles": [{"time": int(time.time())-10*86400, "open": 1, "high": 2, "low": 1, "close": 2}]}
        @self.app.get("/api/market/opportunities")
        def opportunities():
            return {"opportunities": [{"symbol":"XAUUSD","trade_qualified":True}, {"symbol":"BTCUSD","trade_qualified":True}]}
        self.client = TestClient(self.app, base_url="https://app.test")
        self.a, self.ca = self.db.login("https://identity.test/", "alice")
        self.b, self.cb = self.db.login("https://identity.test/", "bob")

    def tearDown(self):
        self.client.close()
        self.storage.stop()
        self.env.stop()
        self.db.engine.dispose()
        self.tmp.cleanup()

    def login_as(self, token):
        self.client.cookies.set(commercial.COOKIE, token)

    def test_anonymous_and_forged_session_fail_closed(self):
        self.assertEqual(self.client.get("/api/journal/review").status_code, 401)
        self.login_as("forged")
        self.assertEqual(self.client.get("/api/market/radar").status_code, 401)
        self.assertEqual(self.client.post("/api/billing/webhook").status_code, 401)

    def test_beta_invites_are_enforced_for_existing_sessions(self):
        with patch.dict(os.environ,{"TRADING_HUB_PRIVATE_BETA":"1","TRADING_HUB_BETA_SUBJECTS":'["alice"]'}):
            self.login_as(self.a)
            self.assertEqual(self.client.get("/api/auth/me").status_code,200)
            self.login_as(self.b)
            self.assertEqual(self.client.get("/api/journal/review").status_code,403)

    def test_cross_user_records_and_conflicting_versions(self):
        self.login_as(self.a)
        body = {"payload": {"notes": "private", "user_id": self.db.identity(self.b)["id"]}, "version": 0}
        url = "/api/journal/review/same-id"
        self.assertEqual(self.client.put(url, json=body).status_code, 403)
        self.assertEqual(self.client.put(url, json=body, headers={"x-csrf-token": self.cb}).status_code, 403)
        self.assertEqual(self.client.put(url, json=body, headers={"x-csrf-token": self.ca}).status_code, 200)
        self.assertEqual(self.client.put(url, json=body, headers={"x-csrf-token": self.ca}).status_code, 409)
        self.login_as(self.b)
        self.assertEqual(self.client.get("/api/journal/review").json()["records"], [])
        self.assertEqual(self.client.delete(url+"?version=1", headers={"x-csrf-token": self.cb}).status_code, 409)
        self.assertEqual(self.client.put(url, json=body, headers={"x-csrf-token": self.cb}).status_code, 200)
        self.login_as(self.a)
        row = self.client.get("/api/journal/review").json()["records"][0]
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["payload"]["notes"], "private")

    def test_persistence_pagination_and_logout(self):
        uid = self.db.identity(self.a)["id"]
        for i in range(3):self.db.put(uid, "account", str(i), {"name": str(i)}, 0)
        reopened = CommercialStore(str(self.db.engine.url))
        try:self.assertEqual(len(reopened.records(uid, "account")["records"]), 3)
        finally:reopened.engine.dispose()
        self.login_as(self.a)
        first = self.client.get("/api/journal/account?limit=2").json()
        second = self.client.get("/api/journal/account?cursor="+first["next_cursor"]).json()
        self.assertEqual([r["id"] for r in first["records"]+second["records"]], ["0", "1", "2"])
        self.assertEqual(self.client.post("/api/auth/logout", headers={"x-csrf-token": self.ca}).status_code, 200)
        self.assertIsNone(self.db.identity(self.a))

    def test_simultaneous_identity_callbacks_share_account(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            logins = list(pool.map(lambda _: self.db.login("https://issuer/", "concurrent-user"), range(2)))
        self.assertEqual(self.db.identity(logins[0][0])["id"], self.db.identity(logins[1][0])["id"])

    def test_free_pro_expiry_and_disabled_billing(self):
        self.login_as(self.a)
        self.assertEqual([r["symbol"] for r in self.client.get("/api/market/radar").json()["markets"]], ["XAUUSD"])
        self.assertEqual([r["symbol"] for r in self.client.get("/api/market/opportunities").json()["opportunities"]], ["XAUUSD"])
        self.assertEqual(self.client.get("/api/market/chart?symbol=BTCUSD").status_code, 403)
        self.assertEqual(self.client.get("/api/market/chart").json()["candles"], [])
        self.assertEqual(self.client.get("/api/journal/export").status_code, 403)
        uid = self.db.identity(self.a)["id"]
        with self.db.engine.begin() as c:c.execute(insert(entitlements).values(user_id=uid, plan="pro", expires_at=int(time.time())+60))
        self.assertEqual(len(self.client.get("/api/market/radar").json()["markets"]), 2)
        self.assertEqual(self.client.get("/api/journal/export").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json()["entitlements"]["price_usd"], 19)
        self.assertEqual(self.client.post("/api/billing/checkout", headers={"x-csrf-token": self.ca}).status_code, 503)
        with patch.object(commercial.time, "time", return_value=time.time()+120):
            self.assertEqual(self.db.identity(self.a)["plan"], "free")

    def test_migration_compiles_for_postgresql_and_is_idempotent(self):
        from sqlalchemy.schema import CreateTable
        from sqlalchemy.dialects.postgresql import dialect
        self.db.migrate()
        ddl = str(CreateTable(journal).compile(dialect=dialect()))
        self.assertIn("PRIMARY KEY (user_id, kind, record_id)", ddl)
        self.assertIn("FOREIGN KEY(user_id)", ddl)

    def test_oidc_code_flow_pkce_state_and_secure_session_cookie(self):
        client = self.app.state.oidc.create_client("identity")
        provider = {"issuer":"https://identity.test/", "authorization_endpoint":"https://identity.test/authorize",
                    "token_endpoint":"https://identity.test/token", "id_token_signing_alg_values_supported":["RS256"]}
        with patch.object(client,"load_server_metadata",AsyncMock(return_value=provider)):
            response = self.client.get("/api/auth/login",follow_redirects=False)
            query = parse_qs(urlsplit(response.headers["location"]).query)
            self.assertEqual(query["code_challenge_method"],["S256"])
            self.assertTrue(query["nonce"])
            self.assertTrue(query["state"])
            bad = self.client.get("/api/auth/callback?state=forged&code=bad",follow_redirects=False)
            self.assertEqual(bad.status_code,401)
            key=RSAKey.generate_key(2048,private=True);key.ensure_kid()
            claims={"iss":"https://identity.test/","aud":"client","sub":"signed-in-user","exp":int(time.time())+300,
                    "iat":int(time.time()),"nonce":query["nonce"][0]}
            encoded=jwt.encode({"alg":"RS256","kid":key.kid},claims,key)
            with patch.object(client,"fetch_access_token",AsyncMock(return_value={"id_token":encoded,"access_token":"offline"})), \
                 patch.object(client,"fetch_jwk_set",AsyncMock(return_value={"keys":[key.as_dict(private=False)]})):
                good=self.client.get("/api/auth/callback?state="+query["state"][0]+"&code=offline",follow_redirects=False)
            self.assertEqual(good.status_code,303)
            cookies=good.headers.get_list("set-cookie")
            cookie=next(c for c in cookies if c.startswith(commercial.COOKIE+"="))
            for flag in ("HttpOnly","Secure","SameSite=lax"):self.assertIn(flag,cookie)
            self.assertEqual(self.client.get("/api/auth/me").status_code,200)

    def test_scope_excludes_old_records_and_global_executed_trades(self):
        old = {"record_type": "setup_snapshot", "setup_id": "s", "symbol": "XAUUSD", "observed_at": "2000-01-01T00:00:00+00:00"}
        self.assertEqual(commercial.scope_payload([old], {"plan": "free"}), [])
        self.assertNotIn("trade_outcomes", commercial.scope_payload({"symbol": "XAUUSD", "trade_outcomes": [{"private": True}]}, {"plan": "pro"}))
        self.login_as(self.a)
        self.assertEqual(self.client.post("/api/market/setups/s/lifecycle",json={}).status_code, 403)


class OIDCValidationTests(unittest.TestCase):
    def test_oidc_signature_issuer_audience_expiry_and_nonce(self):
        key = RSAKey.generate_key(2048, private=True)
        key.ensure_kid()
        oauth = OAuth()
        oauth.register("test",client_id="client",client_secret="unused",issuer="https://identity.test/",
                       jwks={"keys": [key.as_dict(private=False)]},id_token_signing_alg_values_supported=["RS256"])
        client = oauth.create_client("test")
        now = int(time.time())
        claims = {"iss":"https://identity.test/","aud":"client","sub":"alice","exp":now+300,"iat":now,"nonce":"nonce"}
        async def parse(values, signing_key=key):
            encoded = jwt.encode({"alg":"RS256","kid":key.kid},values,signing_key)
            return await client.parse_id_token({"id_token":encoded},nonce="nonce",leeway=0)
        self.assertEqual(asyncio.run(parse(claims))["sub"], "alice")
        for field, value in (("iss","https://evil.test/"),("aud","other"),("exp",now-1),("nonce","other")):
            with self.subTest(field=field),self.assertRaises(Exception):asyncio.run(parse({**claims,field:value}))
        with self.assertRaises(Exception):asyncio.run(parse(claims,RSAKey.generate_key(2048,private=True)))


class PlanningTests(unittest.TestCase):
    def test_conservative_precision_across_all_four_strategies_and_symbols(self):
        for strategy in ("trendline_v5","support_resistance","smc","trend_momentum"):
            for tick, scale in ((0.00001,1.0),(0.001,150.0),(0.01,2600.0),(0.25,20000.0)):
                for direction in ("LONG","SHORT"):
                    long = direction=="LONG"
                    stop,target=(scale-3.13*tick,scale+8.17*tick) if long else (scale+3.13*tick,scale-8.17*tick)
                    market={"strategy_id":strategy,"direction":direction,"entry":scale,"stop_loss":stop,"take_profit":target,
                            "bid":scale,"ask":scale+tick,"tick_size":tick,"score_breakdown":{"pattern":70,"risk_reward":10}}
                    result=apply_plan(market)
                    self.assertLessEqual(result["stop_loss"],stop) if long else self.assertGreaterEqual(result["stop_loss"],stop)
                    self.assertLessEqual(result["take_profit"],target) if long else self.assertGreaterEqual(result["take_profit"],target)
                    self.assertEqual(result["pattern_strength"],70)
                    self.assertAlmostEqual(result["stop_loss"]/tick,round(result["stop_loss"]/tick),places=6)

    def test_structure_cap_never_invents_a_target_or_tightens_a_stop(self):
        market={"strategy_id":"trend_momentum","direction":"LONG","entry":100,"stop_loss":90,"take_profit":140,"bid":100,"ask":101}
        bars={"H1":[{"high":h,"low":h-5} for h in [102,105,110,105,102,100]]}
        result=apply_plan(market,bars)
        self.assertEqual(result["take_profit"],110)
        self.assertEqual(result["stop_loss"],90)
        self.assertEqual(result["plan_evidence"]["pattern_plan"]["take_profit"],140)
        self.assertFalse(qualify({**result,"tick_age_seconds":0})["qualified"])
        market["take_profit"]=None
        self.assertIsNone(apply_plan(market,bars)["take_profit"])

    def test_net_cost_gate_threshold_and_observation_visibility(self):
        market={"strategy_valid":True,"direction":"LONG","entry":100,"stop_loss":90,"take_profit":115,"bid":100,"ask":100,"tick_age_seconds":0}
        self.assertTrue(qualify(market)["qualified"])
        self.assertFalse(qualify({**market,"round_trip_cost_price":1})["qualified"])
        self.assertFalse(qualify({**market,"round_trip_cost_price":"invalid"})["qualified"])
        with patch.dict(os.environ,{"TRADING_HUB_MIN_NET_RR":"2"}):self.assertFalse(qualify(market)["qualified"])
        result=apply({**market,"take_profit":105})
        self.assertEqual(result["take_profit"],105)
        self.assertFalse(result["strategy_valid"])
        self.assertTrue(result["strategy_signal_valid"])

    def test_pattern_confirmation_and_broker_costs_are_separate(self):
        row={"strategy_id":"smc","symbol":"XAUUSD","state":"CONFIRMING","direction":"LONG","entry":100,
             "stop_loss":90,"take_profit":105,"bid":100,"ask":101,"tick_age_seconds":0,
             "strategy_valid":False,"strategy_evidence":{"confirmation":{"rules":{"reaction":True,"min_rr":False}}}}
        with patch.dict(os.environ,{"TRADING_HUB_COSTS_BY_SYMBOL":'{"XAUUSD":0.5}'}):result=apply(apply_plan(row))
        self.assertTrue(result["pattern_confirmed"])
        self.assertFalse(result["trade_qualified"])
        self.assertEqual(result["qualification"]["additional_cost_price"],0.5)

    def test_chart_time_normalization_sorting_and_no_unverified_candles(self):
        rows=[{"time":100000+i*900,"open":1,"high":2,"low":0.5,"close":1.5} for i in (2,0,1,1)]
        self.assertEqual([r["time"] for r in normalize_candles(rows,"UTC")],[100000,100900,101800])
        self.assertEqual(normalize_candles(rows,None),[])
        self.assertEqual(normalize_candles([{**rows[0], "high": float("nan")}, {**rows[0], "low": 3}], "UTC"), [])
