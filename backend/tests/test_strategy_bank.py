"""Strategy Bank: specifications, causality (no repainting), gates, dedupe, Telegram, outcomes, stats, flags."""
from __future__ import annotations

import inspect
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from strategy_bank import engine, rules
from strategy_bank import telegram as bank_telegram
from strategy_bank import worker

START = 1_700_000_000 - 1_700_000_000 % 86400
TF = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def frames(days=150, seed=4, vol=0.0015):
    """Random-walk M15 bars (UTC midnight start) aggregated into H1/H4/D1, with spread."""
    rng = random.Random(seed)
    m15, price = [], 1.2
    for k in range(days * 96):
        o = price
        c = o + rng.gauss(0, vol)
        m15.append({"utc": START + 900 * k, "open": o, "close": c, "high": max(o, c) + abs(rng.gauss(0, vol / 2)),
                    "low": min(o, c) - abs(rng.gauss(0, vol / 2)), "tick_volume": rng.randint(50, 500), "spread": 0.00005})
        price = c
    out = {"M15": m15}
    for tf, s in TF.items():
        if tf == "M15":
            continue
        groups = {}
        for b in m15:
            groups.setdefault(b["utc"] - (b["utc"] - START) % s, []).append(b)
        out[tf] = [{"utc": t, "open": g[0]["open"], "close": g[-1]["close"], "high": max(b["high"] for b in g),
                    "low": min(b["low"] for b in g), "tick_volume": sum(b["tick_volume"] for b in g), "spread": 0.00005}
                   for t, g in sorted(groups.items())]
    return out


def truncated(fr, close_t):
    """Only bars CLOSED by close_t (what the live scanner would have)."""
    return {tf: [b for b in bars if b["utc"] + TF[tf] <= close_t] for tf, bars in fr.items()}


class SpecTests(unittest.TestCase):
    def test_twenty_objective_specifications(self):
        self.assertEqual([s["n"] for s in rules.SPECS], list(range(1, 21)))
        for s in rules.SPECS:
            for field in ("name", "status", "timeframe", "entry", "indicators", "confirmation", "stop", "take_profit",
                          "invalidation", "data", "instruments"):
                self.assertIn(field, s, f"#{s['n']} lacks {field}")
            if s["status"] == rules.EXPERIMENTAL:
                self.assertTrue(callable(s["decide"]))
                self.assertIsNotNone(s["min_rr"])
                self.assertTrue(s["instruments"])
        self.assertEqual([s["n"] for s in rules.SPECS if s["status"] == rules.LINKED], [1, 2, 3])
        vwap = rules.BY_KEY["vwap_reversion"]
        self.assertEqual(vwap["status"], rules.UNSUPPORTED)
        self.assertIn("tick_volume", vwap["unsupported_reason"])
        self.assertEqual(len(rules.scanned()), 16)
        vague = ("strong", "significant momentum", "looks", "clearly")
        for s in rules.scanned():
            self.assertFalse(any(w in s["entry"].lower() for w in vague), f"#{s['n']} entry rule is vague")


