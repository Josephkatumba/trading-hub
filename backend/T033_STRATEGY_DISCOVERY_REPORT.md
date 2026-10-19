# T-033 TRADEden autonomous strategy discovery: final report

Prepared for: CEO review. Date: 2026-10-19.
Status: **research platform built and run. No strategy is ready for production.**
- Nothing was committed, pushed or deployed.
- The live engine, production strategies, MT5 connection and Telegram were left unchanged.
- No V6 recommendation was acted on.

## Assessment (deliverable 8)

**No strategy has demonstrated a credible, repeatable positive expectancy after realistic costs on TRADEden's data.**

- **Scope:** 29 methodologies were catalogued from academic, practitioner and open-source/TradingView sources. Of these:
  - **23** were tested
  - **5** were rejected at intake (data or infrastructure unavailable)
  - **1** was deprioritised: an anomaly documented to have disappeared after publication
  - Across V6 and T-033, about **157 pre-registered configurations** went through train → validation, and **7** reached the untouched test window, each scored once.
- **Multiple-testing result:** after Holm–Bonferroni across all 7 test scorings, every adjusted p-value is 1.0. The single best result is entirely consistent with selection luck.
- **Best available candidate:** H1 Bollinger mean reversion in quiet regimes, re-scored with the new overnight-financing cost model:
  - train **-0.005R**, validation **+0.055R**, test **+0.060R** (95% CI -0.08 to +0.20, n=193)
  - It's the only family not negative on validation and test, but it is **not proven**. It qualifies at most for a CEO-approved shadow forward test (section 6).
- **Commercial implication:** TRADEden cannot honestly market a signal service with demonstrated positive expectancy today. Two things would change that:
  1. Much longer, better data (5–10 years of tick/M1 history with spreads) to measure small edges.
  2. A forward record built in shadow mode.

## 1. Autonomous strategy-discovery workflow (deliverable 1)

`research/discovery.py` is a reusable pipeline that runs every library entry through the same gates:

| Step | What it does | Enforced how |
|---|---|---|
| 1 Intake | Checks data requirements against what TRADEden has (MT5 OHLC, tick volume, spread, multi-instrument) | Strategies needing order books, COT, swap history or event calendars are ARCHIVED with the reason; blocked infrastructure (multi-leg pairs) likewise |
| 2 Deduplicate | Fingerprints the strategy, its grid, the protocol and the data window | An identical evaluation is skipped. On the second run, supertrend and intraday momentum were skipped automatically |
| 3 Implement | Maps library keys to small, pre-registered grids (`research/candidates.py`) or imports prior V6 results | Grids are 2–6 configurations, so no brute force |
| 4 Train | Ranks the grid on 2024-10-15 → 2025-10-01 and keeps a robust shortlist: at least 60 trades, positive, and at least half of the parameter neighbours positive | `v6.select` |
| 5 Validation | Chooses one configuration on 2025-10-01 → 2026-04-01 (at least 30 trades, positive) | For ML, train is the fitting data, so the threshold is chosen on validation only |
| 6 Test | Scores the chosen configuration **once** on 2026-04-01 → 2026-10-12 | `registry.test_consumed`: a second scoring raises an error (unit-tested) |
| 7 Controls | Random-entry twins (same instrument, timing density, stop/target geometry and costs), double-cost stress, walk-forward folds, global Holm–Bonferroni across every test scoring ever made | `random_percentile`, `global_multiple_testing` |
| 8 Rank and report | Orders by status, adjusted p, test and validation expectancy; writes the report | `data/research/discovery_report.md` |

**Qualification registry** (`data/research/registry.json`):
- Each strategy carries a status: DISCOVERED → RESEARCHING → BACKTESTED → VALIDATED → FORWARD_TESTING → PRODUCTION_CANDIDATE, or ARCHIVED with a reason. A full status history is kept.
- The workflow never promotes past VALIDATED by itself.
- `python -m research.discovery promote KEY FORWARD_TESTING --approval "..."` requires a CEO approval reference and the right prior status; PRODUCTION_CANDIDATE requires FORWARD_TESTING first. Both rules are unit-tested.

Commands:

```
python -m research.discovery run [KEY ...]    # evaluate pending/new library entries
python -m research.discovery status           # registry
python -m research.discovery report           # ranked report
python -m research.library search "<term>"    # search the library
```

**Adding a strategy:**
1. Add a library entry: source, rationale, rules, data, evidence and caveats.
2. Write a generator in `candidates.py`.
3. Register a small grid in `discovery._grid()`.
4. Run `discovery run KEY`.

