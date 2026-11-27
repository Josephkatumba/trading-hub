// Offline tests of the cBot's execution safeguards (ExecutionGate, ForwardRules, Sizing).
// Compiled together with TradeDenScalper.cs by tests/test_safety.py; exit code = number of failures.
using System;
using System.Collections.Generic;
using cAlgo.Robots;

public static class SafetyTests
{
    static int _fail, _pass;

    static void Check(string name, bool ok)
    {
        if (ok) { _pass++; } else { _fail++; Console.WriteLine("FAIL " + name); }
    }

    static GateInput Good()
    {
        return new GateInput { IsLive = false, AccountNumber = 1234567, ExpectedAccount = 1234567, Broker = "IC Markets (EU) Ltd",
            ExpectedBroker = "IC Markets", Symbol = "XAUUSD", DemoTradingRequested = true, ActivationCode = "fwd-xau-001", ExperimentApproved = true };
    }

    static RiskInput OkRisk()
    {
        return new RiskInput { DayStartBalance = 10000, RealizedToday = 0, OpenRisk = 0, NewRisk = 25, DailyLossPercent = 1.0,
            OwnPositions = 0, MaxPositions = 1, ForeignPositionsOnSymbol = 0, ConsecutiveLosses = 0, MaxConsecutiveLosses = 2 };
    }

