# TradeDen V3: Information-Driven Research results (2026-11-23)

## Verdict: not demonstrated

**Gold has no demonstrated, repeatable predictive structure in macro releases, COT positioning or regime state, after costs.**

- None of the 12 pre-registered hypothesis families passed development. The sealed 2021–2026 holdout was not opened for them.
- One post-hoc rule (FOMC dollar continuation) got a single confirmatory test on that holdout. It was rejected.
- Nothing was promoted. The cBot stays execution-locked.

All figures are historical simulations on IC Markets MT5 bars and public FRED/ALFRED/CFTC/Federal Reserve data. They are net of spread, slippage, commission and financing. They are not live results.

## Reproducibility

| Item | Location |
|---|---|
| Plan | [TRADEDEN_V3_PLAN.md](TRADEDEN_V3_PLAN.md) |
| V3 protocol hash | `research/v3`, recorded before any result |
| V3.1 protocol hash | `b21ee5f8…c68b` |
| Code | `backend/research/v3/` |
| Reproduce | `cd backend; python -m research.v3.fetch_public; python -m research.v3.runner develop; python -m research.v3.runner holdout; python -m research.v3.confirm_a7 run` (the last refuses to run twice) |
| Archived output | `docs/tradeden-v3-{develop,holdout,ledger,data-sources}-2026-11-23.*` and `docs/tradeden-v3.1-confirm_a7-2026-11-23.json` |
| Ledger contents | 516 train trials, 118 out-of-sample test folds, 1 exploration, 1 confirmatory test |
| Earlier evidence | Untouched: edge-discovery-v1, scalper tds-1.0 (`docs/scalper-v1-evidence-2026-11-23/`), edge-discovery-v2 |
| Dashboard | `/trading-hub/research.html`, served by `GET /api/research/overview` |

## 1. Diagnostics: descriptive vs predictive (development data only)

| Question | Finding | Meaning |
|---|---|---|
| Does gold react to US releases? | Yes, strongly and at once. Gold's move in the release hour vs the dollar's: CPI −0.66, NFP −0.85, PCE −0.52, FOMC −0.74 (2016–20, H1). | **Descriptive.** The information is priced within the hour. |
| Does the reaction predict what follows (next 4 h / 5 days)? | CPI +0.20 / +0.07, NFP +0.03 / +0.02, PCE +0.07 / −0.02 | No usable continuation for data releases |
| Does the first-print surprise (vs a naive forecast) predict what follows? | CPI +0.19 / −0.08, NFP +0.03 / −0.06, PCE +0.13 / 0.00 | Signs flip between horizons: noise |
| FOMC after the statement | −0.42 next 4 h (n = 34), −0.35 next 5 days (n = 73): gold keeps moving against the dollar's reaction | The only lead; tested in §3 |
| COT: managed-money weekly change vs gold | +0.50 with the **same** week; −0.02 with the next week after release; −0.04 with the next 4 weeks; COT index vs next 4 weeks −0.005 (741 weeks) | **Purely descriptive.** Speculators chase price; positioning does not lead it. |
| Regime persistence (now vs 20 bars later) | Volatility: +0.43 D1, +0.25 H4, +0.12 H1. Trend efficiency: −0.11 D1, +0.01 H4, −0.03 H1. | **Volatility is forecastable; trend state is not.** A "trending" label today says nothing about the next 20 bars. |

## 2. Development walk-forward (expanding window, one-year test folds; daily 2010–20, intraday 2018–20, regime D1 2005–20)

| Hypothesis | OOS trades | Trades/yr | Win % | Mean R | Net bp | PF | p | 95% CI (R) | 2× costs | Failed gate-1 checks |
|---|---|---|---|---|---|---|---|---|---|---|
| A1 Under-reaction to the dollar's release move | 195 | 18 | 50.3 | −0.006 | −1.7 | 0.98 | 0.53 | −0.14 … +0.13 | −0.07 | mean, PF, p, control, robustness |
| A2 Gold release-reaction persistence | 86 | 8 | 57.0 | +0.129 | +23.9 | 1.34 | 0.17 | −0.13 … +0.39 | +0.09 | p, control, benchmark, robustness |
| A3 First-print surprise drift | 112 | 10 | 48.2 | +0.094 | +23.9 | 1.27 | 0.18 | −0.09 … +0.29 | +0.06 | p, **benchmark** (always-long +0.165) |
| A4 Gold–dollar divergence | 35 | 4 | 37.1 | −0.179 | −9.9 | 0.63 | 0.86 | −0.49 … +0.13 | −0.24 | mean, PF, p, control, robustness |
| A5 Pre-FOMC drift (long) | 14 | 8 | 64.3 | +0.191 | +20.2 | 2.02 | 0.22 | −0.21 … +0.67 | +0.13 | too few trades, p, control |
| **A6 Real-yield / dollar lead-lag** | **357** | 33 | 52.9 | **+0.101** | +22.8 | 1.30 | **0.031** | −0.01 … +0.21 | +0.06 | **parameter robustness only** |
| B1 COT extremes contrarian | 105 | 10 | 48.6 | −0.049 | +5.5 | 0.88 | 0.68 | −0.24 … +0.15 | −0.08 | mean, PF, p, control, robustness |
| B2 Managed-money flow momentum | 278 | 25 | 48.6 | −0.048 | −13.0 | 0.89 | 0.78 | −0.17 … +0.07 | −0.08 | all but trade count |
| B3 Hedger (producer/merchant) flow | 116 | 11 | 51.7 | +0.035 | +28.0 | 1.09 | 0.37 | −0.17 … +0.24 | +0.00 | PF, p, control, benchmark |
| B4 Open interest confirms price | 95 | 9 | 41.1 | −0.144 | −53.4 | 0.67 | 0.93 | −0.32 … +0.05 | −0.18 | all but trade count |
| B6 Tick-volume imbalance (proxy) | 349 | 117 | 43.8 | −0.141 | −12.5 | 0.72 | 0.99 | −0.26 … −0.02 | −0.20 | all but trade count |
| C1 Regime-conditional strategies | 250 | 16 | 45.6 | −0.092 | −19.1 | 0.80 | 0.91 | −0.22 … +0.04 | −0.14 | mean, PF, p, control, robustness |

