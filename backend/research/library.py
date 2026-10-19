"""TRADEden strategy research library (T-033): published and practitioner methodologies.

Each entry documents where an idea comes from, why it might work, testable rules, the data it
needs, whether TRADEden has that data, and what evidence exists. Published profitability is
NOT taken at face value: `evidence` records the claim, `caveats` what weakens it, and nothing
here is a result until the discovery workflow has tested it on our own data (research/discovery.py).

Sources are cited from the academic and practitioner literature as commonly referenced; claims
are summarised, not quoted. TradingView/open-source scripts are included as a category because
they are popular, with the standing caveat that published backtests there are frequently
in-sample, cost-free or repainting.

    python -m research.library list [--category CAT]
    python -m research.library search TERM
    python -m research.library show KEY
    python -m research.library export            (writes research/STRATEGY_LIBRARY.md)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Data TRADEden has: MT5 OHLC + tick volume + recorded spread for 16 CFDs (M15/H1/H4 since Aug 2024,
# D1 since Aug 2023, M1 ~3 months). Not available: real exchange volume, order book, historical swap
# rates, COT, options, fundamentals history, news/event calendar history.
AVAILABLE = {"OHLC", "tick_volume", "spread", "multi_instrument"}

LIBRARY: list[dict[str, Any]] = [
    # ---------------- trend following / momentum ----------------
    {"key": "tsmom", "name": "Time-series momentum", "category": "trend following",
     "source": "Moskowitz, Ooi & Pedersen (2012), 'Time series momentum', Journal of Financial Economics",
     "source_type": "academic", "rationale": "Past 1-12 month returns of futures predict future returns of the same asset (under-reaction then delayed over-reaction).",
     "rules": "Each period, long if the trailing lookback return > 0 else short; volatility-scaled positions; monthly/weekly rebalance.",
     "timeframes": ["D1", "W1"], "data": ["OHLC"],
     "evidence": "Strong across 58 futures over decades in the paper; replicated widely.",
     "caveats": "Monthly-horizon effect: two years of data give few independent observations; weaker since 2009 in several studies.",
     "implementation": "v6.weekly_tsmom", "prior_result": "V6 round 2: train-positive (60d), negative on validation; chosen 20d config failed on test (-0.04R)."},
    {"key": "trend_century", "name": "Multi-horizon trend following (century of evidence)", "category": "trend following",
     "source": "Hurst, Ooi & Pedersen (2017), 'A Century of Evidence on Trend-Following Investing', Journal of Portfolio Management",
     "source_type": "academic", "rationale": "Trend following has been profitable across 1880-2016 in many markets, especially in large market moves.",
     "rules": "Equal-weight 1, 3 and 12-month time-series momentum signals, volatility-scaled.",
     "timeframes": ["D1"], "data": ["OHLC"], "evidence": "Long-history backtest across asset classes.",
     "caveats": "Needs decades to evaluate; our 2-3 years cannot validate a monthly-horizon strategy.", "implementation": None,
     "prior_result": None},
    {"key": "xsmom_fx", "name": "Cross-sectional currency momentum", "category": "momentum",
     "source": "Menkhoff, Sarno, Schmeling & Schrimpf (2012), 'Currency momentum strategies', Journal of Financial Economics",
     "source_type": "academic", "rationale": "Currencies with high past returns keep outperforming those with low past returns for weeks to months.",
     "rules": "Rank currencies by past return; long winners, short losers; rebalance monthly.",
     "timeframes": ["D1"], "data": ["OHLC", "multi_instrument"],
     "evidence": "Significant excess returns in a broad cross-section of ~48 currencies.",
     "caveats": "Profits concentrated in less liquid currencies; our universe has 8 FX pairs, not 48 currencies.",
     "implementation": "v6_round3.cross_sectional_momentum", "prior_result": "V6 round 3: about zero on train, negative on validation (rejected)."},
    {"key": "ma_breakout_brock", "name": "Moving-average and trading-range breakout rules", "category": "trend following",
     "source": "Brock, Lakonishok & LeBaron (1992), 'Simple technical trading rules and the stochastic properties of stock returns', Journal of Finance; Sullivan, Timmermann & White (1999), 'Data-snooping, technical trading rule performance, and the bootstrap', Journal of Finance",
     "source_type": "academic", "rationale": "Simple MA crossovers and range breakouts appeared to predict DJIA returns 1897-1986.",
     "rules": "Long when price crosses above its N-day MA / breaks the N-day high; short on the opposite.",
     "timeframes": ["D1", "H1"], "data": ["OHLC"],
     "evidence": "Significant in-sample in 1992; Sullivan et al. found the best rules failed out-of-sample after controlling for data snooping.",
     "caveats": "Classic example of data snooping; included as a benchmark family.",
     "implementation": "v6.donchian_trend", "prior_result": "V6: H1 and H4 breakouts about zero after costs (rejected on train)."},
    {"key": "turtle", "name": "Turtle / Donchian channel breakout", "category": "trend following",
     "source": "Faith (2007), 'Way of the Turtle'; Donchian channel rules", "source_type": "practitioner book",
     "rationale": "Enter on 20/55-day highs or lows, exit on shorter opposite channel; captures large trends.",
     "rules": "Long on N-period high break, stop 2 ATR, exit on M-period low.", "timeframes": ["D1", "H4", "H1"], "data": ["OHLC"],
     "evidence": "Anecdotal: the 1980s Turtle traders' returns; later public tests show decay.", "caveats": "Survivorship and era effects.",
     "implementation": "v6.donchian_trend / v6.h4_donchian", "prior_result": "V6: rejected on train (about zero after costs)."},
    {"key": "supertrend", "name": "Supertrend (ATR trailing trend flip)", "category": "trend following",
     "source": "Practitioner indicator (Olivier Seban); among the most-used TradingView public strategies", "source_type": "TradingView / practitioner",
     "rationale": "Trades the direction of an ATR-band trailing stop; flips signal regime changes.",
     "rules": "Bands = (H+L)/2 +- k*ATR(n); trend flips when close crosses the active band; enter on flip, exit on next flip.",
     "timeframes": ["H1", "H4"], "data": ["OHLC"], "evidence": "Popular; public backtests are typically cost-free and in-sample.",
     "caveats": "No credible independent evidence found.", "implementation": "candidates.supertrend", "prior_result": None},
    {"key": "intraday_momentum", "name": "Market intraday momentum", "category": "session-based / momentum",
     "source": "Gao, Han, Li & Zhou (2018), 'Market intraday momentum', Journal of Financial Economics",
     "source_type": "academic", "rationale": "The first half-hour return of the S&P 500 (from the prior close) predicts the last half-hour return; attributed to late-informed traders and hedging.",
     "rules": "Sign of the return from prior close to session open + 30 min (here: session open to the penultimate hour); trade it into the close.",
     "timeframes": ["M15"], "data": ["OHLC"], "evidence": "Significant in SPY 1993-2013; also in other ETFs in follow-ups.",
     "caveats": "Our index CFDs trade nearly 24h; the cash-session open/close must be approximated by clock time.",
     "implementation": "candidates.intraday_momentum", "prior_result": None},
    # ---------------- mean reversion / reversal ----------------
    {"key": "bollinger_mr", "name": "Bollinger Band mean reversion in quiet regimes", "category": "mean reversion",
     "source": "Bollinger (2001), 'Bollinger on Bollinger Bands'; Chan (2013), 'Algorithmic Trading'", "source_type": "practitioner book",
     "rationale": "Stretched prices revert toward the mean when no trend is present.",
     "rules": "Fade a re-entry into the band after a close outside it, in flat-trend regimes; target the mean.",
     "timeframes": ["H1"], "data": ["OHLC"], "evidence": "Practitioner evidence; mean reversion at short horizons is documented in FX.",
     "caveats": "Regime-dependent; costs matter.", "implementation": "v6.bollinger_reversion",
     "prior_result": "V6 best: train +0.01, validation +0.07, test +0.07R (CI -0.07..+0.21), not significant after Holm."},
    {"key": "rsi2", "name": "Connors RSI(2) pullback", "category": "mean reversion",
     "source": "Connors & Alvarez (2008), 'Short Term Trading Strategies That Work'", "source_type": "practitioner book",
     "rationale": "Short, sharp pullbacks inside a long-term uptrend tend to reverse within days.",
     "rules": "Close above 200-period SMA and RSI(2) < 10 -> buy; exit when close > 5-period SMA (mirror for shorts).",
     "timeframes": ["D1", "H1"], "data": ["OHLC"], "evidence": "Strong in US equity indices 1990s-2000s in the authors' tests.",
     "caveats": "Equity-index specific; author-published tests; weaker in recent years per independent replications.",
     "implementation": "candidates.rsi2", "prior_result": None},
    {"key": "short_term_reversal", "name": "Short-term reversal after extreme bars", "category": "mean reversion",
     "source": "Lehmann (1990), 'Fads, martingales, and market efficiency', QJE; Jegadeesh (1990), 'Evidence of predictable behavior of security returns', Journal of Finance",
     "source_type": "academic", "rationale": "Liquidity-driven price pressure reverses at short horizons.",
     "rules": "Fade a bar whose return exceeds z standard deviations; exit after N bars.",
     "timeframes": ["H1"], "data": ["OHLC"], "evidence": "Documented for weekly stock returns; liquidity provision premium.",
     "caveats": "Closely related to bollinger_mr (whose test result is known): a test of this family is partly test-informed.",
     "implementation": None, "prior_result": None},
    {"key": "pairs", "name": "Pairs trading / cointegration (EURUSD-GBPUSD, XAU-XAG)", "category": "statistical arbitrage",
     "source": "Gatev, Goetzmann & Rouwenhorst (2006), 'Pairs trading: performance of a relative-value arbitrage rule', Review of Financial Studies; Vidyamurthy (2004)",
     "source_type": "academic", "rationale": "Prices of closely related assets diverge temporarily and converge.",
     "rules": "Trade the z-score of the spread/ratio; enter at |z| > 2, exit at 0.",
     "timeframes": ["H1", "D1"], "data": ["OHLC", "multi_instrument"],
     "evidence": "Profitable 1962-2002 in US stocks, declining later.",
     "caveats": "Needs a two-leg simulator (not built yet).", "implementation": None, "prior_result": None,
     "blocked": "infrastructure: multi-leg simulation"},
    # ---------------- breakout / volatility ----------------
    {"key": "orb", "name": "Opening range breakout", "category": "breakout / session-based",
     "source": "Crabel (1990), 'Day Trading with Short Term Price Patterns and Opening Range Breakout'", "source_type": "practitioner book",
     "rationale": "The first minutes of a session set the day's direction; breaks of that range follow through.",
     "rules": "Trade the break of the first-hour range; stop at the other side; exit at session end.",
     "timeframes": ["M15"], "data": ["OHLC"], "evidence": "Author tests on futures in the 1980s.", "caveats": "Old; widely arbitraged.",
     "implementation": "v6.opening_range_breakout", "prior_result": "V6: London ORB about zero after costs (rejected on train)."},
    {"key": "nr7", "name": "NR7 / narrow-range breakout", "category": "volatility",
     "source": "Crabel (1990)", "source_type": "practitioner book",
     "rationale": "A day with the narrowest range of the last 7 signals contraction; expansion follows.",
     "rules": "After an NR7 day, buy a break of its high / sell a break of its low the next day; exit at day end.",
     "timeframes": ["D1"], "data": ["OHLC"], "evidence": "Author statistics on futures.", "caveats": "Volatility expansion does not imply direction.",
     "implementation": "candidates.nr7", "prior_result": None},
    {"key": "williams_vb", "name": "Volatility breakout (open + k x prior range)", "category": "volatility",
     "source": "Williams (1999), 'Long-Term Secrets to Short-Term Trading'", "source_type": "practitioner book",
     "rationale": "A move from the open by a fraction of yesterday's range signals intraday directional intent.",
     "rules": "Buy when price exceeds today's open + k x yesterday's range (sell below open - k x range); exit at close.",
     "timeframes": ["D1", "M15"], "data": ["OHLC"], "evidence": "Author contest results; popular in crypto backtests.",
     "caveats": "Author-reported; many cost-free crypto backtests.", "implementation": "candidates.volatility_breakout", "prior_result": None},
    {"key": "squeeze", "name": "Bollinger/Keltner squeeze breakout (TTM Squeeze)", "category": "volatility",
     "source": "Carter (2005), 'Mastering the Trade'; LazyBear 'Squeeze Momentum' (TradingView)", "source_type": "practitioner / TradingView",
     "rationale": "Volatility clusters; compressed ranges resolve into expansion.", "rules": "Trade the band break after a width percentile low.",
     "timeframes": ["H1"], "data": ["OHLC"], "evidence": "Practitioner.", "caveats": "Direction of the expansion is the hard part.",
     "implementation": "v6.squeeze_breakout", "prior_result": "V6 round 2: about zero after costs (rejected on train)."},
    {"key": "inside_bar", "name": "Inside-bar breakout", "category": "price action",
     "source": "Price-action literature (e.g. Brooks, 'Trading Price Action Trends', 2011)", "source_type": "practitioner book",
     "rationale": "Contraction then break of the mother bar starts a move.", "rules": "Break of the mother bar after an inside bar.",
     "timeframes": ["H4"], "data": ["OHLC"], "evidence": "Practitioner.", "caveats": "Discretionary origins.",
     "implementation": "v6_round3.inside_bar_breakout", "prior_result": "V6 round 3: failed on test (-0.17R)."},
    # ---------------- seasonality / calendar / FX microstructure ----------------
    {"key": "fx_local_hours", "name": "FX intraday seasonality: currencies weaken in their own trading hours", "category": "statistical / session-based",
     "source": "Breedon & Ranaldo (2013), 'Intraday patterns in FX returns and order flow', Journal of Money, Credit and Banking",
     "source_type": "academic", "rationale": "Domestic buyers of foreign currency concentrate in local hours, so a currency tends to depreciate during its own trading session and appreciate in foreign hours.",
     "rules": "e.g. short EURUSD/GBPUSD in European hours, long in US hours; long USDJPY in Tokyo hours.",
     "timeframes": ["H1"], "data": ["OHLC"], "evidence": "Significant patterns over 10+ years of major pairs in the paper.",
     "caveats": "Effect sizes are a few basis points per session, possibly below CFD spreads.",
     "implementation": "candidates.fx_local_hours", "prior_result": None},
    {"key": "turn_of_month", "name": "Turn-of-the-month effect (equity indices)", "category": "calendar",
     "source": "Ariel (1987), 'A monthly effect in stock returns', JFE; Lakonishok & Smidt (1988), 'Are seasonal anomalies real?', RFS",
     "source_type": "academic", "rationale": "Equity returns concentrate around month turns (pension and salary flows).",
     "rules": "Long indices from the last trading day of the month to the third trading day of the next.",
     "timeframes": ["D1"], "data": ["OHLC"], "evidence": "Robust over a century of DJIA data in Lakonishok & Smidt.",
     "caveats": "Only ~24 month-turns in our data per index: very low power.", "implementation": "candidates.turn_of_month", "prior_result": None},
    {"key": "overnight_drift", "name": "Overnight vs intraday returns (equity indices)", "category": "calendar / microstructure",
     "source": "Lou, Polk & Skouras (2019), 'A tug of war: overnight versus intraday expected returns', JFE; Cliff, Cooper & Gulen (2008)",
     "source_type": "academic", "rationale": "Much of the US equity premium has accrued overnight rather than during the trading day.",
     "rules": "Long US indices from the cash close to the next cash open; flat during the day.",
     "timeframes": ["M15"], "data": ["OHLC"], "evidence": "Documented 1993-2013+ in US stocks and indices.",
     "caveats": "CFD overnight financing (swap) is not in our history and works against this strategy.",
     "implementation": "candidates.overnight_drift", "prior_result": None},
    {"key": "weekend_effect", "name": "Day-of-week (weekend) effect", "category": "calendar",
     "source": "French (1980), 'Stock returns and the weekend effect', JFE", "source_type": "academic",
     "rationale": "Monday returns were historically negative.", "rules": "Short indices on Mondays.", "timeframes": ["D1"], "data": ["OHLC"],
     "evidence": "Strong pre-1980s; largely disappeared after publication.", "caveats": "Considered a dead anomaly; not worth test budget.",
     "implementation": None, "prior_result": None, "deprioritised": "evidence of disappearance after publication"},
    {"key": "pre_fomc", "name": "Pre-FOMC announcement drift", "category": "event-driven",
     "source": "Lucca & Moench (2015), 'The pre-FOMC announcement drift', Journal of Finance", "source_type": "academic",
     "rationale": "US equities rise in the 24 hours before scheduled FOMC announcements.",
     "rules": "Long US indices 24h before each scheduled FOMC statement.", "timeframes": ["H1"], "data": ["OHLC", "event_calendar"],
     "evidence": "Large share of the equity premium 1994-2011.", "caveats": "Only ~16 events in our window; needs an event calendar.",
     "implementation": None, "prior_result": None},
    {"key": "fx_carry", "name": "FX carry trade", "category": "carry",
     "source": "Lustig, Roussanov & Verdelhan (2011), 'Common risk factors in currency markets', RFS; Burnside et al. (2011)",
     "source_type": "academic", "rationale": "High-yield currencies earn the interest differential with insufficient offsetting depreciation.",
     "rules": "Long high-interest, short low-interest currencies; rebalance monthly.", "timeframes": ["D1"], "data": ["OHLC", "swap_history"],
     "evidence": "Strong but crash-prone.", "caveats": "Requires historical swap/interest rates.", "implementation": None, "prior_result": None},
    # ---------------- volume / microstructure ----------------
    {"key": "vsa_climax", "name": "Volume climax reversal (VSA / Wyckoff)", "category": "volume",
     "source": "Williams (T.) (1993), 'Master the Markets' (Volume Spread Analysis); Wyckoff method", "source_type": "practitioner book",
     "rationale": "Extreme volume with a rejection wick marks exhaustion of the prior move.",
     "rules": "H1 tick volume > 3x its 50-bar median, with a wick > 60% of the range against the bar's direction -> fade.",
     "timeframes": ["H1"], "data": ["OHLC", "tick_volume"], "evidence": "Practitioner; no rigorous published test found.",
     "caveats": "MT5 tick volume is a quote-count proxy, not traded volume.", "implementation": "candidates.volume_climax", "prior_result": None},
    {"key": "order_flow", "name": "Order-book imbalance / order flow", "category": "microstructure",
     "source": "Cont, Kukanov & Stoikov (2014), 'The price impact of order book events', Journal of Financial Econometrics",
     "source_type": "academic", "rationale": "Order-flow imbalance predicts very short-term price changes.", "rules": "Trade the sign of order-flow imbalance.",
     "timeframes": ["tick"], "data": ["order_book"], "evidence": "Strong at seconds horizons.", "caveats": "Requires level-2 data; horizons below our execution latency.",
     "implementation": None, "prior_result": None},
    {"key": "cot", "name": "Commitments of Traders positioning", "category": "positioning",
     "source": "e.g. Wang (2003), 'Investor sentiment, market timing, and futures returns', Applied Financial Economics", "source_type": "academic",
     "rationale": "Extreme speculative positioning predicts reversals.", "rules": "Fade extreme non-commercial net positions.",
     "timeframes": ["W1"], "data": ["cot_history"], "evidence": "Mixed.", "caveats": "Weekly data; not available in TRADEden.",
     "implementation": None, "prior_result": None},
    # ---------------- machine learning / hybrid ----------------
    {"key": "ml_logit", "name": "Walk-forward regularised logistic classifier on price features", "category": "machine learning",
     "source": "Methodology: Gu, Kelly & Xiu (2020), 'Empirical asset pricing via machine learning', RFS; Krauss, Do & Huck (2017), EJOR; Lopez de Prado (2018), 'Advances in Financial Machine Learning'",
     "source_type": "academic", "rationale": "Combine weak price features (returns, volatility, time of day, distance to EMAs) non-linearly; regularise and validate out-of-sample.",
     "rules": "Train an L2 logistic model on TRAIN only to predict whether price moves +1 ATR before -1 ATR; trade when probability > threshold chosen on VALIDATION.",
     "timeframes": ["H1"], "data": ["OHLC", "tick_volume"], "evidence": "ML adds predictive power for stock returns at monthly horizons; intraday FX evidence is weak.",
     "caveats": "High overfitting risk; low signal-to-noise; features must use closed bars only.", "implementation": "candidates.ml_logit", "prior_result": None},
    {"key": "regime_switch", "name": "Regime-aware strategy selection", "category": "hybrid",
     "source": "e.g. Kaufman, 'Trading Systems and Methods' (efficiency ratio); Ang & Bekaert (2002) on regime switching", "source_type": "practitioner / academic",
     "rationale": "Run trend systems in trends and mean reversion in ranges.", "rules": "Classify trend strength and volatility; allocate families to cells chosen on train.",
     "timeframes": ["H1"], "data": ["OHLC"], "evidence": "Intuitive; mixed empirical support.", "caveats": "Many cells -> selection luck.",
     "implementation": "v6_round3 (regime-aware hybrid)", "prior_result": "V6 round 3: in-sample +0.12R, validation -0.01R (rejected)."},
    {"key": "smc_ict", "name": "Smart Money Concepts / ICT (liquidity sweeps, order blocks)", "category": "market structure",
     "source": "Practitioner (Inner Circle Trader); widespread on YouTube/TradingView", "source_type": "practitioner",
     "rationale": "Institutional liquidity grabs and order blocks mark reversal points.", "rules": "See production smc and V6 SMC V2.",
     "timeframes": ["M15", "H1"], "data": ["OHLC"], "evidence": "No peer-reviewed evidence found.", "caveats": "Rules are often discretionary.",
     "implementation": "production smc / experiments.smc_v2_signals", "prior_result": "Production SMC failed on test (-0.23R); SMC V2 sweep rejected (-0.15R)."},
    {"key": "tv_repaint_warning", "name": "TradingView public strategies (category note)", "category": "methodology note",
     "source": "TradingView Pine Script documentation on repainting and request.security lookahead", "source_type": "documentation",
     "rationale": "Public scripts are a rich idea source.", "rules": "Re-implement from rules only; never trust the published equity curve.",
     "timeframes": [], "data": ["OHLC"], "evidence": "Published backtests are commonly in-sample, cost-free, or use future data via repainting/lookahead.",
     "caveats": "Treat every published TradingView result as unverified.", "implementation": None, "prior_result": None, "note_only": True},
]


def available(entry: dict[str, Any]) -> tuple[bool, str]:
    missing = [d for d in entry.get("data", []) if d not in AVAILABLE]
    if missing:
        return False, "data unavailable: " + ", ".join(missing)
    if entry.get("blocked"):
        return False, entry["blocked"]
    return True, ""


def search(term: str) -> list[dict[str, Any]]:
    term = term.lower()
    return [e for e in LIBRARY if any(term in str(v).lower() for v in e.values())]


def get(key: str) -> dict[str, Any]:
    return next(e for e in LIBRARY if e["key"] == key)


def export_markdown(path: Path | None = None) -> Path:
    path = path or Path(__file__).with_name("STRATEGY_LIBRARY.md")
    lines = ["# TRADEden strategy research library", "",
             "Generated from `research/library.py` (`python -m research.library export`). Published claims are "
             "summaries, not endorsements; status and our own results come from the discovery registry "
             "(`python -m research.discovery status`).", ""]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for e in LIBRARY:
        by_category.setdefault(e["category"], []).append(e)
    for category, entries in sorted(by_category.items()):
        lines += [f"## {category.capitalize()}", ""]
        for e in entries:
            ok, why = available(e)
            lines += [f"### {e['name']} (`{e['key']}`)", "",
                      f"- **Source:** {e['source']} ({e['source_type']})",
                      f"- **Rationale:** {e['rationale']}", f"- **Rules:** {e['rules']}",
                      f"- **Timeframes / data:** {', '.join(e['timeframes']) or 'n/a'} / {', '.join(e['data'])}"
                      + ("" if ok else f" (**{why}**)"),
                      f"- **Published evidence:** {e['evidence']}", f"- **Caveats:** {e['caveats']}",
                      f"- **Implementation:** {e.get('implementation') or 'not implemented'}",
                      f"- **TRADEden result so far:** {e.get('prior_result') or 'untested'}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cat = args[args.index("--category") + 1].lower() if "--category" in args else None
        for e in LIBRARY:
            if cat and cat not in e["category"].lower():
                continue
            ok, why = available(e)
            print(f"{e['key']:20} {e['category']:28} {'ok' if ok else why:38} {e['name']}")
    elif args[0] == "search":
        for e in search(" ".join(args[1:])):
            print(f"{e['key']:20} {e['name']}  [{e['source']}]")
    elif args[0] == "show":
        for k, v in get(args[1]).items():
            print(f"{k:16} {v}")
    elif args[0] == "export":
        print(export_markdown())


if __name__ == "__main__":
    main()