    public static int Main()
    {
        // ---------------- execution gate
        Check("gate allows the fully configured demo experiment", ExecutionGate.Evaluate(Good()) == null);
        GateInput g;
        g = Good(); g.IsLive = true; Check("live account refused", ExecutionGate.Evaluate(g) != null && ExecutionGate.Evaluate(g).Contains("LIVE"));
        g = Good(); g.IsLive = true; g.DemoTradingRequested = true; g.ActivationCode = "fwd-xau-001";
        Check("live refused even with every other condition met", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.DemoTradingRequested = false; Check("SignalsOnly mode sends no orders", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.ExperimentApproved = false; Check("unapproved experiment refused", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.ActivationCode = ""; Check("missing activation code refused", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.ActivationCode = "FWD-XAU-001"; Check("activation code is exact", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.ExpectedAccount = 0; Check("expected account required", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.AccountNumber = 7654321; Check("wrong account refused", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.Broker = "Some Other Broker"; Check("wrong broker refused", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.ExpectedBroker = ""; Check("blank expected broker refused", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.Broker = "ICMarkets"; Check("broker match ignores spaces and case", ExecutionGate.Evaluate(g) == null);
        g = Good(); g.Symbol = "BTCUSD"; Check("non-XAUUSD symbol refused", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.Symbol = "xauusd"; Check("symbol match is case-insensitive", ExecutionGate.Evaluate(g) == null);
        Check("null input refused", ExecutionGate.Evaluate(null) != null);

        // ---------------- risk rules
        RiskInput r;
        Check("clean state allows a trade", ForwardRules.RiskCheck(OkRisk()) == null);
        r = OkRisk(); r.OwnPositions = 1; Check("max one open position", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.OwnPositions = 1; r.MaxPositions = 5; Check("position ceiling cannot be raised by parameter", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.ForeignPositionsOnSymbol = 1; Check("manual position on symbol blocks", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.ConsecutiveLosses = 2; Check("halt after two consecutive losses", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.ConsecutiveLosses = 2; r.MaxConsecutiveLosses = 10; Check("loss-streak ceiling cannot be raised", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.ConsecutiveLosses = 1; Check("one loss does not halt", ForwardRules.RiskCheck(r) == null);
        r = OkRisk(); r.RealizedToday = -100; Check("daily loss 1% reached blocks", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.RealizedToday = -80; r.NewRisk = 25; Check("daily budget counts the new trade's risk", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.RealizedToday = -50; r.OpenRisk = 30; r.NewRisk = 25; Check("daily budget counts open risk", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.RealizedToday = -50; r.NewRisk = 25; Check("within budget allowed", ForwardRules.RiskCheck(r) == null);
        r = OkRisk(); r.DailyLossPercent = 3.0; r.RealizedToday = -150; Check("daily ceiling cannot be raised to 3%", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.KillSwitchToday = true; Check("kill switch blocks for the day", ForwardRules.RiskCheck(r) != null);
        r = OkRisk(); r.NewRisk = 0; Check("zero/invalid risk refused", ForwardRules.RiskCheck(r) != null);

        // ---------------- loss streak counting
        Check("streak counts trailing losses", ForwardRules.ConsecutiveLosses(new List<double> { 5, -1, -2 }) == 2);
        Check("a win resets the streak", ForwardRules.ConsecutiveLosses(new List<double> { -1, -2, 3 }) == 0);
        Check("empty history has no streak", ForwardRules.ConsecutiveLosses(new List<double>()) == 0);
        Check("breakeven (0) is not a loss", ForwardRules.ConsecutiveLosses(new List<double> { -1, 0 }) == 0);

        // ---------------- sizing (XAUUSD-like: pip 0.01, pip value 0.01 USD per unit(oz), min 1 oz, step 1 oz)
        SizeResult s = Sizing.Compute(10000, 0.25, 4.237, 0.01, 0.01, 1, 1, 10000);
        Check("risk budget is 0.25% of balance", Math.Abs(s.RiskBudget - 25.0) < 1e-9);
        Check("stop rounded UP to 0.1 pip", Math.Abs(s.StopPips - 423.7) < 1e-9 && s.StopPips * 0.01 >= 4.237 - 1e-12);
        Check("cash risk never exceeds budget", s.CashRisk <= s.RiskBudget + 1e-9 && s.Units >= 1);
        Check("units are whole volume steps", Math.Abs(s.Units - Math.Round(s.Units)) < 1e-9);
        SizeResult capped = Sizing.Compute(10000, 5.0, 4.237, 0.01, 0.01, 1, 1, 10000);
        Check("risk % above 0.25 is clamped", Math.Abs(capped.RiskBudget - 25.0) < 1e-9 && capped.Units == s.Units);
        SizeResult tiny = Sizing.Compute(300, 0.25, 4.0, 0.01, 0.01, 1, 1, 10000);
        Check("trade skipped when minimum volume exceeds budget", tiny.Units == 0);
        SizeResult afterLosses = Sizing.Compute(9900, 0.25, 4.237, 0.01, 0.01, 1, 1, 10000);
        Check("no martingale: size after losses is not larger", afterLosses.Units <= s.Units);
        Check("invalid stop gives zero size", Sizing.Compute(10000, 0.25, 0, 0.01, 0.01, 1, 1, 10000).Units == 0);
        Check("negative stop gives zero size", Sizing.Compute(10000, 0.25, -1, 0.01, 0.01, 1, 1, 10000).Units == 0);
        Check("volume max respected", Sizing.Compute(1e9, 0.25, 0.05, 0.01, 0.01, 1, 1, 500).Units == 500);
        // ---------------- the owner's demo 10141056 (2026-11-23): balance 944.81, equity 1529.75, XAUUSD min 1 oz
        double riskBase = Math.Min(944.81, 1529.75);
        Check("risk base uses the lower of balance and equity", riskBase == 944.81);
        SizeResult typical = Sizing.Compute(riskBase, 0.25, 7.27, 0.01, 0.01, 1, 1, 100000);
        Check("median $7.27 stop is skipped on the $944.81 account", typical.Units == 0 && Math.Abs(typical.RiskBudget - 2.362025) < 1e-6);
        SizeResult tight = Sizing.Compute(riskBase, 0.25, 2.20, 0.01, 0.01, 1, 1, 100000);
        Check("$2.20 stop trades 1 oz risking $2.20", tight.Units == 1 && Math.Abs(tight.CashRisk - 2.20) < 1e-9);
        Check("$2.36 stop still fits the $2.36 budget", Sizing.Compute(riskBase, 0.25, 2.36, 0.01, 0.01, 1, 1, 100000).Units == 1);
        Check("$2.37 stop is skipped", Sizing.Compute(riskBase, 0.25, 2.37, 0.01, 0.01, 1, 1, 100000).Units == 0);
        g = Good(); g.Broker = "Raw Trading Ltd"; g.ExpectedBroker = "Raw Trading";
        Check("IC Markets SC entity name matches 'Raw Trading'", ExecutionGate.Evaluate(g) == null);
        g = Good(); g.Broker = "Raw Trading Ltd"; g.ExpectedBroker = "IC Markets";
        Check("broker text must really match (fails safe to SignalsOnly)", ExecutionGate.Evaluate(g) != null);

        // randomized invariant: budget never exceeded
        var rng = new Random(7);
        bool allOk = true;
        for (int i = 0; i < 20000; i++)
        {
            double bal = 100 + rng.NextDouble() * 200000, stop = 0.01 + rng.NextDouble() * 40, step = rng.Next(2) == 0 ? 1 : 0.01;
            SizeResult z = Sizing.Compute(bal, rng.NextDouble() * 2, stop, 0.01, 0.01, step, step, 1e9);
            if (z.Units > 0 && (z.CashRisk > z.RiskBudget + 1e-6 || z.RiskBudget > bal * 0.0025 + 1e-9 || z.StopPips * 0.01 < stop - 1e-9)) allOk = false;
        }
        Check("20,000 random sizings never exceed 0.25% risk and never shrink the stop", allOk);

        // ---------------- EXECUTION_TEST planning (account 10141056 after manual positions closed: 1514.48)
        Func<TestInput> ti = () => new TestInput { GateReason = null, AlreadyExecuted = false, ConflictingPositions = 0, TradingEnabled = true,
            SessionBlocked = false, RiskBase = 1514.48, RiskPercent = 0.25, Atr = 4.3, Spread = 0.10, Bid = 3640.00, Ask = 3640.10,
            MinVolume = 1, PipSize = 0.01, PipValue = 0.01, CommissionRate = 3e-5 };
        TestPlan tp = ExecutionTest.Plan(ti());
        Check("test plan allowed on a clean demo account", tp.Reason == null);
        Check("test max loss incl. commission within 0.25% budget", tp.MaxLoss <= tp.Budget && Math.Abs(tp.Budget - 3.7862) < 1e-3);
        Check("test stop shrinks below ATR to fit the budget", tp.StopDistance < 4.3 && tp.StopDistance > 3 * 0.10);
        Check("test take-profit equals stop distance", tp.TpPips == tp.StopPips);
        TestInput x;
        x = ti(); x.GateReason = "LIVE account: order execution is prohibited"; Check("test refused when gate fails (live)", ExecutionTest.Plan(x).Reason != null);
        x = ti(); x.AlreadyExecuted = true; Check("test is one-shot", ExecutionTest.Plan(x).Reason != null);
        x = ti(); x.ConflictingPositions = 1; Check("test refused with a bot or XAUUSD position open", ExecutionTest.Plan(x).Reason != null);
        x = ti(); x.SessionBlocked = true; Check("test refused in rollover/weekend", ExecutionTest.Plan(x).Reason != null);
        x = ti(); x.Spread = 2.0; Check("test refused when spread is abnormal", ExecutionTest.Plan(x).Reason != null);
        x = ti(); x.RiskBase = 300; x.Spread = 0.2; Check("test refused when minimum volume cannot fit the budget", ExecutionTest.Plan(x).Reason != null);
        x = ti(); x.RiskPercent = 5; Check("test risk % is clamped to 0.25", Math.Abs(ExecutionTest.Plan(x).Budget - 3.7862) < 1e-3);
        x = ti(); x.MinVolume = 0; Check("test refused without a valid minimum volume", ExecutionTest.Plan(x).Reason != null);
        bool testInv = true;
        var rng2 = new Random(11);
        for (int i = 0; i < 20000; i++)
        {
            x = ti(); x.RiskBase = 200 + rng2.NextDouble() * 50000; x.Atr = 0.5 + rng2.NextDouble() * 15; x.Spread = 0.02 + rng2.NextDouble() * 0.5;
            TestPlan z = ExecutionTest.Plan(x);
            if (z.Reason == null && (z.MaxLoss > z.Budget + 1e-9 || z.Budget > x.RiskBase * 0.0025 + 1e-9 || z.StopDistance <= 0)) testInv = false;
        }
        Check("20,000 random test plans never exceed 0.25% worst-case loss", testInv);

        // ---------------- TradeDen copy mode (fwd-tdn-001)
        Func<GateInput> cg = () => { GateInput q = Good(); q.Experiment = ExecutionGate.CopyExperiment; q.ActivationCode = "fwd-tdn-001"; q.Symbol = "EURUSD"; return q; };
        Check("copy gate allows any TradeDen symbol with the copy code", ExecutionGate.Evaluate(cg()) == null);
        g = cg(); g.ActivationCode = "fwd-xau-001"; Check("copy needs its own activation code", ExecutionGate.Evaluate(g) != null);
        g = Good(); g.ActivationCode = "fwd-tdn-001"; Check("xau experiment refuses the copy code", ExecutionGate.Evaluate(g) != null);
        g = cg(); g.IsLive = true; Check("copy refused on a live account", ExecutionGate.Evaluate(g) != null);
        g = cg(); g.AccountNumber = 99; Check("copy refused on another account", ExecutionGate.Evaluate(g) != null);
        g = cg(); g.DemoTradingRequested = false; Check("copy refused in SignalsOnly", ExecutionGate.Evaluate(g) != null);
        g = cg(); g.Experiment = "other"; Check("unknown experiment refused", ExecutionGate.Evaluate(g) != null);

        string js = "{\"signal_id\": \"bank:bank_1\", \"source\": \"bank\", \"strategy\": \"liquidity_sweep\", \"symbol\": \"eurusd\", \"side\": \"sell\", \"entry\": 1.08900, \"stop\": 1.09100, \"target\": 1.08500, \"timeframe\": \"H1\", \"confirmed_at\": \"2026-11-23T20:00:00Z\", \"time_exit_at\": \"\", \"bridged_at\": \"2026-11-23T20:00:03Z\"}";
        CopySignal cs = CopySignal.Parse(js);
        Check("bridge line parses", cs != null && cs.Side == -1 && cs.Symbol == "EURUSD" && Math.Abs(cs.Stop - 1.091) < 1e-12 && cs.Source == "bank");
        Check("garbage line rejected", CopySignal.Parse("{\"foo\": 1}") == null);
        DateTime t0 = new DateTime(2026, 11, 23, 20, 1, 0, DateTimeKind.Utc);
        CopyCheck cc = CopyRules.Validate(cs, t0, 180, 1.08895, 1.08897, 0.00002, 3e-5, 0.25);
        Check("fresh valid copy signal passes", cc.Reason == null && Math.Abs(cc.StopDistance - 0.00205) < 1e-9);
        Check("too old copy signal refused", CopyRules.Validate(cs, t0.AddMinutes(5), 180, 1.08895, 1.08897, 0.00002, 3e-5, 0.25).Reason != null);
        Check("price beyond stop refused", CopyRules.Validate(cs, t0, 180, 1.0912, 1.0913, 0.0001, 3e-5, 0.25).Reason != null);
        Check("price drift > 0.25R refused", CopyRules.Validate(cs, t0, 180, 1.0897, 1.08972, 0.00002, 3e-5, 0.25).Reason != null);
        Check("price beyond target refused", CopyRules.Validate(cs, t0, 180, 1.0849, 1.08492, 0.00002, 3e-5, 0.25).Reason != null);
        Check("excessive cost refused", CopyRules.Validate(cs, t0, 180, 1.08895, 1.0898, 0.00085, 3e-5, 0.25).Reason != null);
        CopySignal bad = CopySignal.Parse(js.Replace("\"stop\": 1.09100", "\"stop\": 1.08700"));
        Check("stop on wrong side refused", CopyRules.Validate(bad, t0, 180, 1.08895, 1.08897, 0.00002, 3e-5, 0.25).Reason != null);
        bool aliasOk = false; foreach (string a in CopyRules.Aliases("GER40")) if (a == "DE40") aliasOk = true;
        Check("GER40 maps to IC Markets DE40", aliasOk);
        SizeResult fx = Sizing.Compute(1516.46, 0.25, 0.0020, 0.0001, 0.0001, 1000, 1000, 1e7);
        Check("EURUSD 20-pip stop sizes 1,000 units within $3.79", fx.Units == 1000 && fx.CashRisk <= fx.RiskBudget && Math.Abs(fx.CashRisk - 2.0) < 1e-9);

        // ---------------- tick-grid alignment (found 2026-11-23: cTrader placed a 338.3-pip XAUUSD stop at 338 pips)
        SizeResult tk = Sizing.Compute(1516.46, 0.25, 3.383, 0.01, 0.01, 1, 1, 1e6, 0.01);
        Check("XAUUSD stop is rounded UP to the 0.01 tick (339 pips)", Math.Abs(tk.StopPips - 339) < 1e-9);
        Check("tick-aligned risk is what is sized", Math.Abs(tk.CashRisk - 3.39) < 1e-9 && tk.CashRisk <= tk.RiskBudget);
        Check("target pips are rounded DOWN to the tick", Math.Abs(Sizing.FloorPips(5.0789, 0.01, 0.01) - 507) < 1e-9);
        Check("FX keeps 0.1-pip resolution with a 0.00001 tick", Math.Abs(Sizing.CeilPips(0.00203, 0.0001, 0.00001) - 20.3) < 1e-9);
        x = ti(); x.TickSize = 0.01; TestPlan tpk = ExecutionTest.Plan(x);
        Check("execution-test stop is whole ticks", tpk.Reason == null && Math.Abs(tpk.StopPips - Math.Round(tpk.StopPips)) < 1e-9);
        bool tickInv = true;
        var rng3 = new Random(5);
        for (int i = 0; i < 20000; i++)
        {
            double tick = rng3.Next(2) == 0 ? 0.01 : 0.00001, pip = tick == 0.01 ? 0.01 : 0.0001, stop = tick * (1 + rng3.Next(5000)) + rng3.NextDouble() * tick;
            SizeResult z = Sizing.Compute(500 + rng3.NextDouble() * 100000, 0.25, stop, pip, pip, 1, 1, 1e9, tick);
            double ticks = z.StopPips * pip / tick;
            if (z.Units > 0 && (z.CashRisk > z.RiskBudget + 1e-6 || Math.Abs(ticks - Math.Round(ticks)) > 1e-6 || z.StopPips * pip < stop - 1e-9)) tickInv = false;
        }
        Check("20,000 random sizings: stops on the tick grid, never closer than requested, risk within budget", tickInv);

        Console.WriteLine(string.Format("safety tests: {0} passed, {1} failed", _pass, _fail));
        return _fail;
    }
}