The protocol, controls, ledger and registry apply automatically.

## 2. Strategy research library (deliverable 2)

- **Where:** `research/library.py`, exported as `research/STRATEGY_LIBRARY.md`.
- **Contents:** 29 entries across 15 categories:
  - trend following, momentum, mean reversion, statistical arbitrage
  - breakout/session, volatility, price action
  - calendar, FX intraday seasonality, carry, event-driven
  - volume, microstructure, positioning, machine learning
  - hybrid, market structure, and a TradingView methodology note
- **Sources:** academic, including Moskowitz–Ooi–Pedersen 2012, Hurst–Ooi–Pedersen 2017, Menkhoff et al. 2012, Brock–Lakonishok–LeBaron 1992 with Sullivan–Timmermann–White 1999, Gao–Han–Li–Zhou 2018, Breedon–Ranaldo 2013, Lou–Polk–Skouras 2019, Ariel 1987, Lucca–Moench 2015, Lustig–Roussanov–Verdelhan 2011, Gatev–Goetzmann–Rouwenhorst 2006, Cont–Kukanov–Stoikov 2014 and Gu–Kelly–Xiu 2020. Practitioner sources include Crabel, Williams, Connors–Alvarez, Bollinger, Carter, Faith and Brooks. TradingView sources include Supertrend and LazyBear Squeeze.
- **What each entry records:** published evidence and its caveats, separately. Published profitability is never taken at face value.
  - Brock et al. is recorded alongside the data-snooping critique that overturned it.
  - The TradingView category note warns about repainting and lookahead in public backtests.
- **Limitation:** citations come from the literature as commonly referenced. This session did not re-read the papers or scrape TradingView. Each entry is a hypothesis source, and only our own tests count as evidence.

## 3. Reproducible testing framework (deliverable 3)

- **Data:** MT5 IC Markets history for 16 instruments:
  - M15/H1/H4 from Aug 2024, D1 from Aug 2023, M1 from Jul 2026
  - normalised to UTC through the verified broker clock basis
  - cached locally, with each instrument's specification (digits, tick, contract, swap)
- **No look-ahead:** production strategies replay with closed bars and the bar's open only; every generator decides on closed bars. Six unit tests corrupt all post-decision data and require identical decisions, and an injected leak is caught.
- **Execution:**
  - BUY at the ask, SELL exits at the ask; gaps fill at the open
  - stop slippage 0.5 × spread; commission by instrument
  - stop-entry orders fill at the level or the gap open
  - same-candle TP/SL settled on M1, otherwise counted as a stop
  - trailing stops update only after a bar closes
- **New in T-033, overnight financing:**
  - Each instrument's MT5 swap specification is applied per 17:00 New York rollover, with the broker's triple-swap day; points, money-per-lot and annual-interest modes are all handled.
  - It changes conclusions: the published overnight-drift premium on US indices (+0.11R before financing) becomes **-0.02R** after CFD financing.
  - *Limitation:* current swap rates stand in for historical ones.
- **Statistics:**
  - expectancy, PF, drawdown, frequency, holding time
  - bootstrap 95% CIs, one-sided p-values and Holm–Bonferroni
  - walk-forward folds, double-cost stress, random-entry percentiles
  - statistical-power estimates (V6 report, section 9)
- **Ledger:** `data/research/ledger.jsonl` records every configuration, including all failures (`v6-*`, `t033-*`).
- **Tests:** `test_research_lab.py` and `test_discovery.py`, part of the full suite (section 8).

## 4. Ranked strategy research report (deliverable 4)

Auto-generated as `data/research/discovery_report.md`; abridged here. E is expectancy in R per trade after costs; test results come from the single scoring.

