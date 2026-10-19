# TRADEden strategy research library

Generated from `research/library.py` (`python -m research.library export`). Published claims are summaries, not endorsements; status and our own results come from the discovery registry (`python -m research.discovery status`).

## Breakout / session-based

### Opening range breakout (`orb`)

- **Source:** Crabel (1990), 'Day Trading with Short Term Price Patterns and Opening Range Breakout' (practitioner book)
- **Rationale:** The first minutes of a session set the day's direction; breaks of that range follow through.
- **Rules:** Trade the break of the first-hour range; stop at the other side; exit at session end.
- **Timeframes / data:** M15 / OHLC
- **Published evidence:** Author tests on futures in the 1980s.
- **Caveats:** Old; widely arbitraged.
- **Implementation:** v6.opening_range_breakout
- **TRADEden result so far:** V6: London ORB about zero after costs (rejected on train).

## Calendar

### Turn-of-the-month effect (equity indices) (`turn_of_month`)

- **Source:** Ariel (1987), 'A monthly effect in stock returns', JFE; Lakonishok & Smidt (1988), 'Are seasonal anomalies real?', RFS (academic)
- **Rationale:** Equity returns concentrate around month turns (pension and salary flows).
- **Rules:** Long indices from the last trading day of the month to the third trading day of the next.
- **Timeframes / data:** D1 / OHLC
- **Published evidence:** Robust over a century of DJIA data in Lakonishok & Smidt.
- **Caveats:** Only ~24 month-turns in our data per index: very low power.
- **Implementation:** candidates.turn_of_month
- **TRADEden result so far:** untested

### Day-of-week (weekend) effect (`weekend_effect`)

- **Source:** French (1980), 'Stock returns and the weekend effect', JFE (academic)
- **Rationale:** Monday returns were historically negative.
- **Rules:** Short indices on Mondays.
- **Timeframes / data:** D1 / OHLC
- **Published evidence:** Strong pre-1980s; largely disappeared after publication.
- **Caveats:** Considered a dead anomaly; not worth test budget.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Calendar / microstructure

### Overnight vs intraday returns (equity indices) (`overnight_drift`)

- **Source:** Lou, Polk & Skouras (2019), 'A tug of war: overnight versus intraday expected returns', JFE; Cliff, Cooper & Gulen (2008) (academic)
- **Rationale:** Much of the US equity premium has accrued overnight rather than during the trading day.
- **Rules:** Long US indices from the cash close to the next cash open; flat during the day.
- **Timeframes / data:** M15 / OHLC
- **Published evidence:** Documented 1993-2013+ in US stocks and indices.
- **Caveats:** CFD overnight financing (swap) is not in our history and works against this strategy.
- **Implementation:** candidates.overnight_drift
- **TRADEden result so far:** untested

## Carry

### FX carry trade (`fx_carry`)

- **Source:** Lustig, Roussanov & Verdelhan (2011), 'Common risk factors in currency markets', RFS; Burnside et al. (2011) (academic)
- **Rationale:** High-yield currencies earn the interest differential with insufficient offsetting depreciation.
- **Rules:** Long high-interest, short low-interest currencies; rebalance monthly.
- **Timeframes / data:** D1 / OHLC, swap_history (**data unavailable: swap_history**)
- **Published evidence:** Strong but crash-prone.
- **Caveats:** Requires historical swap/interest rates.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Event-driven

### Pre-FOMC announcement drift (`pre_fomc`)

- **Source:** Lucca & Moench (2015), 'The pre-FOMC announcement drift', Journal of Finance (academic)
- **Rationale:** US equities rise in the 24 hours before scheduled FOMC announcements.
- **Rules:** Long US indices 24h before each scheduled FOMC statement.
- **Timeframes / data:** H1 / OHLC, event_calendar (**data unavailable: event_calendar**)
- **Published evidence:** Large share of the equity premium 1994-2011.
- **Caveats:** Only ~16 events in our window; needs an event calendar.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Hybrid

### Regime-aware strategy selection (`regime_switch`)

