# TradeDen V3: Information-Driven Quantitative Research (pre-registered 2026-11-23)

**Question:** does gold (XAUUSD) have a measurable, repeatable predictive structure in information the market may not fully price? The candidates are macro releases, positioning and regimes.

**Protocol:**
- `backend/research/v3/{registry,projects,engine,data}.py`, SHA-256 written to `backend/data/research/v3/ledger.jsonl` before any result was computed.
- The runner refuses to run if a protocol file changes after registration.
- Every train window, test window and holdout evaluation is a ledger row.

**Preserved and not repeated:**
- edge-discovery-v1 (`docs/EDGE_DISCOVERY_REPORT.md`)
- scalper tds-1.0 (`docs/scalper-v1-evidence-2026-11-23/`)
- edge-discovery-v2 (`docs/EDGE_DISCOVERY_V2_*`)

V3 adds no price-pattern families. Every hypothesis uses information those programs never had: macro first prints, release timing, a dollar index, yields, COT positioning, and regime state.

## Data (all public or broker-provided; sources and checksums in `backend/data/research/v3/sources.jsonl`)

| Data | Coverage | Look-ahead control |
|---|---|---|
| XAUUSD H1 (IC Markets MT5) | Feb 2016 → Nov 2026. Earlier "H1" bars are one per day and are not used. | Decide at the bar close, enter at the next open |
| XAUUSD D1 | 1998 → 2026 (broker days, 17:00 New York roll) | Same |
| USD proxy: EURUSD, USDJPY, GBPUSD, USDCHF with DXY weights renormalised (MT5 lacks long USDCAD/USDSEK history) | H1 from Oct 2010; D1 for decades | Built from the same closed bars |
| Release dates: CPI, Employment Situation, Personal Income & Outlays (ALFRED); scheduled FOMC statements (federalreserve.gov) | CPI/NFP/PCE 2006 →; FOMC 2011 → | Actual historical release dates, including shutdown-delayed ones |
| First-print values (ALFRED vintages on each release date) | Same | The value as published that day, never revised data |
| 10-year real yield (DFII10), fed funds (DFF) | Daily | DFII10 is used with a 1-business-day publication lag |
| CFTC disaggregated COT, gold | Jun 2006 → Nov 2026, weekly | Used from the first trading day ≥ as-of + 6 days. Reports delayed by the 2013 and 2018–19 government shutdowns are excluded. |

**Not available, and not faked:**
- Consensus forecasts are paid data. "Surprise" therefore means actual vs a naive expectation, or the dollar's market-implied reaction.
- Exchange volume delta and aggressor-side flow need paid CME tick data. B6 uses CFD tick-volume imbalance and is labelled as a proxy.

## Costs

| Cost | Value |
|---|---|
| Spread | Recorded bar spread, floored at 1.5 bp of price; doubled at D1 opens, which sit at the rollover |
| Slippage | 1 bp per market fill; 3 bp for entries within 2 hours of a release |
| Commission | 0.3 bp per side |
| Financing | Longs pay fed funds + 0.8%/yr; shorts receive fed funds − 0.8%/yr. Calibrated to the current IC Markets swap. |
| Stress test | Every holdout result is also run at 2× all costs |

## Splits

| Split | Period | Rule |
|---|---|---|
| Development | daily layer 2006–2020; intraday 2016-03–2020; regime D1 1999–2020 | Expanding walk-forward. Train on everything before the test year, test one calendar year. Test years: daily 2010–2020, intraday 2018–2020, regime D1 2005–2020. |
| **Sealed holdout** | **2021-01-01 → 2026-11-23** | One shot, gate-1 survivors only, with the config selected on all development data |

**Honesty note:** the holdout overlaps periods earlier programs used for *other* rules. V2's news-shock idea (H7, M15) is related to Project A; its rejection is part of the multiple-testing context.

## Hypotheses: 12 families, 64 configs. Default = the first grid value. Strategies are fixed-horizon with no stops.

**Project A: macro**

| ID | Hypothesis | Grid |
|---|---|---|
| A1 | Gold under-reacts to the dollar's release reaction | \|z(USD reaction)\| ≥ 1 / 0.5 × H4, H1, D1, 5D |
| A2 | Gold's own release reaction continues or reverts. The sign is a grid parameter, so its stability is what is tested. | continue / revert × H4, H1, D1, 5D |
| A3 | First-print surprise vs naive expectation drifts. Core CPI/PCE MoM vs prior; payrolls vs prior 2-month average; unemployment. | \|z\| ≥ 1 / 0.5 × D1, H4, 5D |
| A4 | When gold moves *with* the dollar on a release, the macro-consistent move follows later | all / inflation releases × D1, H4, 5D |
| A5 | Pre-FOMC drift: long into the statement, exit an hour before | 24 h / 48 h |
| A6 | Daily dollar-proxy or real-yield moves lead gold by a day | driver × 1D / 5D |

**Project B: positioning and flow**

| ID | Hypothesis | Grid |
|---|---|---|
| B1 | Extreme managed-money COT index (3-year) is contrarian | 90/10 or 80/20 bands × 4W / 1W |
| B2 | Managed-money flow momentum | 1- or 4-week change × 1W / 4W |
| B3 | Producer/merchant (hedger) flow | 1- or 4-week change × 1W / 4W |
| B4 | Price trend confirmed by rising open interest | 4W / 1W |
| B6 | **Proxy:** CFD tick-volume imbalance | follow / fade × H4 / D1 |

**Project C: regimes**

| ID | Hypothesis | Grid |
|---|---|---|
| C1 | A strategy traded only in its natural regime beats the same strategy unconditionally. Pairs: momentum in trend (efficiency ratio top third), mean reversion in range (bottom third), breakout in low volatility, momentum in high volatility. Regime cut-offs are fitted on train folds only; the strategies use fixed textbook parameters. | 4 pairs × D1, H4, H1 |

**Diagnostics** (development data only, no trading):
- event-study correlations: reaction vs USD, next move vs reaction, next move vs data surprise;
- COT descriptive vs predictive correlations;
- regime persistence.

## Gates

**Gate 1** (walk-forward out-of-sample in development). All must hold:

- at least 30 trades;
- mean R > 0 after costs;
- PF ≥ 1.10;
- one-sided p ≤ 0.10;
- mean above the 90th percentile of 200 random-direction controls;
- mean above the benchmark:
  - always-long at the same timing, for directional rules;
  - random-time long, for A5;
  - the same strategy run unconditionally, for C1;
- at least 50% of the family's configs positive over development.

**Gate 2** (sealed holdout, once). All must hold:

- mean > 0;
- bootstrap 95% CI of mean R above 0;
- positive at 2× costs;
- positive in both 2021–23 and 2024–26;
- Holm-adjusted p ≤ 0.05 across all V3 gate-2 entrants, across projects.

**Outcome:** passing both gates gives `PROMOTED_TO_SHADOW`. The cBot stays execution-locked either way.
