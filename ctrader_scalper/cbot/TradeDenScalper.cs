// TradeDen Scalper (tds-1.0) - cTrader cBot
//
// DEMO-ONLY multi-symbol scalping engine. Mirrors ctrader_scalper/engine
// (Python reference implementation, walk-forward tested) rule for rule.
//
// Safety contract (enforced in code; tested offline by cbot/tests/SafetyTests.cs):
//   * Live accounts: refuses to start, and re-checks before every order (Account.IsLive).
//   * Orders are sent ONLY when ExecutionGate.Evaluate allows: DemoTrading requested, forward experiment
//     fwd-xau-001 approved in code, the activation code typed by the account owner, the exact demo account
//     number and broker matched, and the symbol is XAUUSD. Anything else runs SignalsOnly (journal only).
//   * Hard ceilings (ForwardRules): risk <= 0.25% of balance per trade, 1 open position, daily loss <= 1%
//     including open risk, halt after 2 consecutive losses until the owner sets "Resume after UTC".
//   * Every order carries a stop-loss; a position that ends up without one is closed immediately.
//   * Position size depends only on balance x fixed risk % / stop distance: no martingale, no averaging,
//     no scaling in, no recovery sizing.
//   * Evidence first: if the order-intent record cannot be written to the journal, no order is sent.
//   * Equity kill switch closes this bot's positions when the daily loss limit is hit.
//
// Written in C# 5 syntax so it compiles both in cTrader (.NET 6+) and with the
// repository's offline check (Windows csc.exe against the cAlgo .NET Framework API).

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    public enum ExecutionMode
    {
        DemoTrading,
        SignalsOnly
    }

    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeDenScalper : Robot
    {
        public const string StrategyVersion = "tds-1.0";

        // Research gate. Automated execution stays locked until a strategy is PROMOTED by
        // the pre-registered research protocol (docs/EDGE_DISCOVERY_V2_PLAN.md). While locked,
        // DemoTrading requests run as SignalsOnly (shadow): signals are journaled, no orders are sent.
        // Unlocking requires editing this constant AND the verdict string, i.e. a reviewed code change.
        public const bool ExecutionUnlocked = false;
        public const string ResearchVerdict = "NO_EDGE (tds-1.0, edge-discovery-v2 and TradeDen V3, 2026-11-23)";

        // Forward experiment gate (reviewed 2026-11-23). This does NOT claim an edge: ExecutionUnlocked stays false.
        // It permits a small, demo-only, XAUUSD-only experiment to measure real broker execution against the
        // simulator. Orders additionally require the owner's activation code and exact account/broker match.
        public const bool ForwardExperimentApproved = true;
        public const string ForwardExperimentId = "fwd-xau-001";

        // ---------------------------------------------------------------- parameters
        [Parameter("Symbols (comma separated)", DefaultValue = "XAUUSD", Group = "Universe")]
        public string SymbolList { get; set; }

        [Parameter("Execution mode", DefaultValue = ExecutionMode.SignalsOnly, Group = "Safety")]
        public ExecutionMode Mode { get; set; }

        // Defaults match the owner's verified IC Markets (Raw Trading Ltd) demo account 10141056 (checked 2026-11-23).
        // Any other account or broker fails the gate (SignalsOnly), and live accounts are refused regardless.
        [Parameter("Expected demo account number (required for orders)", DefaultValue = 10141056, Group = "Safety")]
        public int ExpectedAccountNumber { get; set; }

        [Parameter("Expected broker", DefaultValue = "Raw Trading", Group = "Safety")]
        public string ExpectedBroker { get; set; }

        [Parameter("Activation code (type fwd-xau-001 to allow demo orders)", DefaultValue = "", Group = "Safety")]
        public string ActivationCode { get; set; }

        [Parameter("Resume after UTC (yyyy-MM-dd HH:mm, blank = count all)", DefaultValue = "", Group = "Safety")]
        public string ResumeAfterUtc { get; set; }

        [Parameter("Risk per trade %", DefaultValue = 0.25, MinValue = 0.05, MaxValue = 0.25, Step = 0.05, Group = "Risk")]
        public double RiskPercent { get; set; }

        [Parameter("Max open positions", DefaultValue = 1, MinValue = 1, MaxValue = 1, Group = "Risk")]
        public int MaxPositions { get; set; }

        [Parameter("Max daily loss %", DefaultValue = 1.0, MinValue = 0.25, MaxValue = 1.0, Step = 0.25, Group = "Risk")]
        public double MaxDailyLossPercent { get; set; }

        [Parameter("Halt after consecutive losses", DefaultValue = 2, MinValue = 1, MaxValue = 2, Group = "Risk")]
        public int MaxConsecutiveLosses { get; set; }

        [Parameter("Max slippage (x M5 ATR)", DefaultValue = 0.10, MinValue = 0.01, MaxValue = 0.5, Step = 0.01, Group = "Risk")]
        public double MaxSlippageAtr { get; set; }

        [Parameter("Commission $ per side per $1M notional", DefaultValue = 30.0, MinValue = 0, Group = "Risk")]
        public double CommissionPerMillion { get; set; }

        [Parameter("Reward:risk", DefaultValue = 1.5, MinValue = 0.5, MaxValue = 5, Step = 0.1, Group = "Strategy")]
        public double RewardRisk { get; set; }

        [Parameter("Stop buffer (x ATR)", DefaultValue = 0.3, MinValue = 0, MaxValue = 2, Step = 0.05, Group = "Strategy")]
        public double SlBufferAtr { get; set; }

        [Parameter("Min quality score (0-100)", DefaultValue = 80, MinValue = 0, MaxValue = 100, Group = "Strategy")]
        public int MinScore { get; set; }

        [Parameter("Breakout-retest setup", DefaultValue = true, Group = "Strategy")]
        public bool UseBreakoutRetest { get; set; }

        [Parameter("Trend pullback setup", DefaultValue = true, Group = "Strategy")]
        public bool UsePullback { get; set; }

        [Parameter("Breakeven at R (0 = off)", DefaultValue = 0.0, MinValue = 0, MaxValue = 3, Step = 0.25, Group = "Strategy")]
        public double BreakevenR { get; set; }

        [Parameter("Max hold minutes", DefaultValue = 120, MinValue = 5, MaxValue = 1440, Group = "Strategy")]
        public int MaxHoldMinutes { get; set; }

        [Parameter("Min stop (x ATR)", DefaultValue = 0.5, MinValue = 0.1, Group = "Strategy")]
        public double MinSlAtr { get; set; }

        [Parameter("Max stop (x ATR)", DefaultValue = 3.0, MinValue = 0.5, Group = "Strategy")]
        public double MaxSlAtr { get; set; }

        [Parameter("Max cost / risk", DefaultValue = 0.25, MinValue = 0.01, MaxValue = 1, Step = 0.01, Group = "Strategy")]
        public double MaxCostToRisk { get; set; }

        [Parameter("Cooldown minutes after exit", DefaultValue = 15, MinValue = 0, Group = "Strategy")]
        public int CooldownMinutes { get; set; }

        [Parameter("Copy TradeDen signals (bridge inbox)", DefaultValue = false, Group = "TradeDen copy")]
        public bool CopyTradeDen { get; set; }

        [Parameter("Copy activation code (type fwd-tdn-001)", DefaultValue = "", Group = "TradeDen copy")]
        public string CopyActivationCode { get; set; }

        [Parameter("Max signal age seconds", DefaultValue = 180, MinValue = 30, MaxValue = 900, Group = "TradeDen copy")]
        public int CopyMaxAgeSeconds { get; set; }

        [Parameter("Max copied hold hours (if signal has no time exit)", DefaultValue = 24, MinValue = 1, MaxValue = 120, Group = "TradeDen copy")]
        public int CopyMaxHoldHours { get; set; }

        [Parameter("Inbox file (blank = Documents\\TradeDenScalper\\inbox\\tradeden_signals.jsonl)", DefaultValue = "", Group = "TradeDen copy")]
        public string CopyInboxFile { get; set; }

        [Parameter("Run ONE execution test order (EXECUTION_TEST)", DefaultValue = false, Group = "Execution test")]
        public bool RunExecutionTest { get; set; }

        [Parameter("Execution test hold minutes", DefaultValue = 5, MinValue = 1, MaxValue = 60, Group = "Execution test")]
        public int ExecutionTestHoldMinutes { get; set; }

        [Parameter("Journal folder (blank = Documents\\TradeDenScalper\\journal)", DefaultValue = "", Group = "Journal")]
        public string JournalFolder { get; set; }

        [Parameter("Position label", DefaultValue = "TDS-FWD1", Group = "Journal")]
        public string LabelPrefix { get; set; }

        // ---------------------------------------------------------------- state
        private readonly List<SymbolContext> _contexts = new List<SymbolContext>();
        private readonly Dictionary<long, OpenMeta> _meta = new Dictionary<long, OpenMeta>();
        private readonly HashSet<long> _breakevenDone = new HashSet<long>();
        private Journal _journal;
        private string _runId;
        private DateTime _killSwitchDay = DateTime.MinValue;
        private DateTime _lastHeartbeat = DateTime.MinValue;
        private bool _safetyStopped;
        private string _lastStatus = "";
        private ExecutionMode _mode = ExecutionMode.SignalsOnly;
        private string _gateReason = "";
        private DateTime _resumeAfter = DateTime.MinValue;
        private DateTime _nextAssessment = DateTime.MinValue;
        private readonly List<PaperTrade> _paper = new List<PaperTrade>();
        private DateTime _startTime = DateTime.MinValue;
        private bool _testAttempted;
        private double _testPlannedStop = double.NaN;
        private long _inboxPos = -1;
        private string _inboxBuf = "";
        private DateTime _lastInboxPoll = DateTime.MinValue;
        private readonly HashSet<string> _copySeen = new HashSet<string>();
        private readonly Dictionary<long, DateTime> _copyTimeExit = new Dictionary<long, DateTime>();
        private int _paperSeq;

        private double EffRisk { get { return ForwardRules.ClampRisk(RiskPercent); } }
        private int EffMaxPositions { get { return Math.Min(Math.Max(MaxPositions, 1), ForwardRules.MaxPositions); } }
        private double EffDailyLoss { get { return Math.Min(MaxDailyLossPercent, ForwardRules.MaxDailyLossPercent); } }
        private int EffConsecutive { get { return Math.Min(Math.Max(MaxConsecutiveLosses, 1), ForwardRules.MaxConsecutiveLosses); } }

        // ---------------------------------------------------------------- lifecycle
        protected override void OnStart()
        {
            _runId = Server.Time.ToString("yyyyMMddTHHmmss", CultureInfo.InvariantCulture) + "-" + Guid.NewGuid().ToString("N").Substring(0, 6);
            _journal = new Journal(ResolveJournalFolder(), RunningMode == RunningMode.RealTime ? null : "backtest-" + _runId);

            string why;
            bool demoOk = VerifyDemo(out why);
            if (!string.IsNullOrWhiteSpace(ResumeAfterUtc) &&
                !DateTime.TryParseExact(ResumeAfterUtc.Trim(), "yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture,
                    DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out _resumeAfter))
            {
                Print("SAFETY STOP: 'Resume after UTC' must be yyyy-MM-dd HH:mm");
                _journal.Write(Rec("safety").Add("message", "invalid Resume after UTC parameter"));
                _safetyStopped = true;
                Stop();
                return;
            }
            _gateReason = ExecutionGate.Evaluate(GateFor(ExecutionGate.ExperimentSymbol));
            _mode = _gateReason == null ? ExecutionMode.DemoTrading : ExecutionMode.SignalsOnly;
            Print(_mode == ExecutionMode.DemoTrading
                ? "FORWARD EXPERIMENT " + ForwardExperimentId + " ACTIVE on DEMO: XAUUSD orders allowed within ForwardRules."
                : "SignalsOnly: " + _gateReason + ". No orders will be sent.");
            _journal.Write(StartRecord(demoOk, why));
            if (!demoOk)
            {
                Print("SAFETY STOP: " + why);
                _safetyStopped = true;
                Stop();
                return;
            }

            foreach (string raw in (SymbolList ?? "").Split(new[] { ',', ';', ' ' }, StringSplitOptions.RemoveEmptyEntries))
            {
                string name = raw.Trim().ToUpperInvariant();
                Symbol sym = Symbols.GetSymbol(name);
                if (sym == null)
                {
                    Print("Symbol not found, skipped: " + name);
                    _journal.Write(Rec("warning").Add("message", "symbol not found: " + name));
                    continue;
                }
                var ctx = new SymbolContext(name, sym, SignalCore.IsCrypto(name));
                ctx.M1 = MarketData.GetBars(TimeFrame.Minute, name);
                ctx.M5 = MarketData.GetBars(TimeFrame.Minute5, name);
                ctx.M15 = MarketData.GetBars(TimeFrame.Minute15, name);
                EnsureHistory(ctx.M5, SignalCore.MinM5Bars + 80);
                EnsureHistory(ctx.M15, SignalCore.MinM15Bars + 20);
                EnsureHistory(ctx.M1, 300);
                // warm the breakout state machine on recent closed bars without trading
                int last = ctx.M5.Count - 2;
                int from = Math.Max(SignalCore.Warmup, last - 60);
                if (last >= from)
                {
                    Process(ctx, from, last, false);
                }
                ctx.M5.BarOpened += OnM5BarOpened;
                _contexts.Add(ctx);
                Print("Watching " + name + " | M5 bars " + ctx.M5.Count + " | crypto=" + ctx.Crypto);
            }

            Positions.Closed += OnPositionClosed;
            Positions.Closed += OnExecutionTestClosed;
            _startTime = Server.Time;
            WriteAssessments();          // immediate diagnostic at start, then at the top of every hour
            Timer.Start(1);
            UpdatePanel("started");
        }

        protected override void OnStop()
        {
            if (_journal != null)
            {
                _journal.Write(Rec("stop").Add("safety_stopped", _safetyStopped));
            }
        }

        protected override void OnTimer()
        {
            if (_safetyStopped) return;
            ManageOpenPositions();
            EnforceEquityKillSwitch();
            if ((Server.Time - _lastHeartbeat).TotalSeconds >= 60)
            {
                _lastHeartbeat = Server.Time;
                WriteHeartbeat();
            }
            ManagePaperTrades();
            if (RunExecutionTest && !_testAttempted && (Server.Time - _startTime).TotalSeconds >= 5)
            {
                _testAttempted = true;      // at most ONE attempt per run; never retried automatically
                TryExecutionTest();
            }
            ManageExecutionTest();
            if (CopyTradeDen && (Server.Time - _lastInboxPoll).TotalSeconds >= 2)
            {
                _lastInboxPoll = Server.Time;
                ProcessInbox();
            }
            if (Server.Time >= _nextAssessment)
            {
                WriteAssessments();
            }
        }

        // ---------------------------------------------------------------- safety
        private GateInput GateFor(string symbol)
        {
            return new GateInput
            {
                IsLive = Account.IsLive, AccountNumber = Account.Number, ExpectedAccount = ExpectedAccountNumber,
                Broker = Account.BrokerName, ExpectedBroker = ExpectedBroker, Symbol = symbol,
                DemoTradingRequested = Mode == ExecutionMode.DemoTrading, ActivationCode = ActivationCode,
                ExperimentApproved = ForwardExperimentApproved
            };
        }

        private GateInput CopyGateFor(string symbol)
        {
            GateInput g = GateFor(symbol);
            g.Experiment = ExecutionGate.CopyExperiment;
            g.ActivationCode = CopyActivationCode;
            return g;
        }

        private bool VerifyDemo(out string reason)
        {
            if (Account.IsLive)
            {
                reason = "account reports IsLive=true; this cBot only executes on DEMO accounts";
                return false;
            }
            if (ExpectedAccountNumber != 0 && Account.Number != ExpectedAccountNumber)
            {
                reason = "account number does not match the configured demo account";
                return false;
            }
            reason = "demo verified (IsLive=false)";
            return true;
        }

        private void EnsureHistory(Bars bars, int needed)
        {
            int guard = 0;
            while (bars.Count < needed && guard++ < 20)
            {
                if (bars.LoadMoreHistory() <= 0) break;
            }
        }

        // ---------------------------------------------------------------- signals
        private void OnM5BarOpened(BarOpenedEventArgs args)
        {
            if (_safetyStopped) return;
            SymbolContext ctx = _contexts.FirstOrDefault(c => ReferenceEquals(c.M5, args.Bars));
            if (ctx == null) return;
            int last = ctx.M5.Count - 2;
            int from = ctx.LastProcessed < 0 ? last : ctx.LastProcessed + 1;
            Process(ctx, Math.Max(from, SignalCore.Warmup), last, true);
        }

        private void Process(SymbolContext ctx, int from, int to, bool live)
        {
            if (to < SignalCore.Warmup) return;
            var m5 = SeriesFrom(ctx.M5, ctx.M5.Count - 1);       // closed bars only
            var m15 = SeriesFrom(ctx.M15, ctx.M15.Count);
            var m1 = SeriesFrom(ctx.M1, ctx.M1.Count);
            var ind = new SignalCore.M5Indicators(m5);
            var ctxTf = new SignalCore.HigherTf(m15, m1);
            for (int i = from; i <= to; i++)
            {
                double spread = live && i == to ? ctx.Sym.Spread : double.NaN;
                List<Candidate> found = SignalCore.Step(ctx.State, m5, ind, ctxTf, i, spread, ctx.Crypto);
                ctx.LastProcessed = i;
                if (!live || i != to) continue;
                foreach (Candidate c in found)
                {
                    JsonRecord decided = HandleCandidate(ctx, c);
                    NoteDecision(ctx, c, decided);
                }
            }
        }

        private static BarSeries SeriesFrom(Bars b, int count)
        {
            count = Math.Max(0, Math.Min(count, b.Count));
            var s = new BarSeries(count);
            for (int i = 0; i < count; i++)
            {
                s.T[i] = b.OpenTimes[i];
                s.O[i] = b.OpenPrices[i];
                s.H[i] = b.HighPrices[i];
                s.L[i] = b.LowPrices[i];
                s.C[i] = b.ClosePrices[i];
            }
            return s;
        }

        // ---------------------------------------------------------------- execution
        private JsonRecord HandleCandidate(SymbolContext ctx, Candidate c)
        {
            JsonRecord rec = Rec("signal").Add("symbol", ctx.Name).Add("side", c.Side > 0 ? "buy" : "sell")
                .Add("setup", c.Setup).Add("score", c.Score).Add("session", c.Session).Add("atr", c.Atr)
                .Add("rsi", c.Rsi).Add("anchor", c.Anchor).Add("bar_close_utc", c.Time).Add("components", c.ComponentText);

            string skip = Qualify(ctx, c);
            if (skip != null)
            {
                _journal.Write(rec.Add("decision", "skipped").Add("reason", skip));
                return rec;
            }

            Symbol s = ctx.Sym;
            int side = c.Side;
            double estEntry = side > 0 ? s.Ask : s.Bid;
            double stop = c.Anchor - side * SlBufferAtr * c.Atr;
            double riskPx = (estEntry - stop) * side;
            if (riskPx <= 0 || riskPx < MinSlAtr * c.Atr || riskPx > MaxSlAtr * c.Atr)
            {
                _journal.Write(rec.Add("decision", "skipped").Add("reason", "stop distance outside " + MinSlAtr + "-" + MaxSlAtr + " ATR"));
                return rec;
            }
            double commissionRate = CommissionPerMillion / 1e6;
            double cost = s.Spread + 2 * commissionRate * estEntry;
            if (cost / riskPx > MaxCostToRisk)
            {
                _journal.Write(rec.Add("decision", "skipped").Add("reason", "cost/risk " + (cost / riskPx).ToString("0.00", CultureInfo.InvariantCulture) + " > " + MaxCostToRisk));
                return rec;
            }

            RiskState rs = GetRiskState();
            // risk base = the LOWER of balance and equity: floating profit (e.g. on manual positions) never raises bot risk
            double riskBase = Math.Min(Account.Balance, Account.Equity);
            SizeResult size = Sizing.Compute(riskBase, EffRisk, riskPx, s.PipSize, s.PipValue,
                                             s.VolumeInUnitsMin, s.VolumeInUnitsStep, s.VolumeInUnitsMax, s.TickSize);
            double units = size.Units > 0 ? s.NormalizeVolumeInUnits(size.Units, RoundingMode.Down) : 0;
            double slPips = size.StopPips;
            double cashRisk = units * slPips * s.PipValue;
            if (units < s.VolumeInUnitsMin || cashRisk > size.RiskBudget * 1.0001)
            {
                double minRisk = s.VolumeInUnitsMin * Math.Ceiling(riskPx / s.PipSize * 10.0 - 1e-9) / 10.0 * s.PipValue;
                _journal.Write(rec.Add("decision", "skipped")
                    .Add("reason", "minimum volume would exceed the risk budget")
                    .Add("risk_base", riskBase).Add("risk_budget", size.RiskBudget).Add("stop_distance", riskPx)
                    .Add("min_volume_units", s.VolumeInUnitsMin).Add("min_volume_risk", minRisk)
                    .Add("detail", string.Format(CultureInfo.InvariantCulture,
                        "stop {0:0.00} needs {1:0.##} units x {0:0.00} = ${2:0.00} risk at minimum volume, budget is ${3:0.00} (0.25% of {4:0.00})",
                        riskPx, s.VolumeInUnitsMin, minRisk, size.RiskBudget, riskBase)));
                return rec;
            }
            string riskBlock = ForwardRules.RiskCheck(new RiskInput
            {
                DayStartBalance = rs.DayStartBalance, RealizedToday = rs.RealizedToday, OpenRisk = rs.OpenRisk, NewRisk = cashRisk,
                DailyLossPercent = EffDailyLoss, OwnPositions = rs.OwnPositions, MaxPositions = EffMaxPositions,
                ForeignPositionsOnSymbol = rs.ForeignOnSymbol, ConsecutiveLosses = rs.ConsecutiveLosses,
                MaxConsecutiveLosses = EffConsecutive, KillSwitchToday = _killSwitchDay == Server.Time.Date
            });
            if (riskBlock != null)
            {
                _journal.Write(rec.Add("decision", "skipped").Add("reason", riskBlock));
                return rec;
            }

            rec.Add("planned_entry", estEntry).Add("planned_stop", stop).Add("risk_cash", cashRisk).Add("risk_budget", size.RiskBudget)
               .Add("units", units).Add("sl_pips", slPips).Add("spread", s.Spread).Add("bid", s.Bid).Add("ask", s.Ask);
            string gate = ExecutionGate.Evaluate(GateFor(ctx.Name));   // re-evaluated immediately before every order
            if (gate != null)
            {
                if (Account.IsLive)
                {
                    _journal.Write(Rec("safety").Add("message", "LIVE account detected before order; cBot stopped"));
                    _safetyStopped = true;
                    Stop();
                    return rec;
                }
                _journal.Write(rec.Add("decision", "signals_only").Add("gate", gate));
                return rec;
            }

            double tpPips = Sizing.FloorPips(slPips * s.PipSize * RewardRisk, s.PipSize, s.TickSize);
            double rangePips = Math.Max(1.0, MaxSlippageAtr * c.Atr / s.PipSize);
            string label = LabelPrefix;
            string comment = StrategyVersion + "|" + c.Setup + "|" + c.Score + "|" + cashRisk.ToString("0.00", CultureInfo.InvariantCulture);
            TradeType tt = side > 0 ? TradeType.Buy : TradeType.Sell;
            string intentId = Guid.NewGuid().ToString("N").Substring(0, 12);
            if (!_journal.Write(Rec("order_intent").Add("intent_id", intentId).Add("symbol", ctx.Name).Add("side", side > 0 ? "buy" : "sell")
                    .Add("units", units).Add("sl_pips", slPips).Add("tp_pips", tpPips).Add("range_pips", rangePips)
                    .Add("base_price", estEntry).Add("spread", s.Spread).Add("risk_cash", cashRisk)))
            {
                Print("Journal not writable: order NOT sent (evidence first).");
                return rec;
            }
            DateTime sent = DateTime.UtcNow;
            TradeResult result = ExecuteMarketRangeOrder(tt, ctx.Name, units, rangePips, estEntry, label, slPips, tpPips, comment);
            double latencyMs = (DateTime.UtcNow - sent).TotalMilliseconds;
            if (!result.IsSuccessful || result.Position == null)
            {
                _journal.Write(rec.Add("decision", "order_failed").Add("intent_id", intentId).Add("latency_ms", latencyMs)
                    .Add("error", result.Error.HasValue ? result.Error.Value.ToString() : "unknown"));
                return rec;
            }
            Position p = result.Position;
            if (!p.StopLoss.HasValue)
            {
                ClosePosition(p);
                _journal.Write(Rec("safety").Add("message", "position opened without stop-loss and was closed immediately").Add("position_id", p.Id));
                return rec;
            }
            double slippage = (p.EntryPrice - estEntry) * side;
            _meta[p.Id] = new OpenMeta { CashRisk = cashRisk, Setup = c.Setup, Score = c.Score, Session = c.Session,
                RiskPx = Math.Abs(p.EntryPrice - p.StopLoss.Value), Side = side, Stop = p.StopLoss.Value,
                Target = p.TakeProfit.HasValue ? p.TakeProfit.Value : double.NaN, SignalTime = c.Time };
            _journal.Write(rec.Add("decision", "opened").Add("intent_id", intentId).Add("position_id", p.Id).Add("entry", p.EntryPrice)
                .Add("entry_time", p.EntryTime).Add("stop", p.StopLoss.Value).Add("target", p.TakeProfit.HasValue ? p.TakeProfit.Value : double.NaN)
                .Add("slippage", slippage).Add("slippage_pips", slippage / s.PipSize).Add("latency_ms", latencyMs)
                .Add("spread_at_fill", s.Spread).Add("entry_commission", p.Commissions));
            Print(string.Format(CultureInfo.InvariantCulture, "OPEN {0} {1} {2} @ {3} SL {4} TP {5} risk ${6:0.00} [{7} score {8}]",
                tt, units, ctx.Name, p.EntryPrice, p.StopLoss, p.TakeProfit, cashRisk, c.Setup, c.Score));
            UpdatePanel("opened " + ctx.Name);
            return rec;
        }

        private string Qualify(SymbolContext ctx, Candidate c)
        {
            if (c.Setup == SignalCore.SetupBreakoutRetest && !UseBreakoutRetest) return "setup disabled";
            if (c.Setup == SignalCore.SetupPullback && !UsePullback) return "setup disabled";
            if (c.Score < MinScore) return "score " + c.Score + " < " + MinScore;
            if ((Server.Time - c.Time).TotalMinutes > 2) return "stale bar";
            if (!ctx.Sym.IsTradingEnabled) return "symbol trading disabled";
            RiskState rs = GetRiskState();
            if (rs.Halted) return rs.HaltReason;
            if (rs.OwnPositions >= EffMaxPositions) return "max positions open";
            if (Positions.Any(p => p.Label == LabelPrefix && p.SymbolName == ctx.Name)) return "position already open on symbol";
            if (Positions.Any(p => p.Label != LabelPrefix && p.SymbolName == ctx.Name)) return "another (manual or foreign) position is open on this symbol";
            if (ctx.LastExit != DateTime.MinValue && (Server.Time - ctx.LastExit).TotalMinutes < CooldownMinutes) return "cooldown";
            return null;
        }

        // ---------------------------------------------------------------- risk
        private class RiskState
        {
            public double DayStartBalance;
            public double RealizedToday;
            public double OpenRisk;
            public double DailyLimit;
            public int ConsecutiveLosses;
            public int OwnPositions;
            public int ForeignOnSymbol;
            public bool Halted;
            public string HaltReason;
        }

        private RiskState GetRiskState()
        {
            DateTime day = Server.Time.Date;
            var rs = new RiskState();
            double allToday = 0;
            var ours = new List<HistoricalTrade>();
            foreach (HistoricalTrade h in History)
            {
                if (h.ClosingTime < day) continue;
                allToday += h.NetProfit;
                if (h.Label == LabelPrefix) ours.Add(h);
            }
            rs.DayStartBalance = Account.Balance - allToday;
            rs.RealizedToday = ours.Sum(h => h.NetProfit);
            // the loss streak is NOT reset daily: it spans this label's whole history since "Resume after UTC"
            List<double> ordered = History.Where(h => h.Label == LabelPrefix && h.ClosingTime > _resumeAfter)
                                          .OrderBy(h => h.ClosingTime).Select(h => h.NetProfit).ToList();
            rs.ConsecutiveLosses = ForwardRules.ConsecutiveLosses(ordered);
            foreach (Position p in Positions)
            {
                if (p.Label != LabelPrefix)
                {
                    if (p.SymbolName == ExecutionGate.ExperimentSymbol) rs.ForeignOnSymbol++;
                    continue;
                }
                rs.OwnPositions++;
                if (p.StopLoss.HasValue)
                {
                    Symbol s = Symbols.GetSymbol(p.SymbolName);
                    double dist = (p.TradeType == TradeType.Buy ? p.EntryPrice - p.StopLoss.Value : p.StopLoss.Value - p.EntryPrice);
                    rs.OpenRisk += Math.Max(0, dist / s.PipSize * s.PipValue * p.VolumeInUnits);
                }
            }
            rs.DailyLimit = rs.DayStartBalance * EffDailyLoss / 100.0;
            if (_killSwitchDay == day) { rs.Halted = true; rs.HaltReason = "daily equity kill switch triggered"; }
            else if (rs.RealizedToday <= -rs.DailyLimit) { rs.Halted = true; rs.HaltReason = "daily loss limit reached"; }
            else if (rs.ConsecutiveLosses >= EffConsecutive) { rs.Halted = true; rs.HaltReason = rs.ConsecutiveLosses + " consecutive losses: halted until the owner sets 'Resume after UTC'"; }
            return rs;
        }

        private void EnforceEquityKillSwitch()
        {
            DateTime day = Server.Time.Date;
            if (_killSwitchDay == day) return;
            RiskState rs = GetRiskState();
            if (Account.Equity > rs.DayStartBalance - rs.DailyLimit) return;
            _killSwitchDay = day;
            foreach (Position p in Positions.Where(x => x.Label == LabelPrefix).ToList())
            {
                ClosePosition(p);
            }
            _journal.Write(Rec("halt").Add("reason", "equity kill switch").Add("equity", Account.Equity).Add("day_start_balance", rs.DayStartBalance));
            Print("HALT: daily equity loss limit reached; positions closed, no new trades until next UTC day");
            UpdatePanel("halted (daily loss)");
        }

        private void ManageOpenPositions()
        {
            foreach (Position p in Positions.Where(x => x.Label == LabelPrefix).ToList())
            {
                if (Server.Time >= HoldDeadline(p))
                {
                    ClosePosition(p);
                    _journal.Write(Rec("time_exit").Add("position_id", p.Id).Add("symbol", p.SymbolName));
                    continue;
                }
                if (BreakevenR <= 0 || _breakevenDone.Contains(p.Id) || !p.StopLoss.HasValue) continue;
                OpenMeta m;
                if (!_meta.TryGetValue(p.Id, out m)) continue;
                Symbol s = Symbols.GetSymbol(p.SymbolName);
                int side = p.TradeType == TradeType.Buy ? 1 : -1;
                double px = side > 0 ? s.Bid : s.Ask;
                if ((px - p.EntryPrice) * side >= BreakevenR * m.RiskPx)
                {
                    double cover = s.Spread + 2 * CommissionPerMillion / 1e6 * p.EntryPrice;
                    double be = p.EntryPrice + side * cover;
                    var r = p.ModifyStopLossPrice(be);
                    _breakevenDone.Add(p.Id);
                    _journal.Write(Rec("breakeven").Add("position_id", p.Id).Add("new_stop", be).Add("ok", r.IsSuccessful));
                }
            }
        }

        // ---------------------------------------------------------------- EXECUTION_TEST (one order, ever)
        private void TryExecutionTest()
        {
            SymbolContext ctx = _contexts.FirstOrDefault(c => c.Name == ExecutionGate.ExperimentSymbol);
            JsonRecord rec = Rec("execution_test").Add("test_id", ExecutionTest.TestId).Add("label", ExecutionTest.Label)
                .Add("note", "EXECUTION_TEST - not a strategy signal; excluded from strategy results");
            if (ctx == null) { _journal.Write(rec.Add("status", "aborted").Add("reason", "XAUUSD context not loaded")); return; }
            Symbol s = ctx.Sym;
            string gate = ExecutionGate.Evaluate(GateFor(ctx.Name));
            bool done = History.Any(h => h.Label == ExecutionTest.Label) || Positions.Any(p => p.Label == ExecutionTest.Label);
            int conflicts = Positions.Count(p => p.SymbolName == ctx.Name || p.Label == LabelPrefix);
            BarSeries m5 = SeriesFrom(ctx.M5, ctx.M5.Count - 1);
            double atr = m5.Count > 20 ? new SignalCore.M5Indicators(m5).Atr[m5.Count - 1] : double.NaN;
            double riskBase = Math.Min(Account.Balance, Account.Equity);
            TestPlan plan = ExecutionTest.Plan(new TestInput
            {
                GateReason = gate, AlreadyExecuted = done, ConflictingPositions = conflicts, TradingEnabled = s.IsTradingEnabled,
                SessionBlocked = SignalCore.SessionBlocked(Server.Time, false), RiskBase = riskBase, RiskPercent = EffRisk,
                Atr = atr, Spread = s.Spread, Bid = s.Bid, Ask = s.Ask, MinVolume = s.VolumeInUnitsMin, PipSize = s.PipSize,
                PipValue = s.PipValue, CommissionRate = CommissionPerMillion / 1e6, TickSize = s.TickSize
            });
            rec.Add("is_live", Account.IsLive).Add("account_number_matches", Account.Number == ExpectedAccountNumber)
               .Add("broker", Account.BrokerName).Add("gate", gate ?? "allowed").Add("previous_test_found", done)
               .Add("conflicting_positions", conflicts).Add("bid", s.Bid).Add("ask", s.Ask).Add("spread", s.Spread).Add("atr_m5", atr)
               .Add("risk_base", riskBase).Add("risk_budget", plan.Budget).Add("min_volume_units", s.VolumeInUnitsMin)
               .Add("lot_size_units", s.LotSize).Add("pip_size", s.PipSize).Add("pip_value_per_unit", s.PipValue)
               .Add("stop_distance", plan.StopDistance).Add("stop_pips", plan.StopPips).Add("tp_pips", plan.TpPips)
               .Add("max_loss_at_stop_incl_commission", plan.MaxLoss);
            if (plan.Reason != null)
            {
                _journal.Write(rec.Add("status", "aborted").Add("reason", plan.Reason));
                Print("EXECUTION_TEST aborted: " + plan.Reason);
                return;
            }
            if (Account.IsLive) { _journal.Write(rec.Add("status", "aborted").Add("reason", "LIVE account")); _safetyStopped = true; Stop(); return; }
            if (!_journal.Write(rec.Add("status", "order_intent")))
            {
                Print("EXECUTION_TEST: journal not writable, order NOT sent");
                return;
            }
            double rangePips = Math.Max(1.0, 0.5 * plan.StopPips);
            DateTime sent = DateTime.UtcNow;
            TradeResult r = ExecuteMarketRangeOrder(TradeType.Buy, ctx.Name, s.VolumeInUnitsMin, rangePips, s.Ask,
                ExecutionTest.Label, plan.StopPips, plan.TpPips, "EXECUTION_TEST|" + ExecutionTest.TestId);
            double latency = (DateTime.UtcNow - sent).TotalMilliseconds;
            JsonRecord res = Rec("execution_test").Add("test_id", ExecutionTest.TestId).Add("label", ExecutionTest.Label)
                .Add("latency_ms", latency).Add("requested_price", plan.RequestedPrice);
            if (!r.IsSuccessful || r.Position == null)
            {
                string err = r.Error.HasValue ? r.Error.Value.ToString() : "unknown";
                _journal.Write(res.Add("status", "rejected").Add("error", err));
                Print("EXECUTION_TEST rejected by broker: " + err);
                return;
            }
            Position pos = r.Position;
            if (!pos.StopLoss.HasValue)
            {
                ClosePosition(pos);
                _journal.Write(res.Add("status", "closed_no_stop").Add("position_id", pos.Id));
                return;
            }
            _testPlannedStop = pos.StopLoss.Value;
            _journal.Write(res.Add("status", "filled").Add("position_id", pos.Id).Add("entry", pos.EntryPrice)
                .Add("entry_time", pos.EntryTime).Add("volume_units", pos.VolumeInUnits).Add("quantity_lots", pos.Quantity)
                .Add("stop", pos.StopLoss.Value).Add("target", pos.TakeProfit.HasValue ? pos.TakeProfit.Value : double.NaN)
                .Add("slippage", pos.EntryPrice - plan.RequestedPrice).Add("spread_at_fill", s.Spread)
                .Add("entry_commission", pos.Commissions).Add("hold_minutes", ExecutionTestHoldMinutes));
            Print(string.Format(CultureInfo.InvariantCulture, "EXECUTION_TEST FILLED: position {0} BUY {1} units XAUUSD @ {2} SL {3} TP {4}",
                pos.Id, pos.VolumeInUnits, pos.EntryPrice, pos.StopLoss, pos.TakeProfit));
            UpdatePanel("EXECUTION_TEST filled #" + pos.Id);
        }

        private void ManageExecutionTest()
        {
            foreach (Position p in Positions.Where(x => x.Label == ExecutionTest.Label).ToList())
            {
                if ((Server.Time - p.EntryTime).TotalMinutes >= ExecutionTestHoldMinutes)
                {
                    TradeResult r = ClosePosition(p);
                    _journal.Write(Rec("execution_test").Add("test_id", ExecutionTest.TestId).Add("status", "close_requested")
                        .Add("position_id", p.Id).Add("ok", r.IsSuccessful).Add("error", r.Error.HasValue ? r.Error.Value.ToString() : ""));
                }
            }
        }

        private void OnExecutionTestClosed(PositionClosedEventArgs args)
        {
            Position p = args.Position;
            if (p.Label != ExecutionTest.Label) return;
            HistoricalTrade h = null;
            foreach (HistoricalTrade t in History) if (t.PositionId == p.Id) h = t;
            JsonRecord rec = Rec("execution_test").Add("test_id", ExecutionTest.TestId).Add("status", "closed")
                .Add("position_id", p.Id).Add("reason", args.Reason.ToString()).Add("entry", p.EntryPrice)
                .Add("volume_units", p.VolumeInUnits);
            Symbol s = Symbols.GetSymbol(p.SymbolName);
            if (s != null) rec.Add("spread_at_close", s.Spread);
            if (h != null)
            {
                rec.Add("exit", h.ClosingPrice).Add("exit_time", h.ClosingTime).Add("closing_deal_id", h.ClosingDealId)
                   .Add("gross", h.GrossProfit).Add("commission", h.Commissions).Add("swap", h.Swap).Add("net", h.NetProfit)
                   .Add("balance_after", h.Balance);
                if (args.Reason == PositionCloseReason.StopLoss && !double.IsNaN(_testPlannedStop))
                    rec.Add("stop_slippage", _testPlannedStop - h.ClosingPrice);
            }
            _journal.Write(rec);
            Print("EXECUTION_TEST CLOSED: " + args.Reason + " net " + (h != null ? h.NetProfit.ToString("0.00", CultureInfo.InvariantCulture) : "?")
                  + ". Normal signal-based operation continues; set 'Run ONE execution test' back to No.");
            UpdatePanel("EXECUTION_TEST closed");
        }

        // ---------------------------------------------------------------- diagnostics (no orders here)
        private void NoteDecision(SymbolContext ctx, Candidate c, JsonRecord rec)
        {
            string decision = rec.Str("decision") ?? "unknown";
            string reason = rec.Str("reason") ?? rec.Str("gate") ?? "";
            ctx.SignalsThisHour++;
            int n;
            ctx.DecisionsThisHour.TryGetValue(decision, out n);
            ctx.DecisionsThisHour[decision] = n + 1;
            ctx.LastSignalTime = c.Time;
            ctx.LastDecision = decision;
            ctx.LastReason = reason;
            if (decision != "opened") OpenPaperTrade(ctx, c, decision, reason);
        }

        /// A SIMULATED trade that tracks what a real strategy signal would have done. It is never sent to the
        /// broker, never counted as an order, and is journaled as paper_trade_open / paper_trade_close.
        private void OpenPaperTrade(SymbolContext ctx, Candidate c, string decision, string reason)
        {
            Symbol s = ctx.Sym;
            int side = c.Side;
            double entry = side > 0 ? s.Ask : s.Bid;
            double stop = c.Anchor - side * SlBufferAtr * c.Atr;
            double risk = (entry - stop) * side;
            if (risk <= 0 || risk < MinSlAtr * c.Atr || risk > MaxSlAtr * c.Atr || _paper.Count >= 10) return;
            var pt = new PaperTrade
            {
                Id = "paper-" + _runId + "-" + (++_paperSeq), Symbol = ctx.Name, Side = side, Entry = entry, Stop = stop,
                Target = entry + side * RewardRisk * risk, Risk = risk, Opened = Server.Time,
                Expiry = Server.Time.AddMinutes(MaxHoldMinutes), Setup = c.Setup, Score = c.Score
            };
            _paper.Add(pt);
            _journal.Write(Rec("paper_trade_open").Add("simulated", true).Add("real_order", false)
                .Add("note", "SIMULATED - not a broker order").Add("paper_id", pt.Id).Add("symbol", pt.Symbol)
                .Add("side", side > 0 ? "buy" : "sell").Add("setup", c.Setup).Add("score", c.Score)
                .Add("signal_decision", decision).Add("signal_reason", reason).Add("entry", entry).Add("stop", stop)
                .Add("target", pt.Target).Add("risk_px", risk).Add("bar_close_utc", c.Time));
        }

        private void ManagePaperTrades()
        {
            if (_paper.Count == 0) return;
            double rate = CommissionPerMillion / 1e6;
            foreach (PaperTrade pt in _paper.ToList())
            {
                Symbol s = Symbols.GetSymbol(pt.Symbol);
                if (s == null) continue;
                double px = pt.Side > 0 ? s.Bid : s.Ask;     // closing side
                string why = null;
                double exit = px;
                if ((px - pt.Stop) * pt.Side <= 0) { why = "stop"; exit = px; }
                else if ((px - pt.Target) * pt.Side >= 0) { why = "target"; exit = pt.Target; }
                else if (Server.Time >= pt.Expiry) { why = "time"; }
                if (why == null) continue;
                _paper.Remove(pt);
                double grossR = (exit - pt.Entry) * pt.Side / pt.Risk;
                double commR = rate * (pt.Entry + exit) / pt.Risk;
                _journal.Write(Rec("paper_trade_close").Add("simulated", true).Add("real_order", false)
                    .Add("note", "SIMULATED - not a broker order").Add("paper_id", pt.Id).Add("symbol", pt.Symbol)
                    .Add("side", pt.Side > 0 ? "buy" : "sell").Add("setup", pt.Setup).Add("score", pt.Score)
                    .Add("reason", why).Add("entry", pt.Entry).Add("exit", exit).Add("opened", pt.Opened)
                    .Add("r_gross", grossR).Add("r_net_est", grossR - commR).Add("resolution", "1-second quotes, no slippage"));
            }
        }

        private void WriteAssessments()
        {
            DateTime now = Server.Time;
            _nextAssessment = new DateTime(now.Year, now.Month, now.Day, now.Hour, 0, 0, DateTimeKind.Utc).AddHours(1);
            foreach (SymbolContext ctx in _contexts)
            {
                try
                {
                    _journal.Write(Assessment(ctx));
                }
                catch (Exception ex)
                {
                    _journal.Write(Rec("warning").Add("message", "market assessment failed: " + ex.Message));
                }
                ctx.SignalsThisHour = 0;
                ctx.DecisionsThisHour.Clear();
            }
        }

        private JsonRecord Assessment(SymbolContext ctx)
        {
            Symbol s = ctx.Sym;
            JsonRecord rec = Rec("market_assessment").Add("symbol", ctx.Name).Add("bid", s.Bid).Add("ask", s.Ask)
                .Add("spread", s.Spread).Add("session", SignalCore.SessionName(Server.Time))
                .Add("session_blocked", SignalCore.SessionBlocked(Server.Time, ctx.Crypto));
            var reasons = new List<string>();
            BarSeries m5 = SeriesFrom(ctx.M5, ctx.M5.Count - 1);
            double atr = double.NaN;
            if (m5.Count > SignalCore.Warmup + 1)
            {
                var ind = new SignalCore.M5Indicators(m5);
                var tf = new SignalCore.HigherTf(SeriesFrom(ctx.M15, ctx.M15.Count), SeriesFrom(ctx.M1, ctx.M1.Count));
                int i = m5.Count - 1;
                int bias = SignalCore.M15Bias(tf, m5.T[i].AddMinutes(5));
                string stack = ind.Ema9[i] > ind.Ema21[i] && ind.Ema21[i] > ind.Ema50[i] ? "bullish"
                             : ind.Ema9[i] < ind.Ema21[i] && ind.Ema21[i] < ind.Ema50[i] ? "bearish" : "mixed";
                atr = ind.Atr[i];
                rec.Add("m15_bias", bias > 0 ? "up" : bias < 0 ? "down" : "neutral").Add("m5_ema_stack", stack)
                   .Add("rsi_m5", ind.Rsi[i]).Add("atr_m5", atr).Add("atr_rank_1d", SignalCore.AtrRank(ind.Atr, i))
                   .Add("last_closed_m5_utc", m5.T[i].AddMinutes(5));
                if (bias == 0) reasons.Add("M15 trend filter is neutral, so no setup can qualify");
            }
            else
            {
                reasons.Add("not enough M5 history loaded");
            }
            string gate = ExecutionGate.Evaluate(GateFor(ctx.Name));
            RiskState rs = GetRiskState();
            double riskBase = Math.Min(Account.Balance, Account.Equity);
            double budget = riskBase * EffRisk / 100.0;
            double perPriceAtMinVolume = s.VolumeInUnitsMin * s.PipValue / s.PipSize;   // $ risk per 1.0 of price at min volume
            double maxAffordableStop = perPriceAtMinVolume > 0 ? budget / perPriceAtMinVolume : 0;
            string risk = ForwardRules.RiskCheck(new RiskInput
            {
                DayStartBalance = rs.DayStartBalance, RealizedToday = rs.RealizedToday, OpenRisk = rs.OpenRisk, NewRisk = budget,
                DailyLossPercent = EffDailyLoss, OwnPositions = rs.OwnPositions, MaxPositions = EffMaxPositions,
                ForeignPositionsOnSymbol = rs.ForeignOnSymbol, ConsecutiveLosses = rs.ConsecutiveLosses,
                MaxConsecutiveLosses = EffConsecutive, KillSwitchToday = _killSwitchDay == Server.Time.Date
            });
            if (gate != null) reasons.Add("execution gate: " + gate);
            if (risk != null) reasons.Add("risk rules: " + risk);
            if (SignalCore.SessionBlocked(Server.Time, ctx.Crypto)) reasons.Add("session blocked (rollover, weekend or Friday close)");
            if (!double.IsNaN(atr) && MinSlAtr * atr > maxAffordableStop)
                reasons.Add(string.Format(CultureInfo.InvariantCulture,
                    "even the smallest allowed stop ({0:0.00} = {1} x ATR) exceeds the largest affordable stop at minimum volume ({2:0.00})",
                    MinSlAtr * atr, MinSlAtr, maxAffordableStop));
            if (ctx.SignalsThisHour == 0) reasons.Add("no strategy setup closed since the previous assessment");
            var dec = new StringBuilder();
            foreach (var kv in ctx.DecisionsThisHour) dec.Append(kv.Key).Append('=').Append(kv.Value).Append(';');
            rec.Add("execution_mode", _mode.ToString()).Add("execution_gate", gate ?? "allowed").Add("risk_check", risk ?? "ok")
               .Add("halted", rs.Halted).Add("risk_base", riskBase).Add("risk_budget", budget)
               .Add("min_volume_units", s.VolumeInUnitsMin).Add("max_affordable_stop_at_min_volume", maxAffordableStop)
               .Add("typical_stop_estimate", double.IsNaN(atr) ? double.NaN : 1.4 * atr)
               .Add("signals_since_last_assessment", ctx.SignalsThisHour).Add("decisions_since_last_assessment", dec.ToString())
               .Add("last_signal_utc", ctx.LastSignalTime == DateTime.MinValue ? "" : ctx.LastSignalTime.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture))
               .Add("last_decision", ctx.LastDecision).Add("last_reason", ctx.LastReason)
               .Add("open_paper_trades", _paper.Count)
               .Add("eligible_for_next_signal", gate == null && risk == null && !SignalCore.SessionBlocked(Server.Time, ctx.Crypto))
               .Add("why_no_trade", reasons.Count == 0 ? "eligible: the next qualifying signal with a stop within the budget will be executed" : string.Join(" | ", reasons));
            return rec;
        }

        private class PaperTrade
        {
            public string Id, Symbol, Setup;
            public int Side, Score;
            public double Entry, Stop, Target, Risk;
            public DateTime Opened, Expiry;
        }

        private DateTime HoldDeadline(Position p)
        {
            if ((p.Comment ?? "").StartsWith("tdn"))
            {
                DateTime t;
                if (_copyTimeExit.TryGetValue(p.Id, out t)) return t;
                return p.EntryTime.AddHours(CopyMaxHoldHours);
            }
            return p.EntryTime.AddMinutes(MaxHoldMinutes);
        }

        // ---------------------------------------------------------------- TradeDen copy mode (fwd-tdn-001)
        private string InboxPath()
        {
            if (!string.IsNullOrWhiteSpace(CopyInboxFile)) return CopyInboxFile;
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "TradeDenScalper", "inbox", "tradeden_signals.jsonl");
        }

        private void ProcessInbox()
        {
            string path = InboxPath();
            string text;
            bool priming = _inboxPos < 0;      // first read after start: silently ignore signals that are already stale
            try
            {
                if (!System.IO.File.Exists(path)) return;
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                {
                    if (_inboxPos < 0 || fs.Length < _inboxPos) _inboxPos = 0;    // first poll reads all; stale ones are rejected by age
                    if (fs.Length == _inboxPos) return;
                    fs.Seek(_inboxPos, SeekOrigin.Begin);
                    var buf = new byte[fs.Length - _inboxPos];
                    int read = fs.Read(buf, 0, buf.Length);
                    _inboxPos += read;
                    text = _inboxBuf + Encoding.UTF8.GetString(buf, 0, read);
                }
            }
            catch (IOException) { return; }
            catch (UnauthorizedAccessException) { return; }
            string[] parts = text.Split('\n');
            _inboxBuf = parts[parts.Length - 1];
            for (int i = 0; i < parts.Length - 1; i++)
            {
                string line = parts[i].Trim();
                if (line.Length == 0) continue;
                CopySignal sig = CopySignal.Parse(line);
                if (sig == null || _copySeen.Contains(sig.SignalId)) continue;
                _copySeen.Add(sig.SignalId);
                DateTime conf;
                if (priming && DateTime.TryParse(sig.ConfirmedAt, CultureInfo.InvariantCulture,
                        DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out conf) &&
                    (Server.Time - conf).TotalSeconds > CopyMaxAgeSeconds) continue;
                HandleCopySignal(sig);
            }
        }

        private void HandleCopySignal(CopySignal sig)
        {
            JsonRecord rec = Rec("tradeden_signal").Add("signal_id", sig.SignalId).Add("source", sig.Source)
                .Add("strategy", sig.Strategy).Add("symbol", sig.Symbol).Add("side", sig.Side > 0 ? "buy" : "sell")
                .Add("signal_entry", sig.Entry).Add("signal_stop", sig.Stop).Add("signal_target", sig.Target)
                .Add("timeframe", sig.Timeframe).Add("confirmed_at", sig.ConfirmedAt);
            string brokerName = null;
            Symbol s = null;
            foreach (string cand in CopyRules.Aliases(sig.Symbol))
            {
                try { s = Symbols.GetSymbol(cand); } catch (Exception) { s = null; }
                if (s != null) { brokerName = cand; break; }
            }
            if (s == null) { _journal.Write(rec.Add("decision", "skipped").Add("reason", "symbol not available on this cTrader account")); return; }
            rec.Add("broker_symbol", brokerName).Add("bid", s.Bid).Add("ask", s.Ask).Add("spread", s.Spread);
            CopyCheck chk = CopyRules.Validate(sig, Server.Time, CopyMaxAgeSeconds, s.Bid, s.Ask, s.Spread,
                                               CommissionPerMillion / 1e6, MaxCostToRisk);
            rec.Add("age_seconds", chk.AgeSeconds);
            if (chk.Reason != null) { _journal.Write(rec.Add("decision", "skipped").Add("reason", chk.Reason)); return; }
            if (!s.IsTradingEnabled) { _journal.Write(rec.Add("decision", "skipped").Add("reason", "symbol trading disabled")); return; }

            RiskState rs = GetRiskState();
            int foreign = Positions.Count(p => p.Label != LabelPrefix && p.SymbolName == brokerName);
            if (Positions.Any(p => p.Label == LabelPrefix && p.SymbolName == brokerName))
            { _journal.Write(rec.Add("decision", "skipped").Add("reason", "position already open on symbol")); return; }
            double riskBase = Math.Min(Account.Balance, Account.Equity);
            SizeResult size = Sizing.Compute(riskBase, EffRisk, chk.StopDistance, s.PipSize, s.PipValue,
                                             s.VolumeInUnitsMin, s.VolumeInUnitsStep, s.VolumeInUnitsMax, s.TickSize);
            double units = size.Units > 0 ? s.NormalizeVolumeInUnits(size.Units, RoundingMode.Down) : 0;
            double slPips = size.StopPips;
            double cashRisk = units * slPips * s.PipValue;
            if (units < s.VolumeInUnitsMin || cashRisk > size.RiskBudget * 1.0001)
            {
                double minRisk = s.VolumeInUnitsMin * Math.Ceiling(chk.StopDistance / s.PipSize * 10.0 - 1e-9) / 10.0 * s.PipValue;
                _journal.Write(rec.Add("decision", "skipped").Add("reason", "minimum volume would exceed the risk budget")
                    .Add("risk_budget", size.RiskBudget).Add("min_volume_units", s.VolumeInUnitsMin).Add("min_volume_risk", minRisk)
                    .Add("stop_distance", chk.StopDistance));
                return;
            }
            string riskBlock = ForwardRules.RiskCheck(new RiskInput
            {
                DayStartBalance = rs.DayStartBalance, RealizedToday = rs.RealizedToday, OpenRisk = rs.OpenRisk, NewRisk = cashRisk,
                DailyLossPercent = EffDailyLoss, OwnPositions = rs.OwnPositions, MaxPositions = EffMaxPositions,
                ForeignPositionsOnSymbol = foreign, ConsecutiveLosses = rs.ConsecutiveLosses,
                MaxConsecutiveLosses = EffConsecutive, KillSwitchToday = _killSwitchDay == Server.Time.Date
            });
            if (riskBlock != null) { _journal.Write(rec.Add("decision", "skipped").Add("reason", riskBlock)); return; }
            string gate = ExecutionGate.Evaluate(CopyGateFor(brokerName));
            if (gate != null)
            {
                if (Account.IsLive) { _journal.Write(Rec("safety").Add("message", "LIVE account detected before copy order; cBot stopped")); _safetyStopped = true; Stop(); return; }
                _journal.Write(rec.Add("decision", "signals_only").Add("gate", gate).Add("units", units).Add("risk_cash", cashRisk));
                return;
            }
            double tpPips = Sizing.FloorPips(chk.TargetDistance, s.PipSize, s.TickSize);
            double rangePips = Math.Max(1.0, 0.25 * slPips);
            double basePrice = sig.Side > 0 ? s.Ask : s.Bid;
            string sidShort = sig.SignalId.Length > 40 ? sig.SignalId.Substring(sig.SignalId.Length - 40) : sig.SignalId;
            string comment = "tdn-" + sig.Source + "|" + sig.Strategy + "|" + sidShort + "|" + cashRisk.ToString("0.00", CultureInfo.InvariantCulture);
            string intentId = Guid.NewGuid().ToString("N").Substring(0, 12);
            if (!_journal.Write(Rec("order_intent").Add("intent_id", intentId).Add("copy", true).Add("signal_id", sig.SignalId)
                    .Add("symbol", brokerName).Add("side", sig.Side > 0 ? "buy" : "sell").Add("units", units).Add("sl_pips", slPips)
                    .Add("tp_pips", tpPips).Add("range_pips", rangePips).Add("base_price", basePrice).Add("spread", s.Spread).Add("risk_cash", cashRisk)))
            {
                Print("Journal not writable: copy order NOT sent (evidence first).");
                return;
            }
            DateTime sent = DateTime.UtcNow;
            TradeResult r = ExecuteMarketRangeOrder(sig.Side > 0 ? TradeType.Buy : TradeType.Sell, brokerName, units, rangePips,
                                                    basePrice, LabelPrefix, slPips, tpPips, comment);
            double latency = (DateTime.UtcNow - sent).TotalMilliseconds;
            if (!r.IsSuccessful || r.Position == null)
            {
                _journal.Write(rec.Add("decision", "order_failed").Add("intent_id", intentId).Add("latency_ms", latency)
                    .Add("error", r.Error.HasValue ? r.Error.Value.ToString() : "unknown"));
                return;
            }
            Position pos = r.Position;
            if (!pos.StopLoss.HasValue)
            {
                ClosePosition(pos);
                _journal.Write(Rec("safety").Add("message", "copied position opened without stop-loss and was closed immediately").Add("position_id", pos.Id));
                return;
            }
            DateTime te;
            if (DateTime.TryParse(sig.TimeExitAt, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out te))
                _copyTimeExit[pos.Id] = te;
            _meta[pos.Id] = new OpenMeta { CashRisk = cashRisk, Setup = "tdn-" + sig.Source + ":" + sig.Strategy, Score = 0,
                Session = SignalCore.SessionName(Server.Time), RiskPx = Math.Abs(pos.EntryPrice - pos.StopLoss.Value), Side = sig.Side,
                Stop = pos.StopLoss.Value, Target = pos.TakeProfit.HasValue ? pos.TakeProfit.Value : double.NaN, SignalTime = Server.Time };
            double slippage = (pos.EntryPrice - basePrice) * sig.Side;
            _journal.Write(rec.Add("decision", "opened").Add("intent_id", intentId).Add("position_id", pos.Id).Add("entry", pos.EntryPrice)
                .Add("entry_time", pos.EntryTime).Add("units", pos.VolumeInUnits).Add("stop", pos.StopLoss.Value)
                .Add("target", pos.TakeProfit.HasValue ? pos.TakeProfit.Value : double.NaN).Add("risk_cash", cashRisk)
                .Add("slippage", slippage).Add("latency_ms", latency).Add("spread_at_fill", s.Spread).Add("entry_commission", pos.Commissions));
            Print(string.Format(CultureInfo.InvariantCulture, "COPY OPEN {0} {1} {2} @ {3} SL {4} TP {5} risk ${6:0.00} [{7}]",
                sig.Side > 0 ? "Buy" : "Sell", pos.VolumeInUnits, brokerName, pos.EntryPrice, pos.StopLoss, pos.TakeProfit, cashRisk, sig.SignalId));
            UpdatePanel("copied " + brokerName + " " + sig.Source);
        }

        // ---------------------------------------------------------------- journal
        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            Position p = args.Position;
            if (p.Label != LabelPrefix) return;
            HistoricalTrade h = null;
            foreach (HistoricalTrade t in History)
            {
                if (t.PositionId == p.Id) h = t;
            }
            OpenMeta m;
            _meta.TryGetValue(p.Id, out m);
            double cashRisk = m != null ? m.CashRisk : ParseRiskFromComment(p.Comment);
            JsonRecord rec = Rec("close").Add("position_id", p.Id).Add("symbol", p.SymbolName)
                .Add("side", p.TradeType == TradeType.Buy ? "buy" : "sell").Add("reason", args.Reason.ToString())
                .Add("units", p.VolumeInUnits).Add("entry", p.EntryPrice).Add("entry_time", p.EntryTime)
                .Add("setup", m != null ? m.Setup : ParseField(p.Comment, 1)).Add("score", m != null ? m.Score : 0)
                .Add("session", m != null ? m.Session : SignalCore.SessionName(p.EntryTime)).Add("risk_cash", cashRisk);
            if (m != null)
            {
                rec.Add("planned_stop", m.Stop).Add("planned_target", m.Target).Add("signal_time", m.SignalTime);
            }
            Symbol cs = Symbols.GetSymbol(p.SymbolName);
            if (cs != null) rec.Add("spread_at_close", cs.Spread);
            if (h != null && m != null && args.Reason == PositionCloseReason.StopLoss)
            {
                rec.Add("stop_slippage", (m.Stop - h.ClosingPrice) * m.Side);   // > 0 = filled worse than the stop
            }
            if (h != null)
            {
                rec.Add("exit", h.ClosingPrice).Add("exit_time", h.ClosingTime).Add("gross", h.GrossProfit)
                   .Add("commission", h.Commissions).Add("swap", h.Swap).Add("net", h.NetProfit).Add("pips", h.Pips)
                   .Add("balance_after", h.Balance).Add("r_multiple", cashRisk > 0 ? h.NetProfit / cashRisk : double.NaN);
            }
            _journal.Write(rec);
            SymbolContext ctx = _contexts.FirstOrDefault(c => c.Name == p.SymbolName);
            if (ctx != null) ctx.LastExit = Server.Time;
            _meta.Remove(p.Id);
            _breakevenDone.Remove(p.Id);
            Print("CLOSE " + p.SymbolName + " " + args.Reason + " net " + (h != null ? h.NetProfit.ToString("0.00", CultureInfo.InvariantCulture) : "?"));
            UpdatePanel("closed " + p.SymbolName);
        }

        private void WriteHeartbeat()
        {
            RiskState rs = GetRiskState();
            var open = new StringBuilder("[");
            bool first = true;
            foreach (Position p in Positions.Where(x => x.Label == LabelPrefix))
            {
                if (!first) open.Append(',');
                first = false;
                open.Append(new JsonRecord().Add("position_id", p.Id).Add("symbol", p.SymbolName)
                    .Add("side", p.TradeType == TradeType.Buy ? "buy" : "sell").Add("units", p.VolumeInUnits)
                    .Add("entry", p.EntryPrice).Add("stop", p.StopLoss.HasValue ? p.StopLoss.Value : double.NaN)
                    .Add("target", p.TakeProfit.HasValue ? p.TakeProfit.Value : double.NaN)
                    .Add("net", p.NetProfit).Add("entry_time", p.EntryTime).ToString());
            }
            open.Append(']');
            _journal.Write(Rec("heartbeat").Add("balance", Account.Balance).Add("equity", Account.Equity)
                .Add("day_start_balance", rs.DayStartBalance).Add("realized_today", rs.RealizedToday)
                .Add("open_risk", rs.OpenRisk).Add("daily_limit", rs.DailyLimit).Add("consecutive_losses", rs.ConsecutiveLosses)
                .Add("halted", rs.Halted).Add("halt_reason", rs.HaltReason).Add("mode", _mode.ToString())
                .AddRaw("positions", open.ToString()));
            UpdatePanel(null);
        }

        private JsonRecord StartRecord(bool demoOk, string why)
        {
            string num = Account.Number.ToString(CultureInfo.InvariantCulture);
            string masked = num.Length > 3 ? new string('*', num.Length - 3) + num.Substring(num.Length - 3) : "***";
            return Rec("start").Add("demo_verified", demoOk).Add("verification", why).Add("is_live", Account.IsLive)
                .Add("account", masked).Add("broker", Account.BrokerName).Add("currency", Account.Asset.Name)
                .Add("leverage", Account.PreciseLeverage).Add("account_type", Account.AccountType.ToString())
                .Add("balance", Account.Balance).Add("equity", Account.Equity).Add("symbols", SymbolList)
                .Add("execution_mode", _mode.ToString()).Add("requested_mode", Mode.ToString()).Add("execution_gate", _gateReason ?? "allowed")
                .Add("experiment_id", ForwardExperimentId).Add("experiment_approved", ForwardExperimentApproved)
                .Add("copy_tradeden", CopyTradeDen).Add("copy_gate", CopyTradeDen ? (ExecutionGate.Evaluate(CopyGateFor("EURUSD")) ?? "allowed") : "off")
                .Add("resume_after", _resumeAfter == DateTime.MinValue ? "" : _resumeAfter.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture))
                .Add("execution_unlocked", ExecutionUnlocked).Add("research_verdict", ResearchVerdict)
                .Add("params", ParamsText());
        }

        private string ParamsText()
        {
            return string.Format(CultureInfo.InvariantCulture,
                "risk={0};maxpos={1};daily={2};consec={3};rr={4};slbuf={5};minscore={6};brt={7};pb={8};be={9};hold={10};minsl={11};maxsl={12};cost={13};cool={14};slip={15};comm={16}",
                EffRisk, EffMaxPositions, EffDailyLoss, EffConsecutive, RewardRisk, SlBufferAtr, MinScore, UseBreakoutRetest, UsePullback,
                BreakevenR, MaxHoldMinutes, MinSlAtr, MaxSlAtr, MaxCostToRisk, CooldownMinutes, MaxSlippageAtr, CommissionPerMillion);
        }

        private JsonRecord Rec(string evt)
        {
            return new JsonRecord().Add("v", StrategyVersion).Add("event", evt).Add("ts", Server.Time)
                .Add("run_id", _runId).Add("running_mode", RunningMode.ToString()).Add("experiment_id", ForwardExperimentId)
                .Add("label", LabelPrefix);
        }

        private string ResolveJournalFolder()
        {
            if (!string.IsNullOrWhiteSpace(JournalFolder)) return JournalFolder;
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "TradeDenScalper", "journal");
        }

        private static string ParseField(string comment, int idx)
        {
            if (string.IsNullOrEmpty(comment)) return "";
            string[] parts = comment.Split('|');
            return parts.Length > idx ? parts[idx] : "";
        }

        private static double ParseRiskFromComment(string comment)
        {
            double v;
            return double.TryParse(ParseField(comment, 3), NumberStyles.Float, CultureInfo.InvariantCulture, out v) ? v : 0;
        }

        private void UpdatePanel(string lastEvent)
        {
            if (lastEvent != null) _lastStatus = lastEvent;
            if (RunningMode == RunningMode.SilentBacktesting || RunningMode == RunningMode.Optimization || Chart == null) return;
            RiskState rs = GetRiskState();
            string text = string.Format(CultureInfo.InvariantCulture,
                "TradeDen Scalper {0}  |  {1}  |  DEMO verified  |  " + ForwardExperimentId + "\nSymbols: {2}\nDay P&L: {3:0.00}  limit -{4:0.00}  open risk {5:0.00}\nPositions: {6}/{7}  consecutive losses: {8}\n{9}\nLast: {10}",
                StrategyVersion, _mode, SymbolList, rs.RealizedToday, rs.DailyLimit, rs.OpenRisk, rs.OwnPositions, EffMaxPositions,
                rs.ConsecutiveLosses, rs.Halted ? "HALTED: " + rs.HaltReason : "Scanning", _lastStatus);
            Chart.DrawStaticText("tds-panel", text, VerticalAlignment.Top, HorizontalAlignment.Left, rs.Halted ? Color.Orange : Color.LightGreen);
        }

        private class OpenMeta
        {
            public double CashRisk;
            public double RiskPx;
            public string Setup;
            public int Score;
            public string Session;
            public int Side;
            public double Stop;
            public double Target;
            public DateTime SignalTime;
        }

        private class SymbolContext
        {
            public readonly string Name;
            public readonly Symbol Sym;
            public readonly bool Crypto;
            public Bars M1, M5, M15;
            public readonly SignalState State = new SignalState();
            public int LastProcessed = -1;
            public DateTime LastExit = DateTime.MinValue;
            public int SignalsThisHour;
            public readonly Dictionary<string, int> DecisionsThisHour = new Dictionary<string, int>();
            public DateTime LastSignalTime = DateTime.MinValue;
            public string LastDecision = "";
            public string LastReason = "";

            public SymbolContext(string name, Symbol sym, bool crypto)
            {
                Name = name;
                Sym = sym;
                Crypto = crypto;
            }
        }
    }

    // ==================================================================== pure logic
    // Everything below is free of cAlgo types so tests/SignalParity can run it on
    // exported data and compare against the Python reference bar for bar.

    public sealed class BarSeries
    {
        public readonly DateTime[] T;
        public readonly double[] O, H, L, C;
        public BarSeries(int n)
        {
            T = new DateTime[n]; O = new double[n]; H = new double[n]; L = new double[n]; C = new double[n];
        }
        public int Count { get { return T.Length; } }
    }

    public sealed class Candidate
    {
        public DateTime Time;      // decision time (M5 bar close, UTC)
        public int Side;
        public string Setup;
        public double Anchor, Atr, Rsi, Ref;
        public int Score;
        public string Session;
        public string ComponentText;
    }

    public sealed class SignalState
    {
        public readonly bool[] PendActive = new bool[2];   // [0]=long, [1]=short
        public readonly double[] PendLevel = new double[2];
        public readonly int[] PendBar = new int[2];
    }

    public static class Ind
    {
        public static double[] Ema(double[] v, int n)
        {
            var o = new double[v.Length];
            if (v.Length == 0) return o;
            double a = 2.0 / (n + 1.0), acc = v[0];
            o[0] = acc;
            for (int i = 1; i < v.Length; i++) { acc = acc + a * (v[i] - acc); o[i] = acc; }
            return o;
        }

        public static double[] Wilder(double[] v, int n)
        {
            var o = new double[v.Length];
            if (v.Length == 0) return o;
            double a = 1.0 / n, acc = v[0];
            o[0] = acc;
            for (int i = 1; i < v.Length; i++) { acc = acc + a * (v[i] - acc); o[i] = acc; }
            return o;
        }

        public static double[] Rsi(double[] c, int n)
        {
            var g = new double[c.Length];
            var l = new double[c.Length];
            for (int i = 1; i < c.Length; i++)
            {
                double d = c[i] - c[i - 1];
                g[i] = d > 0 ? d : 0;
                l[i] = d < 0 ? -d : 0;
            }
            double[] ag = Wilder(g, n), al = Wilder(l, n);
            var o = new double[c.Length];
            for (int i = 0; i < c.Length; i++)
            {
                if (ag[i] == 0 && al[i] == 0) o[i] = 50;
                else if (al[i] == 0) o[i] = 100;
                else o[i] = 100.0 - 100.0 / (1.0 + ag[i] / al[i]);
            }
            return o;
        }

        public static double[] Atr(double[] h, double[] l, double[] c, int n)
        {
            var tr = new double[c.Length];
            for (int i = 0; i < c.Length; i++)
            {
                double prev = i == 0 ? c[0] : c[i - 1];
                tr[i] = Math.Max(h[i] - l[i], Math.Max(Math.Abs(h[i] - prev), Math.Abs(l[i] - prev)));
            }
            return Wilder(tr, n);
        }
    }

    public static class SignalCore
    {
        public const string SetupBreakoutRetest = "BRT";
        public const string SetupPullback = "PB";
        public const int EmaFast = 9, EmaMid = 21, EmaSlow = 50, RsiPeriod = 14, AtrPeriod = 14;
        public const int M15SlopeBars = 3, BreakoutLookback = 24, RetestWindow = 6, AtrRankWindow = 288;
        public const double BreakoutMarginAtr = 0.10, RetestToleranceAtr = 0.25, BreakoutFailAtr = 0.30;
        public const double PullbackZoneAtr = 0.15, MaxSpreadAtr = 0.15, M1SpikeMult = 3.0;
        public const int Warmup = 288;          // max(atr rank window, 3 x EMA50), as in Python
        public const int MinM5Bars = 600;
        public const int MinM15Bars = 200;

        public static bool IsCrypto(string symbol)
        {
            string s = symbol.ToUpperInvariant();
            return s.StartsWith("BTC") || s.StartsWith("ETH") || s.StartsWith("LTC") || s.StartsWith("XRP") || s.StartsWith("SOL");
        }

        public sealed class M5Indicators
        {
            public readonly double[] Ema9, Ema21, Ema50, Rsi, Atr;
            public M5Indicators(BarSeries m5)
            {
                Ema9 = Ind.Ema(m5.C, EmaFast);
                Ema21 = Ind.Ema(m5.C, EmaMid);
                Ema50 = Ind.Ema(m5.C, EmaSlow);
                Rsi = Ind.Rsi(m5.C, RsiPeriod);
                Atr = Ind.Atr(m5.H, m5.L, m5.C, AtrPeriod);
            }
        }

        public sealed class HigherTf
        {
            public readonly BarSeries M15, M1;
            public readonly double[] Ema50M15, AtrM1;
            public HigherTf(BarSeries m15, BarSeries m1)
            {
                M15 = m15;
                M1 = m1;
                Ema50M15 = Ind.Ema(m15.C, EmaSlow);
                AtrM1 = Ind.Atr(m1.H, m1.L, m1.C, AtrPeriod);
            }
        }

        public static bool SessionBlocked(DateTime ts, bool crypto)
        {
            int minute = ts.Hour * 60 + ts.Minute;
            DayOfWeek d = ts.DayOfWeek;
            if (crypto) return d == DayOfWeek.Friday && minute >= 20 * 60 + 30 && minute < 22 * 60 + 30;
            if (minute >= 20 * 60 + 45 && minute < 22 * 60 + 15) return true;
            if (d == DayOfWeek.Friday && minute >= 20 * 60) return true;
            if (d == DayOfWeek.Sunday && minute < 23 * 60 + 30) return true;
            return d == DayOfWeek.Saturday;
        }

        public static int SessionPoints(DateTime ts)
        {
            int h = ts.Hour;
            if (h >= 12 && h < 16) return 10;
            if ((h >= 7 && h < 12) || (h >= 16 && h < 20)) return 7;
            return 3;
        }

        public static string SessionName(DateTime ts)
        {
            int h = ts.Hour;
            if (h >= 7 && h < 12) return "london";
            if (h >= 12 && h < 16) return "overlap";
            if (h >= 16 && h < 21) return "newyork";
            return "asia";
        }

        // Index of the last bar whose open time <= t (or -1).
        private static int LastAtOrBefore(DateTime[] times, DateTime t)
        {
            int lo = 0, hi = times.Length - 1, ans = -1;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                if (times[mid] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
            }
            return ans;
        }

        public static int M15Bias(HigherTf tf, DateTime m5Close)
        {
            // last M15 bar with open + 15m <= M5 close
            int j = LastAtOrBefore(tf.M15.T, m5Close.AddMinutes(-15));
            if (j < EmaSlow || j < M15SlopeBars) return 0;
            bool above = tf.M15.C[j] > tf.Ema50M15[j];
            double slope = tf.Ema50M15[j] - tf.Ema50M15[j - M15SlopeBars];
            if (above && slope > 0) return 1;
            if (!above && slope < 0) return -1;
            return 0;
        }

        public static bool M1Spike(HigherTf tf, DateTime m5Open)
        {
            int k = LastAtOrBefore(tf.M1.T, m5Open.AddMinutes(4));
            if (k < 0) return false;
            int prev = Math.Max(0, k - 1);
            return (tf.M1.H[k] - tf.M1.L[k]) > M1SpikeMult * tf.AtrM1[prev];
        }

        public static double AtrRank(double[] atr, int i)
        {
            if (i < AtrRankWindow - 1) return double.NaN;
            int cnt = 0;
            for (int k = i - AtrRankWindow + 1; k <= i; k++) if (atr[k] <= atr[i]) cnt++;
            return cnt / (double)AtrRankWindow;
        }

        /// Advance the state machine on closed M5 bar i and return candidates that
        /// pass the hard filters. spreadPx = NaN means "unknown" (warm-up/replay):
        /// the spread filter is then skipped and the spread score uses 0.
        public static List<Candidate> Step(SignalState st, BarSeries m5, M5Indicators ind, HigherTf tf, int i, double spreadPx, bool crypto)
        {
            var result = new List<Candidate>();
            if (i < Warmup || i >= m5.Count) return result;
            double a = ind.Atr[i];
            if (!(a > 0)) return result;
            DateTime ts = m5.T[i].AddMinutes(5);

            double hh = double.MinValue, ll = double.MaxValue;
            for (int k = i - BreakoutLookback; k < i; k++) { hh = Math.Max(hh, m5.H[k]); ll = Math.Min(ll, m5.L[k]); }

            var found = new List<Tuple<int, string, double>>();
            for (int s = 0; s < 2; s++)
            {
                int side = s == 0 ? 1 : -1;
                if (st.PendActive[s])
                {
                    double level = st.PendLevel[s];
                    int b = st.PendBar[s];
                    if (i - b > RetestWindow || (level - m5.C[i]) * side > BreakoutFailAtr * a)
                    {
                        st.PendActive[s] = false;
                    }
                    else
                    {
                        bool touched = side > 0 ? m5.L[i] <= level + RetestToleranceAtr * a : m5.H[i] >= level - RetestToleranceAtr * a;
                        bool beyond = (m5.C[i] - level) * side > 0 && (m5.C[i] - m5.O[i]) * side > 0;
                        if (touched && beyond && i > b)
                        {
                            double anchor = side > 0 ? Math.Min(m5.L[i], level) : Math.Max(m5.H[i], level);
                            found.Add(Tuple.Create(side, SetupBreakoutRetest, anchor));
                            st.PendActive[s] = false;
                        }
                    }
                }
                double levelNow = side > 0 ? hh : ll;
                if ((m5.C[i] - levelNow) * side > BreakoutMarginAtr * a)
                {
                    st.PendActive[s] = true;
                    st.PendLevel[s] = levelNow;
                    st.PendBar[s] = i;
                }
            }

            for (int s = 0; s < 2; s++)
            {
                int side = s == 0 ? 1 : -1;
                if ((ind.Ema9[i] - ind.Ema21[i]) * side <= 0) continue;
                bool zone = side > 0 ? m5.L[i] <= ind.Ema21[i] + PullbackZoneAtr * a : m5.H[i] >= ind.Ema21[i] - PullbackZoneAtr * a;
                bool reclaim = (m5.C[i] - ind.Ema9[i]) * side > 0 && (m5.C[i] - m5.O[i]) * side > 0;
                double rNow = side > 0 ? ind.Rsi[i] : 100 - ind.Rsi[i];
                double rPrev = side > 0 ? ind.Rsi[i - 1] : 100 - ind.Rsi[i - 1];
                double rMin = double.MaxValue;
                for (int k = i - 4; k < i; k++) rMin = Math.Min(rMin, side > 0 ? ind.Rsi[k] : 100 - ind.Rsi[k]);
                if (zone && reclaim && rNow > rPrev && rNow >= 45 && rNow <= 70 && rMin <= 52)
                {
                    double anchor = side > 0 ? double.MaxValue : double.MinValue;
                    for (int k = i - 3; k <= i; k++) anchor = side > 0 ? Math.Min(anchor, m5.L[k]) : Math.Max(anchor, m5.H[k]);
                    found.Add(Tuple.Create(side, SetupPullback, anchor));
                }
            }
            if (found.Count == 0) return result;

            if (SessionBlocked(ts, crypto) || M1Spike(tf, m5.T[i])) return result;
            if (!double.IsNaN(spreadPx) && spreadPx > MaxSpreadAtr * a) return result;
            int bias = M15Bias(tf, ts);
            double rank = AtrRank(ind.Atr, i);

            foreach (var f in found)
            {
                int side = f.Item1;
                if (bias != side || (ind.Ema9[i] - ind.Ema21[i]) * side <= 0) continue;
                var c = new Candidate { Time = ts, Side = side, Setup = f.Item2, Anchor = f.Item3, Atr = a, Rsi = ind.Rsi[i], Ref = m5.C[i], Session = SessionName(ts) };
                c.Score = Score(side, f.Item2, m5, ind, i, rank, spreadPx, ts, out c.ComponentText);
                result.Add(c);
            }
            return result;
        }

        public static int Score(int side, string setup, BarSeries m5, M5Indicators ind, int i, double rank, double spreadPx, DateTime ts, out string text)
        {
            int stack = (ind.Ema21[i] - ind.Ema50[i]) * side > 0 ? 20 : 0;
            double r = side > 0 ? ind.Rsi[i] : 100 - ind.Rsi[i];
            int rsi = (r >= 52 && r <= 68) ? 15 : ((r >= 48 && r <= 75) ? 8 : 0);
            int regime = (rank >= 0.3 && rank <= 0.9) ? 15 : ((rank >= 0.15 && rank <= 0.97) ? 7 : 0);
            double sa = double.IsNaN(spreadPx) ? 1 : spreadPx / ind.Atr[i];
            int spread = sa <= 0.05 ? 15 : (sa <= 0.10 ? 8 : 0);
            double rng = m5.H[i] - m5.L[i];
            double body = Math.Abs(m5.C[i] - m5.O[i]);
            double pos = rng > 0 ? (m5.C[i] - m5.L[i]) / rng : 0.5;
            if (side < 0) pos = 1 - pos;
            bool goodBody = rng > 0 && body / rng >= 0.5;
            int candle = (goodBody && pos >= 0.7) ? 15 : (pos >= 0.6 ? 7 : 0);
            int session = SessionPoints(ts);
            int setupPts = setup == SetupBreakoutRetest ? 10 : 5;
            text = string.Format(CultureInfo.InvariantCulture, "stack={0};rsi={1};atr_regime={2};spread={3};candle={4};session={5};setup={6}",
                stack, rsi, regime, spread, candle, session, setupPts);
            return stack + rsi + regime + spread + candle + session + setupPts;
        }
    }

    // ==================================================================== execution safety (pure, tested)
    public sealed class GateInput
    {
        public bool IsLive;
        public long AccountNumber;
        public long ExpectedAccount;
        public string Broker;
        public string ExpectedBroker;
        public string Symbol;
        public bool DemoTradingRequested;
        public string ActivationCode;
        public bool ExperimentApproved;
        public string Experiment = ExecutionGate.XauExperiment;   // which experiment's rules apply
    }

    public static class ExecutionGate
    {
        public const string ExperimentSymbol = "XAUUSD";
        public const string RequiredActivationCode = "fwd-xau-001";
        public const string XauExperiment = "fwd-xau-001";
        public const string CopyExperiment = "fwd-tdn-001";
        public const string CopyActivationCode = "fwd-tdn-001";

        /// <summary>null = orders allowed; otherwise the reason the bot must stay SignalsOnly.</summary>
        public static string Evaluate(GateInput g)
        {
            if (g == null) return "no gate input";
            if (g.IsLive) return "LIVE account: order execution is prohibited";
            if (!g.DemoTradingRequested) return "SignalsOnly requested";
            if (!g.ExperimentApproved) return "forward experiment not approved in code";
            bool copy = g.Experiment == CopyExperiment;
            if (!copy && g.Experiment != XauExperiment) return "unknown experiment";
            if ((g.ActivationCode ?? "").Trim() != (copy ? CopyActivationCode : RequiredActivationCode))
                return copy ? "copy activation code not entered" : "activation code not entered";
            if (g.ExpectedAccount <= 0) return "expected demo account number not set";
            if (g.AccountNumber != g.ExpectedAccount) return "account number does not match the expected demo account";
            string want = Norm(g.ExpectedBroker);
            if (want.Length == 0 || Norm(g.Broker).IndexOf(want, StringComparison.Ordinal) < 0) return "broker does not match";
            if (copy)
            {
                if (string.IsNullOrWhiteSpace(g.Symbol)) return "no symbol";
            }
            else if (!string.Equals((g.Symbol ?? "").Trim(), ExperimentSymbol, StringComparison.OrdinalIgnoreCase))
                return "symbol is not part of the forward experiment";
            return null;
        }

        private static string Norm(string s)
        {
            return new string((s ?? "").ToLowerInvariant().Where(char.IsLetterOrDigit).ToArray());
        }
    }

    public sealed class RiskInput
    {
        public double DayStartBalance, RealizedToday, OpenRisk, NewRisk, DailyLossPercent;
        public int OwnPositions, MaxPositions, ForeignPositionsOnSymbol, ConsecutiveLosses, MaxConsecutiveLosses;
        public bool KillSwitchToday;
    }

    public static class ForwardRules
    {
        public const double MaxRiskPercent = 0.25;
        public const int MaxPositions = 1;
        public const double MaxDailyLossPercent = 1.0;
        public const int MaxConsecutiveLosses = 2;

        public static double ClampRisk(double requested)
        {
            if (double.IsNaN(requested) || requested <= 0) return 0;
            return Math.Min(requested, MaxRiskPercent);
        }

        /// <summary>Losses at the end of the closed-trade list (ordered oldest to newest).</summary>
        public static int ConsecutiveLosses(IList<double> netOldToNew)
        {
            int n = 0;
            for (int i = netOldToNew.Count - 1; i >= 0; i--)
            {
                if (netOldToNew[i] < 0) n++;
                else break;
            }
            return n;
        }

        /// <summary>null = a new position may be opened.</summary>
        public static string RiskCheck(RiskInput r)
        {
            int maxPos = Math.Min(Math.Max(r.MaxPositions, 1), MaxPositions);
            int maxLoss = Math.Min(Math.Max(r.MaxConsecutiveLosses, 1), MaxConsecutiveLosses);
            double dailyPct = Math.Min(r.DailyLossPercent, MaxDailyLossPercent);
            double limit = r.DayStartBalance * dailyPct / 100.0;
            if (r.KillSwitchToday) return "daily equity kill switch triggered";
            if (r.ConsecutiveLosses >= maxLoss) return r.ConsecutiveLosses + " consecutive losses: halted";
            if (r.OwnPositions >= maxPos) return "max positions open";
            if (r.ForeignPositionsOnSymbol > 0) return "another (manual or foreign) position is open on this symbol";
            if (!(r.NewRisk > 0) || !(limit > 0)) return "invalid risk";
            if (-r.RealizedToday >= limit) return "daily loss limit reached";
            if (-r.RealizedToday + r.OpenRisk + r.NewRisk > limit) return "would exceed daily loss budget including open risk";
            return null;
        }
    }

    public sealed class SizeResult
    {
        public double Units, StopPips, RiskBudget, CashRisk;
    }

    public static class Sizing
    {
        /// <summary>Fixed-fractional sizing: depends only on balance, the capped risk % and the stop distance.
        /// The stop is rounded UP to the instrument's tick (the broker places stops on the tick grid; rounding up means the
        /// stop the broker sets is the stop that was sized) and units DOWN to the volume step, so cash risk never exceeds
        /// the budget. tickSize <= 0 falls back to 0.1 pip.</summary>
        public static SizeResult Compute(double balance, double riskPercent, double stopDistancePx, double pipSize,
                                         double pipValuePerUnit, double volMin, double volStep, double volMax, double tickSize = 0)
        {
            var r = new SizeResult();
            double pct = ForwardRules.ClampRisk(riskPercent);
            r.RiskBudget = balance * pct / 100.0;
            if (!(balance > 0) || !(stopDistancePx > 0) || !(pipSize > 0) || !(pipValuePerUnit > 0) || !(volStep > 0)) return r;
            r.StopPips = CeilPips(stopDistancePx, pipSize, tickSize);
            double raw = r.RiskBudget / (r.StopPips * pipValuePerUnit);
            double units = Math.Floor(raw / volStep + 1e-9) * volStep;
            if (volMax > 0) units = Math.Min(units, volMax);
            if (units < volMin) return r;
            r.Units = units;
            r.CashRisk = units * r.StopPips * pipValuePerUnit;
            return r;
        }

        private static double Tick(double pipSize, double tickSize)
        {
            return tickSize > 0 ? tickSize : pipSize / 10.0;
        }

        /// Distance rounded UP to whole ticks, expressed in pips (stops: the sized distance is never smaller than the broker's).
        public static double CeilPips(double distancePx, double pipSize, double tickSize)
        {
            double t = Tick(pipSize, tickSize);
            return Math.Ceiling(distancePx / t - 1e-7) * t / pipSize;
        }

        /// Distance rounded DOWN to whole ticks, expressed in pips (used for targets and test stops).
        public static double FloorPips(double distancePx, double pipSize, double tickSize)
        {
            double t = Tick(pipSize, tickSize);
            return Math.Floor(distancePx / t + 1e-7) * t / pipSize;
        }
    }

    // ==================================================================== execution test planning (pure, tested)
    public sealed class TestInput
    {
        public string GateReason;
        public bool AlreadyExecuted, TradingEnabled, SessionBlocked;
        public int ConflictingPositions;
        public double RiskBase, RiskPercent, Atr, Spread, Bid, Ask, MinVolume, PipSize, PipValue, CommissionRate, TickSize;
    }

    public sealed class TestPlan
    {
        public string Reason;                 // null = the single test order may be sent
        public double Budget, StopDistance, StopPips, TpPips, MaxLoss, RequestedPrice;
    }

    public static class ExecutionTest
    {
        public const string TestId = "xtest-001";
        public const string Label = "TDS-XTEST";

        /// One BUY at the broker's minimum volume. Stop = min(1 x ATR(M5), the largest distance whose loss at the stop,
        /// INCLUDING round-trip commission, stays within 95% of the 0.25% budget); take-profit at the same distance.
        public static TestPlan Plan(TestInput t)
        {
            var p = new TestPlan();
            p.Budget = t.RiskBase * ForwardRules.ClampRisk(t.RiskPercent) / 100.0;
            p.RequestedPrice = t.Ask;
            if (t.GateReason != null) { p.Reason = "execution gate: " + t.GateReason; return p; }
            if (t.AlreadyExecuted) { p.Reason = "the one-time execution test was already executed (label " + Label + " found)"; return p; }
            if (t.ConflictingPositions > 0) { p.Reason = "a bot position or an XAUUSD position is open"; return p; }
            if (!t.TradingEnabled) { p.Reason = "symbol trading disabled"; return p; }
            if (t.SessionBlocked) { p.Reason = "session blocked (rollover / weekend): spreads unrepresentative"; return p; }
            if (!(t.Bid > 0) || !(t.Ask > t.Bid) || !(t.PipSize > 0) || !(t.PipValue > 0) || !(t.MinVolume > 0) || !(t.Atr > 0))
            { p.Reason = "no valid live quote, volume or ATR"; return p; }
            if (t.Spread > 0.25 * t.Atr) { p.Reason = "spread above 0.25 x ATR(M5)"; return p; }
            double perPrice = t.MinVolume * t.PipValue / t.PipSize;          // $ loss per 1.0 of price at minimum volume
            double commission = 2 * t.CommissionRate * t.Ask * t.MinVolume;  // round-trip estimate
            double maxStop = (0.95 * p.Budget - commission) / perPrice;
            double stop = Math.Min(t.Atr, maxStop);
            if (stop < 3 * t.Spread || stop <= 0)
            { p.Reason = "minimum volume cannot respect the 0.25% risk limit with a stop of at least 3 x spread"; return p; }
            p.StopPips = Sizing.FloorPips(stop, t.PipSize, t.TickSize);
            p.TpPips = p.StopPips;
            p.StopDistance = p.StopPips * t.PipSize;
            p.MaxLoss = perPrice * p.StopDistance + commission;
            if (p.MaxLoss > p.Budget) { p.Reason = "maximum loss exceeds budget"; return p; }
            return p;
        }
    }

    // ==================================================================== TradeDen copy rules (pure, tested)
    public sealed class CopySignal
    {
        public string SignalId, Source, Strategy, Symbol, Timeframe, ConfirmedAt, TimeExitAt;
        public int Side;
        public double Entry, Stop, Target;

        private static string Field(string json, string key)
        {
            Match m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(\"((?:[^\"\\\\]|\\\\.)*)\"|(-?[0-9][0-9.eE+-]*)|null|true|false)");
            if (!m.Success) return null;
            return m.Groups[2].Success && m.Groups[1].Value.StartsWith("\"") ? m.Groups[2].Value : (m.Groups[3].Success ? m.Groups[3].Value : null);
        }

        private static double Num(string json, string key)
        {
            double v;
            return double.TryParse(Field(json, key), NumberStyles.Float, CultureInfo.InvariantCulture, out v) ? v : double.NaN;
        }

        public static CopySignal Parse(string json)
        {
            var c = new CopySignal
            {
                SignalId = Field(json, "signal_id"), Source = Field(json, "source"), Strategy = Field(json, "strategy") ?? "",
                Symbol = (Field(json, "symbol") ?? "").ToUpperInvariant(), Timeframe = Field(json, "timeframe") ?? "",
                ConfirmedAt = Field(json, "confirmed_at"), TimeExitAt = Field(json, "time_exit_at") ?? "",
                Entry = Num(json, "entry"), Stop = Num(json, "stop"), Target = Num(json, "target")
            };
            string side = Field(json, "side");
            c.Side = side == "buy" ? 1 : side == "sell" ? -1 : 0;
            if (string.IsNullOrEmpty(c.SignalId) || string.IsNullOrEmpty(c.Symbol) || c.Side == 0 || string.IsNullOrEmpty(c.ConfirmedAt)) return null;
            return c;
        }
    }

    public sealed class CopyCheck
    {
        public string Reason;          // null = may proceed to sizing and risk checks
        public double StopDistance, TargetDistance, AgeSeconds;
    }

    public static class CopyRules
    {
        public static readonly Dictionary<string, string[]> AliasMap = new Dictionary<string, string[]>
        {
            { "XAUUSD", new[] { "XAUUSD", "GOLD" } }, { "NAS100", new[] { "NAS100", "US100", "USTEC", "NAS" } },
            { "US500", new[] { "US500", "SPX500", "SP500" } }, { "GER40", new[] { "GER40", "DE40", "DAX40" } },
            { "XAGUSD", new[] { "XAGUSD", "SILVER" } }, { "BTCUSD", new[] { "BTCUSD" } }, { "ETHUSD", new[] { "ETHUSD" } }
        };

        public static IEnumerable<string> Aliases(string symbol)
        {
            string[] a;
            return AliasMap.TryGetValue(symbol, out a) ? a : new[] { symbol };
        }

        /// Freshness, price drift, stop/target geometry and cost checks. Entry is at the CURRENT price (ask for buys,
        /// bid for sells); the signal's absolute stop and target are kept.
        public static CopyCheck Validate(CopySignal sig, DateTime nowUtc, int maxAgeSeconds, double bid, double ask, double spread,
                                         double commissionRate, double maxCostToRisk)
        {
            var c = new CopyCheck();
            DateTime conf;
            if (!DateTime.TryParse(sig.ConfirmedAt, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out conf))
            { c.Reason = "unreadable confirmation time"; return c; }
            c.AgeSeconds = (nowUtc - conf).TotalSeconds;
            if (c.AgeSeconds > maxAgeSeconds) { c.Reason = "signal too old (" + Math.Round(c.AgeSeconds) + "s)"; return c; }
            if (c.AgeSeconds < -120) { c.Reason = "signal time is in the future"; return c; }
            if (!(bid > 0) || !(ask >= bid)) { c.Reason = "no valid live quote"; return c; }
            if (double.IsNaN(sig.Entry) || double.IsNaN(sig.Stop) || double.IsNaN(sig.Target)) { c.Reason = "missing entry/stop/target"; return c; }
            int side = sig.Side;
            double px = side > 0 ? ask : bid;
            double planned = (sig.Entry - sig.Stop) * side;
            if (planned <= 0 || (sig.Target - sig.Entry) * side <= 0) { c.Reason = "stop/target on the wrong side of entry"; return c; }
            c.StopDistance = (px - sig.Stop) * side;
            c.TargetDistance = (sig.Target - px) * side;
            if (c.StopDistance <= 0) { c.Reason = "price already beyond the stop"; return c; }
            if (c.TargetDistance <= 0) { c.Reason = "price already beyond the target"; return c; }
            if (Math.Abs(px - sig.Entry) > 0.25 * planned) { c.Reason = "price moved more than 0.25R from the signal entry"; return c; }
            if (c.TargetDistance < 0.5 * c.StopDistance) { c.Reason = "remaining reward below 0.5R"; return c; }
            double cost = spread + 2 * commissionRate * px;
            if (cost / c.StopDistance > maxCostToRisk) { c.Reason = "cost/risk " + (cost / c.StopDistance).ToString("0.00", CultureInfo.InvariantCulture) + " > " + maxCostToRisk; return c; }
            return c;
        }
    }

    // ==================================================================== JSON journal
    public sealed class JsonRecord
    {
        private readonly StringBuilder _sb = new StringBuilder("{");
        private readonly Dictionary<string, string> _strings = new Dictionary<string, string>();

        public string Str(string k)
        {
            string v;
            return _strings.TryGetValue(k, out v) ? v : null;
        }
        private bool _first = true;

        private JsonRecord Key(string k)
        {
            if (!_first) _sb.Append(',');
            _first = false;
            _sb.Append('"').Append(Escape(k)).Append("\":");
            return this;
        }

        public JsonRecord Add(string k, string v) { _strings[k] = v; Key(k); if (v == null) _sb.Append("null"); else _sb.Append('"').Append(Escape(v)).Append('"'); return this; }
        public JsonRecord Add(string k, double v) { Key(k); _sb.Append(double.IsNaN(v) || double.IsInfinity(v) ? "null" : v.ToString("R", CultureInfo.InvariantCulture)); return this; }
        public JsonRecord Add(string k, int v) { Key(k); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); return this; }
        public JsonRecord Add(string k, long v) { Key(k); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); return this; }
        public JsonRecord Add(string k, bool v) { Key(k); _sb.Append(v ? "true" : "false"); return this; }
        public JsonRecord Add(string k, DateTime v) { return Add(k, v.ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture) + "Z"); }
        public JsonRecord AddRaw(string k, string json) { Key(k); _sb.Append(json); return this; }

        public override string ToString() { return _sb.ToString() + "}"; }

        private static string Escape(string s)
        {
            var b = new StringBuilder(s.Length + 8);
            foreach (char ch in s)
            {
                switch (ch)
                {
                    case '"': b.Append("\\\""); break;
                    case '\\': b.Append("\\\\"); break;
                    case '\n': b.Append("\\n"); break;
                    case '\r': b.Append("\\r"); break;
                    case '\t': b.Append("\\t"); break;
                    default:
                        if (ch < 0x20) b.Append("\\u").Append(((int)ch).ToString("x4")); else b.Append(ch);
                        break;
                }
            }
            return b.ToString();
        }
    }

    public sealed class Journal
    {
        private readonly string _folder;
        private readonly string _fixedName;

        public Journal(string folder, string fixedName)
        {
            _folder = folder;
            _fixedName = fixedName;
            Directory.CreateDirectory(folder);
        }

        public bool Write(JsonRecord r)
        {
            string name = (_fixedName ?? "journal-" + DateTime.UtcNow.ToString("yyyyMMdd", CultureInfo.InvariantCulture)) + ".jsonl";
            for (int attempt = 0; attempt < 3; attempt++)
            {
                try
                {
                    System.IO.File.AppendAllText(Path.Combine(_folder, name), r.ToString() + "\n", new UTF8Encoding(false));
                    return true;
                }
                catch (IOException)
                {
                    System.Threading.Thread.Sleep(50);   // e.g. a OneDrive or reader lock; retry briefly
                }
                catch (UnauthorizedAccessException)
                {
                    return false;
                }
            }
            return false;
        }
    }
}