- **Source:** e.g. Kaufman, 'Trading Systems and Methods' (efficiency ratio); Ang & Bekaert (2002) on regime switching (practitioner / academic)
- **Rationale:** Run trend systems in trends and mean reversion in ranges.
- **Rules:** Classify trend strength and volatility; allocate families to cells chosen on train.
- **Timeframes / data:** H1 / OHLC
- **Published evidence:** Intuitive; mixed empirical support.
- **Caveats:** Many cells -> selection luck.
- **Implementation:** v6_round3 (regime-aware hybrid)
- **TRADEden result so far:** V6 round 3: in-sample +0.12R, validation -0.01R (rejected).

## Machine learning

### Walk-forward regularised logistic classifier on price features (`ml_logit`)

- **Source:** Methodology: Gu, Kelly & Xiu (2020), 'Empirical asset pricing via machine learning', RFS; Krauss, Do & Huck (2017), EJOR; Lopez de Prado (2018), 'Advances in Financial Machine Learning' (academic)
- **Rationale:** Combine weak price features (returns, volatility, time of day, distance to EMAs) non-linearly; regularise and validate out-of-sample.
- **Rules:** Train an L2 logistic model on TRAIN only to predict whether price moves +1 ATR before -1 ATR; trade when probability > threshold chosen on VALIDATION.
- **Timeframes / data:** H1 / OHLC, tick_volume
- **Published evidence:** ML adds predictive power for stock returns at monthly horizons; intraday FX evidence is weak.
- **Caveats:** High overfitting risk; low signal-to-noise; features must use closed bars only.
- **Implementation:** candidates.ml_logit
- **TRADEden result so far:** untested

## Market structure

### Smart Money Concepts / ICT (liquidity sweeps, order blocks) (`smc_ict`)

- **Source:** Practitioner (Inner Circle Trader); widespread on YouTube/TradingView (practitioner)
- **Rationale:** Institutional liquidity grabs and order blocks mark reversal points.
- **Rules:** See production smc and V6 SMC V2.
- **Timeframes / data:** M15, H1 / OHLC
- **Published evidence:** No peer-reviewed evidence found.
- **Caveats:** Rules are often discretionary.
- **Implementation:** production smc / experiments.smc_v2_signals
- **TRADEden result so far:** Production SMC failed on test (-0.23R); SMC V2 sweep rejected (-0.15R).

## Mean reversion

### Bollinger Band mean reversion in quiet regimes (`bollinger_mr`)

- **Source:** Bollinger (2001), 'Bollinger on Bollinger Bands'; Chan (2013), 'Algorithmic Trading' (practitioner book)
- **Rationale:** Stretched prices revert toward the mean when no trend is present.
- **Rules:** Fade a re-entry into the band after a close outside it, in flat-trend regimes; target the mean.
- **Timeframes / data:** H1 / OHLC
- **Published evidence:** Practitioner evidence; mean reversion at short horizons is documented in FX.
- **Caveats:** Regime-dependent; costs matter.
- **Implementation:** v6.bollinger_reversion
- **TRADEden result so far:** V6 best: train +0.01, validation +0.07, test +0.07R (CI -0.07..+0.21), not significant after Holm.

### Connors RSI(2) pullback (`rsi2`)

- **Source:** Connors & Alvarez (2008), 'Short Term Trading Strategies That Work' (practitioner book)
- **Rationale:** Short, sharp pullbacks inside a long-term uptrend tend to reverse within days.
- **Rules:** Close above 200-period SMA and RSI(2) < 10 -> buy; exit when close > 5-period SMA (mirror for shorts).
- **Timeframes / data:** D1, H1 / OHLC
- **Published evidence:** Strong in US equity indices 1990s-2000s in the authors' tests.
- **Caveats:** Equity-index specific; author-published tests; weaker in recent years per independent replications.
- **Implementation:** candidates.rsi2
- **TRADEden result so far:** untested

### Short-term reversal after extreme bars (`short_term_reversal`)

