// TradeDen Collector (tdc-1.0) - cTrader cBot, DATA ONLY
//
// Records market data and account state from the running cTrader desktop app into local files that the
// Trading Hub engine reads (backend/ctrader_feed.py -> /api/ctrader/*).
//
// This cBot contains NO order code: it never places, modifies, cancels or closes orders or positions,
// never changes account settings and never moves funds. ctrader_scalper/tests/test_collector.py fails the
// build if any trading API call appears in this file.
//
// It refuses to run on a LIVE account unless "Allow live account" is set (default: off, demo only).
//
// Output (Documents\TradeDenScalper\collector\ unless "Output folder" is set):
//   status.json                       overwritten every few seconds: account, quotes, open positions, freshness
//   account-YYYYMMDD.jsonl            balance/equity snapshot every 60 s
//   deals.jsonl                       closed deals from cTrader history (full history at start, then each close)
//   bars\<SYMBOL>\M1-YYYYMMDD.jsonl   closed M1 bars (backfill at start, then each new bar)
//   events.jsonl                      start / stop / symbol-missing records
//
// Written in C# 5 syntax so it compiles both in cTrader and with the repository's offline check.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeDenCollector : Robot
    {
        public const string CollectorVersion = "tdc-1.0";

        // Product name = broker aliases tried in order. IC Markets names: NAS100 -> USTEC, US500 -> US500, GER40 -> DE40.
        [Parameter("Symbols (NAME=alias|alias, ...)", DefaultValue = "XAUUSD,BTCUSD,ETHUSD,NAS100=USTEC|NAS100|US100,US500=US500|SPX500|US500.cash,GER40=DE40|GER40|DAX40,GBPJPY,EURUSD,GBPUSD", Group = "Collector")]
        public string SymbolList { get; set; }

        [Parameter("Status interval (seconds)", DefaultValue = 5, MinValue = 1, MaxValue = 60, Group = "Collector")]
        public int StatusSeconds { get; set; }

        [Parameter("M1 bars to backfill at start", DefaultValue = 1440, MinValue = 0, MaxValue = 20000, Group = "Collector")]
        public int BackfillBars { get; set; }

        [Parameter("Output folder (blank = Documents\\TradeDenScalper\\collector)", DefaultValue = "", Group = "Collector")]
        public string OutputFolder { get; set; }

        [Parameter("Allow live account", DefaultValue = false, Group = "Safety")]
        public bool AllowLive { get; set; }

        private sealed class Feed
        {
            public string Name;
            public string BrokerName;
            public Symbol Symbol;
            public Bars M1;
            public DateTime LastTick = DateTime.MinValue;
            public DateTime LastBarWritten = DateTime.MinValue;
        }

        private readonly List<Feed> _feeds = new List<Feed>();
        private readonly List<string> _missing = new List<string>();
        private string _folder;
        private string _runId;
        private DateTime _lastAccountLine = DateTime.MinValue;
        private int _writeErrors;
        private bool _refused;

        protected override void OnStart()
        {
            _runId = DateTime.UtcNow.ToString("yyyyMMdd'T'HHmmss", CultureInfo.InvariantCulture) + "-" + Guid.NewGuid().ToString("N").Substring(0, 6);
            _folder = string.IsNullOrWhiteSpace(OutputFolder)
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "TradeDenScalper", "collector")
                : OutputFolder;
            Directory.CreateDirectory(Path.Combine(_folder, "bars"));

            if (Account.IsLive && !AllowLive)
            {
                _refused = true;
                Append("events.jsonl", Rec("refused").Add("reason", "LIVE account and 'Allow live account' is off").Add("is_live", true));
                WriteStatus("refused_live");
                Print("TradeDen Collector: LIVE account detected; collector stopped (data-only, demo by default).");
                Stop();
                return;
            }

            foreach (string raw in (SymbolList ?? "").Split(','))
            {
                string item = raw.Trim();
                if (item.Length == 0) continue;
                string name = item, aliases = item;
                int eq = item.IndexOf('=');
                if (eq > 0) { name = item.Substring(0, eq).Trim(); aliases = item.Substring(eq + 1); }
                Feed f = Resolve(name.ToUpperInvariant(), aliases.Split('|'));
                if (f == null) { _missing.Add(name.ToUpperInvariant()); continue; }
                _feeds.Add(f);
            }

            Append("events.jsonl", Rec("start").Add("is_live", Account.IsLive).Add("account", MaskedAccount())
                .Add("broker", Account.BrokerName).Add("currency", Account.Asset.Name)
                .Add("symbols", string.Join(",", _feeds.Select(x => x.Name + "=" + x.BrokerName).ToArray()))
                .Add("missing", string.Join(",", _missing.ToArray())));

            foreach (Feed f in _feeds) Backfill(f);
            WriteAllDeals();
            Positions.Closed += OnPositionClosed;

            WriteStatus("running");
            WriteAccountLine();
            Timer.Start(StatusSeconds);
            Print("TradeDen Collector running (data only, no orders): " + _feeds.Count + " symbols, missing: " + string.Join(",", _missing.ToArray()) + ". Output: " + _folder);
        }

        protected override void OnTimer()
        {
            if (_refused) return;
            WriteStatus("running");
            if ((DateTime.UtcNow - _lastAccountLine).TotalSeconds >= 60) WriteAccountLine();
        }

        protected override void OnStop()
        {
            if (_refused) return;
            Append("events.jsonl", Rec("stop"));
            WriteStatus("stopped");
        }

        // ------------------------------------------------------------------ symbols and bars
        private Feed Resolve(string name, string[] aliases)
        {
            foreach (string a in aliases)
            {
                string cand = a.Trim();
                if (cand.Length == 0) continue;
                Symbol s;
                try { s = Symbols.Exists(cand) ? Symbols.GetSymbol(cand) : null; } catch (Exception) { s = null; }
                if (s == null) continue;
                Feed f = new Feed { Name = name, BrokerName = cand, Symbol = s };
                f.M1 = MarketData.GetBars(TimeFrame.Minute, cand);
                Feed captured = f;
                s.Tick += delegate { captured.LastTick = DateTime.UtcNow; };
                f.M1.BarOpened += delegate { WriteClosedBars(captured); };
                return f;
            }
            return null;
        }

        private void Backfill(Feed f)
        {
            int guard = 0;
            while (f.M1.Count < BackfillBars + 1 && guard++ < 20)
            {
                if (f.M1.LoadMoreHistory() <= 0) break;
            }
            int last = f.M1.Count - 2;                  // the newest bar is still forming
            int first = Math.Max(0, last - BackfillBars + 1);
            for (int i = first; i <= last; i++) WriteBar(f, i);
        }

        private void WriteClosedBars(Feed f)
        {
            int last = f.M1.Count - 2;
            if (last < 0) return;
            int i = last;
            while (i > 0 && f.M1.OpenTimes[i - 1] > f.LastBarWritten && last - i < 30) i--;   // catch up after gaps
            for (; i <= last; i++) WriteBar(f, i);
        }

        private void WriteBar(Feed f, int i)
        {
            DateTime t = f.M1.OpenTimes[i];
            if (t <= f.LastBarWritten) return;
            JsonRec r = new JsonRec().Add("t", t).Add("o", f.M1.OpenPrices[i]).Add("h", f.M1.HighPrices[i])
                .Add("l", f.M1.LowPrices[i]).Add("c", f.M1.ClosePrices[i]).Add("v", f.M1.TickVolumes[i]);
            string dir = Path.Combine(_folder, "bars", f.Name);
            Directory.CreateDirectory(dir);
            if (AppendTo(Path.Combine(dir, "M1-" + t.ToString("yyyyMMdd", CultureInfo.InvariantCulture) + ".jsonl"), r))
                f.LastBarWritten = t;
        }

        // ------------------------------------------------------------------ account and deals
        private void WriteAccountLine()
        {
            _lastAccountLine = DateTime.UtcNow;
            JsonRec r = Rec("account").Add("balance", Account.Balance).Add("equity", Account.Equity)
                .Add("margin", Account.Margin).Add("free_margin", Account.FreeMargin)
                .Add("unrealized_net", Account.UnrealizedNetProfit).Add("open_positions", Positions.Count);
            Append("account-" + DateTime.UtcNow.ToString("yyyyMMdd", CultureInfo.InvariantCulture) + ".jsonl", r);
        }

        private void WriteAllDeals()
        {
            var sb = new StringBuilder();
            int n = 0;
            foreach (HistoricalTrade h in History)
            {
                sb.Append(Deal(h, "history").ToString()).Append('\n');
                n++;
            }
            if (n > 0) AppendRaw(Path.Combine(_folder, "deals.jsonl"), sb.ToString());
        }

        private void OnPositionClosed(PositionClosedEventArgs args)
        {
            HistoricalTrade match = null;
            foreach (HistoricalTrade h in History) if (h.PositionId == args.Position.Id) match = h;
            if (match != null) Append("deals.jsonl", Deal(match, "close_event").Add("close_reason", args.Reason.ToString()));
            WriteStatus("running");
            WriteAccountLine();
        }

        private JsonRec Deal(HistoricalTrade h, string source)
        {
            return new JsonRec().Add("closing_deal_id", h.ClosingDealId).Add("position_id", h.PositionId)
                .Add("symbol", h.SymbolName).Add("side", h.TradeType == TradeType.Buy ? "buy" : "sell")
                .Add("volume_units", h.VolumeInUnits).Add("quantity_lots", h.Quantity)
                .Add("entry_time", h.EntryTime).Add("entry_price", h.EntryPrice)
                .Add("close_time", h.ClosingTime).Add("close_price", h.ClosingPrice)
                .Add("gross", h.GrossProfit).Add("commission", h.Commissions).Add("swap", h.Swap).Add("net", h.NetProfit)
                .Add("balance_after", h.Balance).Add("label", h.Label).Add("comment", h.Comment)
                .Add("source", source).Add("run_id", _runId);
        }

        // ------------------------------------------------------------------ status snapshot
        private void WriteStatus(string state)
        {
            DateTime now = DateTime.UtcNow;
            var quotes = new StringBuilder("[");
            bool first = true;
            foreach (Feed f in _feeds)
            {
                if (!first) quotes.Append(',');
                first = false;
                int lastClosed = f.M1.Count - 2;
                quotes.Append(new JsonRec().Add("symbol", f.Name).Add("broker_symbol", f.BrokerName)
                    .Add("bid", f.Symbol.Bid).Add("ask", f.Symbol.Ask).Add("spread", f.Symbol.Ask - f.Symbol.Bid)
                    .Add("digits", f.Symbol.Digits)
                    .Add("last_tick_utc", f.LastTick == DateTime.MinValue ? null : Iso(f.LastTick))
                    .Add("last_bar_utc", lastClosed >= 0 ? Iso(f.M1.OpenTimes[lastClosed]) : null).ToString());
            }
            quotes.Append(']');

            var pos = new StringBuilder("[");
            first = true;
            foreach (Position p in Positions)
            {
                if (!first) pos.Append(',');
                first = false;
                pos.Append(new JsonRec().Add("position_id", p.Id).Add("symbol", p.SymbolName)
                    .Add("side", p.TradeType == TradeType.Buy ? "buy" : "sell").Add("volume_units", p.VolumeInUnits)
                    .Add("entry_price", p.EntryPrice).Add("entry_time", p.EntryTime)
                    .Add("stop_loss", p.StopLoss.HasValue ? p.StopLoss.Value : double.NaN)
                    .Add("take_profit", p.TakeProfit.HasValue ? p.TakeProfit.Value : double.NaN)
                    .Add("net", p.NetProfit).Add("label", p.Label).ToString());
            }
            pos.Append(']');

            JsonRec r = new JsonRec().Add("v", CollectorVersion).Add("state", state).Add("written_at", now)
                .Add("server_time", Server.Time).Add("run_id", _runId).Add("running_mode", RunningMode.ToString())
                .Add("status_interval_seconds", StatusSeconds)
                .Add("is_live", Account.IsLive).Add("account", MaskedAccount()).Add("broker", Account.BrokerName)
                .Add("currency", Account.Asset.Name).Add("leverage", Account.PreciseLeverage)
                .Add("balance", Account.Balance).Add("equity", Account.Equity).Add("margin", Account.Margin)
                .Add("free_margin", Account.FreeMargin).Add("unrealized_net", Account.UnrealizedNetProfit)
                .Add("missing_symbols", string.Join(",", _missing.ToArray())).Add("write_errors", _writeErrors)
                .AddRaw("quotes", quotes.ToString()).AddRaw("positions", pos.ToString());

            string path = Path.Combine(_folder, "status.json");
            string tmp = path + ".tmp";
            try
            {
                System.IO.File.WriteAllText(tmp, r.ToString(), new UTF8Encoding(false));
                if (System.IO.File.Exists(path)) System.IO.File.Replace(tmp, path, null);
                else System.IO.File.Move(tmp, path);
            }
            catch (Exception)
            {
                try { System.IO.File.WriteAllText(path, r.ToString(), new UTF8Encoding(false)); }
                catch (Exception) { _writeErrors++; }
            }
        }

        // ------------------------------------------------------------------ helpers
        private string MaskedAccount()
        {
            string num = Account.Number.ToString(CultureInfo.InvariantCulture);
            return num.Length > 3 ? new string('*', num.Length - 3) + num.Substring(num.Length - 3) : "***";
        }

        private JsonRec Rec(string evt)
        {
            return new JsonRec().Add("v", CollectorVersion).Add("event", evt).Add("ts", DateTime.UtcNow).Add("run_id", _runId);
        }

        private static string Iso(DateTime t)
        {
            return t.ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture) + "Z";
        }

        private void Append(string file, JsonRec r) { AppendTo(Path.Combine(_folder, file), r); }

        private bool AppendTo(string path, JsonRec r) { return AppendRaw(path, r.ToString() + "\n"); }

        private bool AppendRaw(string path, string text)
        {
            for (int attempt = 0; attempt < 3; attempt++)
            {
                try
                {
                    System.IO.File.AppendAllText(path, text, new UTF8Encoding(false));
                    return true;
                }
                catch (IOException) { System.Threading.Thread.Sleep(50); }
                catch (UnauthorizedAccessException) { break; }
            }
            _writeErrors++;
            return false;
        }
    }

    public sealed class JsonRec
    {
        private readonly StringBuilder _sb = new StringBuilder("{");
        private bool _first = true;

        private void Key(string k)
        {
            if (!_first) _sb.Append(',');
            _first = false;
            _sb.Append('"').Append(Escape(k)).Append("\":");
        }

        public JsonRec Add(string k, string v) { Key(k); if (v == null) _sb.Append("null"); else _sb.Append('"').Append(Escape(v)).Append('"'); return this; }
        public JsonRec Add(string k, double v) { Key(k); _sb.Append(double.IsNaN(v) || double.IsInfinity(v) ? "null" : v.ToString("R", CultureInfo.InvariantCulture)); return this; }
        public JsonRec Add(string k, int v) { Key(k); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); return this; }
        public JsonRec Add(string k, long v) { Key(k); _sb.Append(v.ToString(CultureInfo.InvariantCulture)); return this; }
        public JsonRec Add(string k, bool v) { Key(k); _sb.Append(v ? "true" : "false"); return this; }
        public JsonRec Add(string k, DateTime v) { return Add(k, v.ToString("yyyy-MM-ddTHH:mm:ss.fff", CultureInfo.InvariantCulture) + "Z"); }
        public JsonRec AddRaw(string k, string json) { Key(k); _sb.Append(json); return this; }

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
}