class CausalityTests(unittest.TestCase):
    def test_no_strategy_repaints_or_looks_ahead(self):
        fr = frames(days=150)
        full = rules.Ctx("EURUSD", fr)
        checked = 0
        for spec in rules.scanned():
            tf = spec["timeframe"]
            n = len(full.a[tf]["close"])
            fired = [i for i in range(300, n) if spec["decide"](full, i)]
            sample = fired[:4] + list(range(300, n, max(1, (n - 300) // 6)))
            for i in sample:
                close_t = full.close_utc(tf, i)
                part = rules.Ctx("EURUSD", truncated(fr, close_t))
                j = len(part.a[tf]["close"]) - 1
                self.assertEqual(part.close_utc(tf, j), close_t)
                a, b = spec["decide"](full, i), spec["decide"](part, j)
                self.assertEqual(a is None, b is None, f"{spec['key']} differs at bar {i} with future data present")
                if a is not None:
                    self.assertEqual((a.direction, a.stop_atr, a.target_r), (b.direction, b.stop_atr, b.target_r))
                    for x, y in ((a.stop, b.stop), (a.target, b.target)):
                        if x is not None:
                            self.assertAlmostEqual(x, y, places=7, msg=spec["key"])
                checked += 1
        self.assertGreater(checked, 100)

    def test_strategies_trigger_on_history(self):
        fr = frames(days=150, seed=9, vol=0.002)
        ctx = rules.Ctx("EURUSD", fr)
        silent = []
        for spec in rules.scanned():
            if "EURUSD" not in spec["instruments"]:
                continue
            tf = spec["timeframe"]
            if not any(spec["decide"](ctx, i) for i in range(300, len(ctx.a[tf]["close"]))):
                silent.append(spec["key"])
        self.assertLessEqual(len(silent), 2, f"strategies never triggering on 150 days of data: {silent}")


def bars_from(closes, start=START, tf=3600, wick=0.0005):
    return [{"utc": start + tf * k, "open": c, "high": c + wick, "low": c - wick, "close": c, "tick_volume": 100}
            for k, c in enumerate(closes)]


class RuleFixtureTests(unittest.TestCase):
    def test_donchian_and_inside_bar(self):
        closes = [1.0 + 0.0001 * ((k % 7) - 3) for k in range(260)] + [1.01]
        ctx = rules.Ctx("EURUSD", {"H1": bars_from(closes)})
        d = rules.donchian(ctx, len(closes) - 1)
        self.assertEqual((d.direction, d.stop_atr), ("LONG", 2.0))
        h1 = bars_from([1.0] * 260)
        h1[-3].update(high=1.003, low=0.997)                      # mother
        h1[-2].update(high=1.002, low=0.998)                      # inside
        h1[-1].update(close=1.004, high=1.0045, open=1.0)         # break above the mother
        d = rules.inside_bar_breakout(rules.Ctx("EURUSD", {"H1": h1}), len(h1) - 1)
        self.assertEqual((d.direction, d.stop), ("LONG", 0.997))

    def test_liquidity_sweep_needs_close_back_inside(self):
        d1 = [{"utc": START + 86400 * k, "open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0, "tick_volume": 1} for k in range(3)]
        h1 = bars_from([1.0] * 72, start=START + 86400)
        h1[-1].update(open=1.0050, high=1.0150, low=1.0040, close=1.0055)   # sweep above 1.01, close back below
        ctx = rules.Ctx("EURUSD", {"H1": h1, "D1": d1})
        with mock.patch.object(ctx, "get", side_effect=lambda tf, name, *a: [0.008] * len(h1) if name == "atr" else rules.Ctx.get(ctx, tf, name, *a)):
            d = rules.liquidity_sweep(ctx, len(h1) - 1)
        self.assertEqual(d.direction, "SHORT")
        self.assertAlmostEqual(d.stop, 1.0150 + 0.2 * 0.008)
        h1[-1].update(close=1.0120)                                         # closes beyond: no sweep signal
        ctx2 = rules.Ctx("EURUSD", {"H1": h1, "D1": d1})
        with mock.patch.object(ctx2, "get", side_effect=lambda tf, name, *a: [0.008] * len(h1) if name == "atr" else rules.Ctx.get(ctx2, tf, name, *a)):
            self.assertIsNone(rules.liquidity_sweep(ctx2, len(h1) - 1))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.fr = frames(days=60)
        self.ctx = rules.Ctx("EURUSD", self.fr)
        self.i = len(self.ctx.a["H1"]["close"]) - 1
        self.atr = float(self.ctx.get("H1", "atr")[self.i])
        self.close = float(self.ctx.a["H1"]["close"][self.i])
        self.now = self.ctx.close_utc("H1", self.i) + 10
        self.spec = rules.BY_KEY["ema_crossover"]

    def quote(self, bid=None, spread=0.00005, age=5.0):
        bid = self.close if bid is None else bid
        return {"bid": bid, "ask": bid + spread, "tick_age_seconds": age}

    def test_valid_signal(self):
        s, reason = engine.confirm(self.spec, rules.Decision("LONG", stop_atr=1.5), self.ctx, self.i, self.quote(), self.now)
        self.assertEqual(reason, "")
        self.assertAlmostEqual(s["rr"], 2.0, places=3)
        self.assertLess(s["stop_loss"], s["entry"])
        self.assertEqual(s["r_basis"], "hypothetical (signal outcome, not an executed trade)")
        self.assertIn("contradictions", s)

    def test_each_gate(self):
        d = rules.Decision("LONG", stop_atr=1.5)
        cases = [(dict(now=self.now + 3 * 3600), "stale bar"), (dict(quote=self.quote(age=900)), "stale or unverified quote"),
                 (dict(quote=self.quote(bid=self.close + self.atr)), "entry moved"),
                 (dict(quote=self.quote(spread=0.45 * self.atr)), "spread above"),   # within drift, > 25% of 1.5 ATR risk
                 (dict(decision=rules.Decision("LONG", stop_atr=0.1)), "stop distance"),
                 (dict(decision=rules.Decision("LONG", stop_atr=1.5, target_r=1.0)), "below the 1.5 minimum"),
                 (dict(decision=rules.Decision("SHORT", stop=self.close - self.atr)), "stop distance")]
        for over, expected in cases:
            s, reason = engine.confirm(self.spec, over.get("decision", d), self.ctx, self.i, over.get("quote", self.quote()),
                                       over.get("now", self.now))
            self.assertIsNone(s)
            self.assertIn(expected, reason)


class BankFlowTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.store = engine.BankStore(Path(self._temp.name))

    def tearDown(self):
        self._temp.cleanup()

    def signal(self, key, symbol="EURUSD", direction="LONG", minutes=0, **over):
        spec = rules.BY_KEY[key]
        t = datetime(2026, 10, 20, 10, tzinfo=timezone.utc) + timedelta(minutes=minutes)
        return {"signal_id": f"bank_{key}_{minutes}", "strategy_key": key, "strategy_name": spec["name"], "strategy_number": spec["n"],
                "status": spec["status"], "symbol": symbol, "direction": direction, "timeframe": spec["timeframe"],
                "confirmed_at": t.isoformat(), "entry": 1.1000, "stop_loss": 1.0980, "take_profit": 1.1040, "risk": 0.002, "rr": 2.0,
                "explanation": "EMA20 crossed above EMA50 on the H1 close with price above EMA200.",
                "contradictions": ["the H4 trend is down (EMA50 below EMA200)", "RSI(14) is overbought at 74"], **over}

    def test_opportunity_merge_attribution_and_production_cover(self):
        bank = engine.Bank(self.store, production_confirmations=lambda: [
            {"symbol": "GBPUSD", "direction": "SHORT", "confirmed_at": "2026-10-20T09:40:00+00:00", "setup_id": "stp_prod"}])
        first, second = self.signal("ema_crossover"), self.signal("macd_momentum", minutes=60)
        for s in (first, second):
            bank._attach(s, 0)
            self.store.put_signal(s)
        self.assertEqual((first["alert"], second["alert"]), ("primary", "merged"))
        opp = self.store.opportunities[first["opportunity_id"]]
        self.assertEqual(opp["strategies"], ["EMA Crossover", "MACD Momentum"])
        self.assertEqual(len(opp["signal_ids"]), 2)
        other = self.signal("ema_crossover", minutes=600)                 # outside the window: a new opportunity
        bank._attach(other, 0)
        self.assertNotEqual(other["opportunity_id"], first["opportunity_id"])
        covered = self.signal("donchian", symbol="GBPUSD", direction="SHORT")
        bank._attach(covered, 0)
        self.assertEqual(covered["alert"], "covered by a production alert")

    def test_duplicate_while_open(self):
        self.store.put_signal(self.signal("ema_crossover"))
        self.assertIsNotNone(self.store.open_signal("ema_crossover", "EURUSD"))
        self.store.put_signal({**self.signal("ema_crossover"), "outcome_status": "STOP_HIT"})
        self.assertIsNone(self.store.open_signal("ema_crossover", "EURUSD"))
        reloaded = engine.BankStore(Path(self._temp.name))
        self.assertEqual(reloaded.signals["bank_ema_crossover_0"]["outcome_status"], "STOP_HIT")

    def test_telegram_message_and_delivery(self):
        s = self.signal("ema_crossover", alert="primary", opportunity_id="opp_1")
        text = bank_telegram.message(s)
        lines = text.splitlines()
        self.assertEqual(lines[:3], ["📊 <b>EURUSD</b> | 🟢 <b>BUY</b>", "📈 Strategy: EMA Crossover", "⏱ Timeframe: H1"])
        for expected in ("➡️ Entry: <b>1.1</b>", "🛑 Stop Loss: <b>", "🎯 Take Profit: <b>", "⚖️ Risk/Reward: 1:2.00",
                         "🕒 Confirmed:", "💡 <b>Trade rationale:</b>", "⚖️ <b>Contradicting evidence:</b>", "The H4 trend is down",
                         bank_telegram.DISCLAIMER):
            self.assertIn(expected, text)
        self.assertEqual(lines[-1], "⚠️ Experimental signal. This strategy has not demonstrated reliable profitability. Trading involves risk.")
        # No contradicting evidence recorded: the section is left out entirely.
        clean = bank_telegram.message({**s, "contradictions": []})
        self.assertNotIn("Contradicting", clean)
        self.assertIn("💡 <b>Trade rationale:</b>", clean)
        for hidden in ("bank_", "opp_", "ema_crossover", "version"):
            self.assertNotIn(hidden, text)

        class Client:
            def __init__(self):
                self.sent = []

            def send_message(self, chat_id, text, parse_mode=None):
                self.sent.append((text, parse_mode))
                return {"message_id": len(self.sent)}

        now = datetime.fromisoformat(s["confirmed_at"]).timestamp() + 30
        self.store.put_signal(s)
        self.store.put_signal(self.signal("macd_momentum", minutes=5, alert="merged", opportunity_id="opp_1"))
        self.store.put_signal(self.signal("donchian", minutes=-60, alert="primary", opportunity_id="opp_old"))
        client = Client()
        alerts = bank_telegram.BankAlerts(client, "1", self.store, clock=lambda: now)
        self.assertEqual(alerts.deliver(), 1)
        self.assertEqual(alerts.deliver(), 0)                       # never twice
        self.assertEqual(client.sent[0][1], "HTML")
        self.assertTrue((Path(self._temp.name) / "telegram_notifications.jsonl").exists())
        self.assertEqual(alerts.sent.get("bank:opp_old")["status"], "expired")   # too old: never sent late


class RestartReplayTests(unittest.TestCase):
    """T-034: starting (or restarting) the bank never replays recorded signals as alerts."""

    def test_restart_after_downtime_sends_nothing_old_and_never_repeats(self):
        with tempfile.TemporaryDirectory() as temp:
            store = engine.BankStore(Path(temp))
            t0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
            for k in range(5):                                       # recorded before the downtime
                store.put_signal({"signal_id": f"bank_old_{k}", "strategy_key": "ema_crossover", "strategy_name": "EMA Crossover",
                                  "symbol": "EURUSD", "direction": "LONG", "timeframe": "H1", "alert": "primary",
                                  "opportunity_id": f"opp_old_{k}", "confirmed_at": (t0 - timedelta(hours=k + 1)).isoformat(),
                                  "entry": 1.1, "stop_loss": 1.098, "take_profit": 1.104, "rr": 2.0, "explanation": "x"})
            sent = []

            class Client:
                def send_message(self, chat_id, text, parse_mode=None):
                    sent.append(text)
                    return {"message_id": len(sent)}

            restarted = engine.BankStore(Path(temp))                 # engine restart: store reloaded from disk
            alerts = bank_telegram.BankAlerts(Client(), "1", restarted, clock=lambda: t0.timestamp())
            self.assertEqual(alerts.deliver(), 0)
            self.assertEqual(sent, [])
            self.assertEqual({alerts.sent.get(f"bank:opp_old_{k}")["status"] for k in range(5)}, {"expired"})
            # A fresh signal is sent once, and a second restart does not send it again.
            restarted.put_signal({**restarted.signals["bank_old_0"], "signal_id": "bank_new", "opportunity_id": "opp_new",
                                  "confirmed_at": (t0 - timedelta(seconds=20)).isoformat()})
            self.assertEqual(alerts.deliver(), 1)
            again = bank_telegram.BankAlerts(Client(), "1", engine.BankStore(Path(temp)), clock=lambda: t0.timestamp() + 30)
            self.assertEqual(again.deliver(), 0)
            self.assertEqual(len(sent), 1)


class OutcomeAndStatsTests(unittest.TestCase):
    def test_time_exit_and_first_barrier(self):
        t0 = datetime(2026, 10, 20, 8, 7, tzinfo=timezone.utc)
        base = t0.timestamp() - t0.timestamp() % 900
        m15 = [{"utc": base + 900 * k, "open": 1.1, "high": 1.1005, "low": 1.0995, "close": 1.1002, "spread": 0.0} for k in range(40)]
        s = {"direction": "LONG", "entry": 1.1, "stop_loss": 1.098, "take_profit": 1.104, "risk": 0.002,
             "confirmed_at": t0.isoformat(), "time_exit_at": (t0 + timedelta(hours=3)).isoformat()}
        r = engine.resolve_signal(s, m15, None, t0 + timedelta(hours=8))
        self.assertEqual(r["status"], "TIME_EXIT")
        self.assertAlmostEqual(r["r_multiple"], 0.1, places=4)
        m15[5].update(high=1.105)
        self.assertEqual(engine.resolve_signal(s, m15, None, t0 + timedelta(hours=8))["status"], "TARGET_HIT")

    def test_statistics_show_pending_until_outcomes_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            store = engine.BankStore(Path(temp))
            stats = {row["key"]: row for row in engine.statistics(store)}
            self.assertEqual(len(stats), 20)
            self.assertEqual((stats["ema_pullback"]["signals"], stats["ema_pullback"]["win_rate"], stats["ema_pullback"]["expectancy_r"]), (0, None, None))
            for k, (status, r) in enumerate((("TARGET_HIT", 2.0), ("STOP_HIT", -1.0), ("STOP_HIT", -1.0), (None, None))):
                store.put_signal({"signal_id": f"s{k}", "strategy_key": "ema_pullback", "symbol": "EURUSD", "timeframe": "H1",
                                  "confirmed_at": f"2026-10-2{k}T10:00:00+00:00", "outcome_status": status, "r_multiple": r,
                                  "outcome_at": f"2026-10-2{k}T12:00:00+00:00"})
            row = {r["key"]: r for r in engine.statistics(store)}["ema_pullback"]
            self.assertEqual((row["signals"], row["resolved"], row["open"]), (4, 3, 1))
            self.assertAlmostEqual(row["win_rate"], 1 / 3, places=3)
            self.assertAlmostEqual(row["expectancy_r"], 0.0)
            self.assertEqual(row["max_drawdown_r"], 2.0)
            self.assertEqual(row["by_instrument"]["EURUSD"]["signals"], 4)


class IsolationTests(unittest.TestCase):
    def test_flags_default_off_and_live_code_untouched(self):
        import os
        for env in (worker.ENABLED_ENV, bank_telegram.ENABLED_ENV):
            self.assertNotEqual(os.getenv(env, ""), "1")
        self.assertFalse(worker.enabled())
        self.assertFalse(bank_telegram.enabled())
        import main
        source = inspect.getsource(main.lifespan)
        self.assertIn("bank_worker.enabled()", source)
        import telegram_notifier
        self.assertNotIn("strategy_bank", inspect.getsource(telegram_notifier))
        from strategies import REGISTRY
        self.assertFalse(set(REGISTRY.enabled()) & {s["key"] for s in rules.SPECS if s["status"] != rules.LINKED})

    def test_api_returns_twenty_rows_and_labels_history(self):
        import main
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(engine, "bank_dir", lambda: Path(temp)), \
                mock.patch.object(engine, "linked_production_rows", lambda: {}):
            payload = main.strategy_bank()
        self.assertEqual(len(payload["strategies"]), 20)
        self.assertEqual(len(payload["rules"]), 20)
        self.assertIn("not live", payload["historical"]["label"])
        self.assertTrue(all(row["win_rate"] is None for row in payload["strategies"]))


if __name__ == "__main__":
    unittest.main()