- **Source:** Lehmann (1990), 'Fads, martingales, and market efficiency', QJE; Jegadeesh (1990), 'Evidence of predictable behavior of security returns', Journal of Finance (academic)
- **Rationale:** Liquidity-driven price pressure reverses at short horizons.
- **Rules:** Fade a bar whose return exceeds z standard deviations; exit after N bars.
- **Timeframes / data:** H1 / OHLC
- **Published evidence:** Documented for weekly stock returns; liquidity provision premium.
- **Caveats:** Closely related to bollinger_mr (whose test result is known): a test of this family is partly test-informed.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Methodology note

### TradingView public strategies (category note) (`tv_repaint_warning`)

- **Source:** TradingView Pine Script documentation on repainting and request.security lookahead (documentation)
- **Rationale:** Public scripts are a rich idea source.
- **Rules:** Re-implement from rules only; never trust the published equity curve.
- **Timeframes / data:** n/a / OHLC
- **Published evidence:** Published backtests are commonly in-sample, cost-free, or use future data via repainting/lookahead.
- **Caveats:** Treat every published TradingView result as unverified.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Microstructure

### Order-book imbalance / order flow (`order_flow`)

- **Source:** Cont, Kukanov & Stoikov (2014), 'The price impact of order book events', Journal of Financial Econometrics (academic)
- **Rationale:** Order-flow imbalance predicts very short-term price changes.
- **Rules:** Trade the sign of order-flow imbalance.
- **Timeframes / data:** tick / order_book (**data unavailable: order_book**)
- **Published evidence:** Strong at seconds horizons.
- **Caveats:** Requires level-2 data; horizons below our execution latency.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Momentum

### Cross-sectional currency momentum (`xsmom_fx`)

- **Source:** Menkhoff, Sarno, Schmeling & Schrimpf (2012), 'Currency momentum strategies', Journal of Financial Economics (academic)
- **Rationale:** Currencies with high past returns keep outperforming those with low past returns for weeks to months.
- **Rules:** Rank currencies by past return; long winners, short losers; rebalance monthly.
- **Timeframes / data:** D1 / OHLC, multi_instrument
- **Published evidence:** Significant excess returns in a broad cross-section of ~48 currencies.
- **Caveats:** Profits concentrated in less liquid currencies; our universe has 8 FX pairs, not 48 currencies.
- **Implementation:** v6_round3.cross_sectional_momentum
- **TRADEden result so far:** V6 round 3: about zero on train, negative on validation (rejected).

## Positioning

### Commitments of Traders positioning (`cot`)

- **Source:** e.g. Wang (2003), 'Investor sentiment, market timing, and futures returns', Applied Financial Economics (academic)
- **Rationale:** Extreme speculative positioning predicts reversals.
- **Rules:** Fade extreme non-commercial net positions.
- **Timeframes / data:** W1 / cot_history (**data unavailable: cot_history**)
- **Published evidence:** Mixed.
- **Caveats:** Weekly data; not available in TRADEden.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Price action

### Inside-bar breakout (`inside_bar`)

- **Source:** Price-action literature (e.g. Brooks, 'Trading Price Action Trends', 2011) (practitioner book)
- **Rationale:** Contraction then break of the mother bar starts a move.
- **Rules:** Break of the mother bar after an inside bar.
- **Timeframes / data:** H4 / OHLC
- **Published evidence:** Practitioner.
- **Caveats:** Discretionary origins.
- **Implementation:** v6_round3.inside_bar_breakout
- **TRADEden result so far:** V6 round 3: failed on test (-0.17R).

## Session-based / momentum

### Market intraday momentum (`intraday_momentum`)

- **Source:** Gao, Han, Li & Zhou (2018), 'Market intraday momentum', Journal of Financial Economics (academic)
- **Rationale:** The first half-hour return of the S&P 500 (from the prior close) predicts the last half-hour return; attributed to late-informed traders and hedging.
- **Rules:** Sign of the return from prior close to session open + 30 min (here: session open to the penultimate hour); trade it into the close.
- **Timeframes / data:** M15 / OHLC
- **Published evidence:** Significant in SPY 1993-2013; also in other ETFs in follow-ups.
- **Caveats:** Our index CFDs trade nearly 24h; the cash-session open/close must be approximated by clock time.
- **Implementation:** candidates.intraday_momentum
- **TRADEden result so far:** untested

## Statistical / session-based