**Reading the near-misses:**
- **A6** shows how the parameter-robustness gate works.
  - Walk-forward picked "10-year real yield, hold 5 days" in 10 of 11 test years, and it was +0.10R out of sample (p = 0.03).
  - The other three configs of the same family lost over development: dollar proxy, 1 day: −0.13R; dollar proxy, 5 days: −0.10R; real yield, 1 day: −0.03R.
  - The −0.13R config is not a reverse signal. Its gross is about −1 bp; costs are about −10 bp.
  - One positive setting surrounded by losers is the "works only at the optimised parameter" pattern you asked me to reject.
- **A2, A3 and B3 were positive but did not beat always-long** at the same timing. Gold rose through most of development, so being long after macro releases made money for reasons unrelated to the signal.

## 3. V3.1 confirmatory test: FOMC dollar continuation (the only lead)

| Stage | Result |
|---|---|
| Rule | On FOMC statement days, at the daily close, trade gold against the dollar proxy's move for that day; hold one day |
| Origin, disclosed | Chosen post-hoc: the FOMC diagnostic first, then the best of three variants explored on development data (2011–20: 73 meetings, +0.46R, t = 2.9). That in-sample figure is **not counted**. |
| Registration | Hash registered before the run; the runner refuses a second run |
| **Sealed holdout 2021–26** | **45 meetings, +0.15R, PF 1.39, p = 0.18, CI −0.17 … +0.45** |
| Halves | 2021–23: +0.46R (22 meetings); 2024–26: **−0.15R** (23 meetings) |
| Controls | Random-direction 90th percentile +0.149: **not beaten**. Always-long at the same timing: −0.08 (beaten). |
| Verdict | **REJECTED_AT_HOLDOUT.** The effect held through 2023, then disappeared. |

## 4. What this means

- **Three information sets, three different answers. None is a trading edge.**
  - *Macro releases* move gold violently but within the hour. The market prices them; first-print surprise has no lasting drift. FOMC continuation lasted about a decade and faded after 2023, too thin to bet on.
  - *Positioning (COT)* describes what traders already did (+0.50 contemporaneous). It carries no information about what comes next, at any lag tested.
  - *Regimes:* volatility clusters, which is useful for **position sizing and risk**. Trend state does not persist, so regime-switching strategy selection had nothing to work with (C1: −0.09R).
- **Cumulative evidence:** about 4,300 trials across edge-discovery-v1, scalper tds-1.0, edge-discovery-v2 and V3, plus about 227 earlier configurations. No gold strategy has passed an independent holdout. The answer to the V3 question is: **not demonstrated with price, macro first prints, public positioning or regime data.**

## 5. What would genuinely change the information set (each a new pre-registered program)

1. **Consensus forecasts** (paid, e.g. Trading Economics or FMP). They turn "surprise" into what the market actually expected.
   - Caution: the dollar-reaction diagnostic already shows the surprise is priced within the hour. Expect at most an intraday edge that needs fast execution.
2. **Exchange order flow** (CME GC trades with aggressor flags, e.g. Databento) for real volume delta. This is the only untested item from your list, because the data is paid.
3. **Use volatility forecastability for risk, not direction.** Scale risk by forecast volatility in whatever strategy the business runs. That is a measurable, repeatable structure, but it is not an edge on its own.
4. **The sealed 2021–26 holdout is now spent for FOMC-continuation ideas.** It remains untouched for every other V3 family.

## Data limits, disclosed

- **Intraday gold** history at IC Markets starts in Feb 2016. Earlier "H1" bars are one per day and were excluded.
- **The USD proxy** uses four DXY majors (EUR, JPY, GBP, CHF; about 87% of DXY weight). MT5 holds USDCAD and USDSEK only from 2025.
- **"Surprise"** means a naive forecast or the market-implied dollar reaction. Consensus data is paid.
- **COT:** reports delayed by the 2013 and 2018–19 government shutdowns were excluded. Everything else is used from as-of + 6 days.
- **Financing** for multi-day holds is modelled as fed funds ± 0.8%/yr, calibrated to today's IC Markets swap. The historical broker markup may have differed.