| Rank | Strategy (source) | Status | Validation E (n) | Test E (95% CI), n | Verdict |
|---|---|---|---|---|---|
| 1 | Bollinger mean reversion, quiet regimes (Bollinger; Chan) | BACKTESTED | +0.055 (174)* | **+0.060 (-0.08, +0.20), 193*** | Promising, not proven; Holm p 1.0 |
| 2 | Volatility breakout, k=0.7 with trend (Williams 1999) | ARCHIVED | +0.098 (595) | -0.021 (-0.08, +0.04), 687 | Failed on test (beat 10/10 random twins in development, then failed) |
| 3 | Time-series momentum (Moskowitz et al. 2012) | ARCHIVED | +0.011 (339) | -0.043 (-0.10, +0.01), 352 | Failed on test |
| 4 | Connors RSI(2), D1 (Connors & Alvarez 2008) | ARCHIVED | +0.068 (107) | -0.059 (-0.17, +0.05), 108 | Failed on test (beat 10/10 random twins in development, then failed) |
| 5 | H4 inside-bar breakout (price action) | ARCHIVED | +0.105 (225) | -0.173 (-0.35, +0.02), 272 | Failed on test |
| 6 | SMC / ICT, production (practitioner) | ARCHIVED | +0.083 (55) | -0.231 (-0.68, +0.27), 51 | Failed on test |
| 7 | Cross-sectional FX momentum (Menkhoff et al. 2012) | ARCHIVED | -0.006 (138) | – | Rejected on validation |
| 8 | Regime-aware hybrid (Kaufman; Ang & Bekaert) | ARCHIVED | -0.011 (243) | – | Rejected on validation |
| 9 | Market intraday momentum (Gao et al. 2018) | ARCHIVED | -0.026 (369) | – | Rejected on validation |
| 10 | Volume-climax reversal (VSA/Wyckoff) | ARCHIVED | -0.267 (131) | – | Rejected on validation |
| 11 | ML: walk-forward L2 logistic, 16 price features (Gu–Kelly–Xiu methodology) | ARCHIVED | -0.119 (940) | – | Rejected on validation; in-sample accuracy 51.7% on 93k rows |
| 12–20 | MA/range breakout (Brock et al.), Turtle/Donchian (H1, H4), Supertrend, London ORB (Crabel), NR7 (Crabel), squeeze (Carter), FX local-hours seasonality (Breedon & Ranaldo), turn-of-month (Ariel), overnight drift (Lou et al.) | ARCHIVED | – | – | Rejected on train: about zero or negative after costs (overnight drift after financing) |
| – | Pre-FOMC drift, FX carry, order-flow imbalance, COT positioning | ARCHIVED | – | – | Data unavailable (event calendar, swap history, level-2, COT) |
| – | Pairs / cointegration | ARCHIVED | – | – | Needs a multi-leg simulator (not built) |
| – | Century trend following, short-term reversal, weekend effect | DISCOVERED | – | – | Not implemented: needs decades of data; related to a test-seen family; anomaly disappeared |

\* With overnight financing. V6 scored it before the financing model at +0.067 (validation) and +0.068 (test).

Benchmarks, on the same periods and costs:
- **Production strategies:** trendline_v5 -0.26R on test; S&R -0.02R; Trend/Momentum -0.13R; SMC -0.23R.
- **Random-entry twins:** about -0.1 to -0.17R, which is roughly the cost of trading.
- **Comparison:** every candidate above beats the production trendline, but none beats zero credibly.

## 5. Evidence supporting or rejecting the promising candidates (deliverable 5)

- **Bollinger mean reversion (best):**
  - Not negative on validation or test; consistent with documented short-horizon mean reversion in FX.
  - Against it: train is about 0 with financing; test p = 0.17 raw and 1.0 after Holm; only 3/6 walk-forward folds positive; double costs push development negative.
  - Instrument selection on train did not persist on test.
  - Verdict: a hypothesis worth a cheap forward test, not a product.
- **Williams volatility breakout and Connors RSI(2):**
  - Both beat 10/10 random-entry twins in development and were positive on validation, then lost on test.
  - This is the clearest illustration of why train and validation success is not evidence.
- **Overnight drift:** the academic effect is real in cash indices, but CFD financing of about 0.13R per night consumes it entirely. It isn't tradable in TRADEden's instruments.
- **FX local-hours seasonality:** the published effect is a few basis points per session, below CFD spreads. It was negative after costs on train.
- **Machine learning:** a regularised model on 16 closed-bar features reached 51.7% accuracy in-sample and lost on validation. Weak features plus costs leave nothing to learn at H1. A more complex model would mainly add overfitting.
- **Contradictory-condition filters, regimes, sessions, score thresholds** (V6): none predictive out of sample.

## 6. Forward-testing plan (deliverable 6)

- **Candidate:** "Reversion V6-R1", the H1 Bollinger mean reversion (z=2.5, quiet-regime gate, mean target). Parameters are frozen; all 16 instruments; no instrument selection.
- **Mode:** SHADOW only. It records confirmations, and the authoritative outcome resolver (T-032) tracks them. **No Telegram alerts.**
- **Pre-registered criteria,** fixed now, before any forward data:

| Checkpoint | Condition | Action |
|---|---|---|
| ≥ 60 forward trades | expectancy < -0.15R (about 2 SE below zero) | Stop: archive |
| ≥ 120 trades (~4 months) | expectancy ≥ +0.05R after costs **and** PF ≥ 1.10 **and** positive at ×2 costs **and** no instrument > 30% of total R | Propose PRODUCTION_CANDIDATE to the CEO |
| ≥ 120 trades | otherwise | Continue to 250 trades, then decide by the same rule; archive if not met |

- **Honest power statement:** 120 forward trades can only distinguish edges of about ±0.18R; confirming +0.05R takes about 1,500 trades (about 4 years at 31 trades a month). The forward test guards against deterioration; it cannot prove a small edge quickly.
- **Highest-value parallel step:** acquire 5–10 years of M1/tick history with spreads (e.g. Dukascopy for FX, metals and major indices). Then re-run the whole library through the existing workflow, which needs no code changes beyond a data loader. It needs CEO approval because it involves an external data download.

## 7. Integration path for successful strategies (deliverable 7)

- **The adapter:** `research/adapter.py` wraps the candidate in the production `Strategy` contract (`evaluate(MarketInput) → payload`), so it can flow through scanner → lifecycle → authoritative outcomes → (eventually) Telegram.
  - It is **not registered** and nothing in the engine imports it.
- **Parity:** on real history it reproduces the research generator's decisions exactly. That's **53/53 test-period signals with identical stop/target levels** across EURUSD, XAUUSD, US500 and GBPJPY. A synthetic-data unit test also checks for no misses and no false positives.
- **Steps, each needing CEO approval:**
  1. Register it as `mode=SHADOW` in `strategies.REGISTRY`, with no Telegram delivery.
  2. **Resolve a rule conflict:** production qualification requires executable reward/risk ≥ 1.5R, which rejects most mean-reversion trades (target = band mean, often about 1R). A per-strategy minimum R:R is a risk-parameter change and needs approval.
  3. Enable the authoritative outcome resolver (`TRADEDEN_SIGNAL_OUTCOMES_ENABLED`) so forward results accumulate.
  4. `discovery promote reversion FORWARD_TESTING --approval "<ref>"`. After the criteria in section 6 pass, propose PRODUCTION_CANDIDATE, then `mode=LIVE` only with approval.
- **Generalisation:** any future winner follows the same path. Write `decide()` from closed bars, wrap it in an adapter, add a parity test against the research generator, register it SHADOW, forward-test, then promote with approval.

## 8. Verification

- New tests: `tests/test_discovery.py` (7) and new cases in `tests/test_research_lab.py` (financing, look-ahead for all new generators).
- Full suite: `python tests/run_suite.py` → **578 tests, OK**.

## 9. Proposed research directions (independent)

1. **Data before ideas.** Longer, higher-quality history is the binding constraint: two years of M15 can only detect edges ≥ 0.15–0.2R.
2. **Cost reduction as an edge.** Costs (0.1–0.17R per trade at M15/H1) are the main reason near-zero gross edges turn negative. Simulate limit-order entries (e.g. mean-reversion entries resting at the band) and session-aware spread avoidance; this needs tick or M1 spreads.
3. **Multi-leg statistical arbitrage.** Build the two-leg simulator; pairs and ratio trades (EURUSD/GBPUSD, XAU/XAG, US500/NAS100) are the main untested family with credible literature.
4. **Event-driven research.** An economic-calendar history (FOMC, NFP, CPI) unlocks pre-FOMC drift and post-announcement drift. The Trading Economics key already in `.env.example` could supply it, with approval.
5. **Lower frequency with a portfolio view.** Daily or weekly multi-asset trend and carry need decades of data; consider futures or ETF data rather than CFDs.

## Files

- **New:**
  - `research/library.py`, `research/STRATEGY_LIBRARY.md`, `research/discovery.py`
  - `research/candidates.py`, `research/adapter.py`
  - `tests/test_discovery.py`, this report
- **Updated:**
  - `research/simulate.py`: overnight financing
  - `research/history.py`: swap specifications in the manifest
  - `tests/test_research_lab.py`
- **Data (git-ignored):**
  - `data/research/registry.json`, `discovery_report.md`, `ledger.jsonl`
  - the swap specs in `bars/manifest.json`
- **Earlier reports this builds on:** `SIGNAL_AUDIT_2026-10-19.md`, `T032_INTELLIGENCE_V2_REPORT.md`, `V6_RESEARCH_REPORT.md`.