### FX intraday seasonality: currencies weaken in their own trading hours (`fx_local_hours`)

- **Source:** Breedon & Ranaldo (2013), 'Intraday patterns in FX returns and order flow', Journal of Money, Credit and Banking (academic)
- **Rationale:** Domestic buyers of foreign currency concentrate in local hours, so a currency tends to depreciate during its own trading session and appreciate in foreign hours.
- **Rules:** e.g. short EURUSD/GBPUSD in European hours, long in US hours; long USDJPY in Tokyo hours.
- **Timeframes / data:** H1 / OHLC
- **Published evidence:** Significant patterns over 10+ years of major pairs in the paper.
- **Caveats:** Effect sizes are a few basis points per session, possibly below CFD spreads.
- **Implementation:** candidates.fx_local_hours
- **TRADEden result so far:** untested

## Statistical arbitrage

### Pairs trading / cointegration (EURUSD-GBPUSD, XAU-XAG) (`pairs`)

- **Source:** Gatev, Goetzmann & Rouwenhorst (2006), 'Pairs trading: performance of a relative-value arbitrage rule', Review of Financial Studies; Vidyamurthy (2004) (academic)
- **Rationale:** Prices of closely related assets diverge temporarily and converge.
- **Rules:** Trade the z-score of the spread/ratio; enter at |z| > 2, exit at 0.
- **Timeframes / data:** H1, D1 / OHLC, multi_instrument (**infrastructure: multi-leg simulation**)
- **Published evidence:** Profitable 1962-2002 in US stocks, declining later.
- **Caveats:** Needs a two-leg simulator (not built yet).
- **Implementation:** not implemented
- **TRADEden result so far:** untested

## Trend following

### Time-series momentum (`tsmom`)

- **Source:** Moskowitz, Ooi & Pedersen (2012), 'Time series momentum', Journal of Financial Economics (academic)
- **Rationale:** Past 1-12 month returns of futures predict future returns of the same asset (under-reaction then delayed over-reaction).
- **Rules:** Each period, long if the trailing lookback return > 0 else short; volatility-scaled positions; monthly/weekly rebalance.
- **Timeframes / data:** D1, W1 / OHLC
- **Published evidence:** Strong across 58 futures over decades in the paper; replicated widely.
- **Caveats:** Monthly-horizon effect: two years of data give few independent observations; weaker since 2009 in several studies.
- **Implementation:** v6.weekly_tsmom
- **TRADEden result so far:** V6 round 2: train-positive (60d), negative on validation; chosen 20d config failed on test (-0.04R).

### Multi-horizon trend following (century of evidence) (`trend_century`)

- **Source:** Hurst, Ooi & Pedersen (2017), 'A Century of Evidence on Trend-Following Investing', Journal of Portfolio Management (academic)
- **Rationale:** Trend following has been profitable across 1880-2016 in many markets, especially in large market moves.
- **Rules:** Equal-weight 1, 3 and 12-month time-series momentum signals, volatility-scaled.
- **Timeframes / data:** D1 / OHLC
- **Published evidence:** Long-history backtest across asset classes.
- **Caveats:** Needs decades to evaluate; our 2-3 years cannot validate a monthly-horizon strategy.
- **Implementation:** not implemented
- **TRADEden result so far:** untested

### Moving-average and trading-range breakout rules (`ma_breakout_brock`)

- **Source:** Brock, Lakonishok & LeBaron (1992), 'Simple technical trading rules and the stochastic properties of stock returns', Journal of Finance; Sullivan, Timmermann & White (1999), 'Data-snooping, technical trading rule performance, and the bootstrap', Journal of Finance (academic)
- **Rationale:** Simple MA crossovers and range breakouts appeared to predict DJIA returns 1897-1986.
- **Rules:** Long when price crosses above its N-day MA / breaks the N-day high; short on the opposite.
- **Timeframes / data:** D1, H1 / OHLC
- **Published evidence:** Significant in-sample in 1992; Sullivan et al. found the best rules failed out-of-sample after controlling for data snooping.
- **Caveats:** Classic example of data snooping; included as a benchmark family.
- **Implementation:** v6.donchian_trend
- **TRADEden result so far:** V6: H1 and H4 breakouts about zero after costs (rejected on train).

### Turtle / Donchian channel breakout (`turtle`)

- **Source:** Faith (2007), 'Way of the Turtle'; Donchian channel rules (practitioner book)
- **Rationale:** Enter on 20/55-day highs or lows, exit on shorter opposite channel; captures large trends.
- **Rules:** Long on N-period high break, stop 2 ATR, exit on M-period low.
- **Timeframes / data:** D1, H4, H1 / OHLC
- **Published evidence:** Anecdotal: the 1980s Turtle traders' returns; later public tests show decay.
- **Caveats:** Survivorship and era effects.
- **Implementation:** v6.donchian_trend / v6.h4_donchian
- **TRADEden result so far:** V6: rejected on train (about zero after costs).

### Supertrend (ATR trailing trend flip) (`supertrend`)

- **Source:** Practitioner indicator (Olivier Seban); among the most-used TradingView public strategies (TradingView / practitioner)
- **Rationale:** Trades the direction of an ATR-band trailing stop; flips signal regime changes.
- **Rules:** Bands = (H+L)/2 +- k*ATR(n); trend flips when close crosses the active band; enter on flip, exit on next flip.
- **Timeframes / data:** H1, H4 / OHLC
- **Published evidence:** Popular; public backtests are typically cost-free and in-sample.
- **Caveats:** No credible independent evidence found.
- **Implementation:** candidates.supertrend
- **TRADEden result so far:** untested

## Volatility

### NR7 / narrow-range breakout (`nr7`)

- **Source:** Crabel (1990) (practitioner book)
- **Rationale:** A day with the narrowest range of the last 7 signals contraction; expansion follows.
- **Rules:** After an NR7 day, buy a break of its high / sell a break of its low the next day; exit at day end.
- **Timeframes / data:** D1 / OHLC
- **Published evidence:** Author statistics on futures.
- **Caveats:** Volatility expansion does not imply direction.
- **Implementation:** candidates.nr7
- **TRADEden result so far:** untested

### Volatility breakout (open + k x prior range) (`williams_vb`)

- **Source:** Williams (1999), 'Long-Term Secrets to Short-Term Trading' (practitioner book)
- **Rationale:** A move from the open by a fraction of yesterday's range signals intraday directional intent.
- **Rules:** Buy when price exceeds today's open + k x yesterday's range (sell below open - k x range); exit at close.
- **Timeframes / data:** D1, M15 / OHLC
- **Published evidence:** Author contest results; popular in crypto backtests.
- **Caveats:** Author-reported; many cost-free crypto backtests.
- **Implementation:** candidates.volatility_breakout
- **TRADEden result so far:** untested

### Bollinger/Keltner squeeze breakout (TTM Squeeze) (`squeeze`)

- **Source:** Carter (2005), 'Mastering the Trade'; LazyBear 'Squeeze Momentum' (TradingView) (practitioner / TradingView)
- **Rationale:** Volatility clusters; compressed ranges resolve into expansion.
- **Rules:** Trade the band break after a width percentile low.
- **Timeframes / data:** H1 / OHLC
- **Published evidence:** Practitioner.
- **Caveats:** Direction of the expansion is the hard part.
- **Implementation:** v6.squeeze_breakout
- **TRADEden result so far:** V6 round 2: about zero after costs (rejected on train).

## Volume

### Volume climax reversal (VSA / Wyckoff) (`vsa_climax`)

- **Source:** Williams (T.) (1993), 'Master the Markets' (Volume Spread Analysis); Wyckoff method (practitioner book)
- **Rationale:** Extreme volume with a rejection wick marks exhaustion of the prior move.
- **Rules:** H1 tick volume > 3x its 50-bar median, with a wick > 60% of the range against the bar's direction -> fade.
- **Timeframes / data:** H1 / OHLC, tick_volume
- **Published evidence:** Practitioner; no rigorous published test found.
- **Caveats:** MT5 tick volume is a quote-count proxy, not traded volume.
- **Implementation:** candidates.volume_climax
- **TRADEden result so far:** untested
