# T-032 TRADEden Intelligence V2: implementation report

Status: **BUILD and VERIFY complete; awaiting CEO approval.**
- Nothing is committed or pushed.
- No production strategy, risk parameter or execution setting was changed.
- The running engine was not restarted.
- The new outcome worker and the scheduled reports are **built but disabled**.
- No data was deleted.

Date: 2026-10-19.

## Executive summary

1. **The performance problem is the strategies, not the tracking.** Signals were tracked with a new, stricter outcome engine and replayed over 2 years of MT5 history. In both, all four production strategies lose money after realistic costs. trendline_v5, which produces almost all signals, shows **no measurable edge even before costs** (gross -0.04R per trade, 95% CI -0.08 to +0.01). Costs then take about 0.15R per trade because its stops are about one M15 ATR, small next to spread plus commission.
2. **Filters don't create an edge.**
   - 28 pre-registered experiments were tested, with parameters chosen walk-forward and scored once on an untouched holdout: higher-timeframe alignment, session filters, rollover exclusion, score thresholds, volatility stops, target caps, three composite "V2" strategies and one new strategy.
   - **None passed** (positive out-of-sample expectancy with a CI above zero, a positive holdout, and survival of doubled costs).
   - The closest is S&R V2, about break-even.
   - With 28 tests, one or two false positives would be expected by chance; none appeared, which makes the negative conclusion robust.
3. **Outcome tracking is now authoritative and recovers from downtime.** Every confirmed signal has exactly one outcome, resolved from MT5 history with M1 tie-breaks and an audit trail. Recovered history so far: live strategies 30 TP / 103 SL (-0.32R per signal).
4. **Daily and weekly Telegram reports are built and tested, including PDF output, but off.** They need two flags and an engine restart (section G).
5. **Recommendation:** treat current live alerts as research signals, not trade ideas, until a strategy passes the lab. Consider pausing or relabelling Trendline alerts (section G).

## A. Existing strategy performance (verified baseline)

### A1. Live record: authoritative outcomes of every confirmed live signal

Source: `data/signal_outcomes.jsonl`, built by the new resolver from MT5 history for all 396 confirmations. The tracking window is 7 days, SELLs exit at the ask, and same-candle ties are settled on M1.

| Strategy | Resolved | TP | SL | Win rate | Net R | R per signal |
|---|---|---|---|---|---|---|
| trendline_v5 | 93 | 20 | 73 | 22% | -28.8 | -0.31 |
| support_resistance | 27 | 10 | 17 | 37% | -0.5 | -0.02 |
| trend_momentum | 12 | 0 | 12 | 0% | -12.0 | -1.00 |
| smc | 1 | 0 | 1 | – | -1.0 | – |
| **All live** | 133 | 30 | 103 | 23% | -42.3 | -0.32 |

Shadow-mode records are excluded (the one Trend/Momentum target came from a shadow v1 record). One trendline signal is still pending, and one Trend/Momentum signal is unavailable (its confirmation candle is missing from MT5 history).

Notes:
- The earlier audit's "28 TP vs 88 SL" counted only 24h windows on bid prices. The authoritative engine resolves the 17 previously undecided signals: most became stops; 2 targets were recovered.
- The 231 legacy `trendline` (v4) records are a one-off backfill dated 23–24 Sep and are not live evidence.
- Most live signals predate the 12 Oct executable-price qualification and `apply_plan`, and 63 of 94 trendline signals came from v5, not v5.1. The live record therefore mixes versions; the lab baseline (A2) replays exactly the current code.

### A2. Two-year replay of the current production code (research lab)

- **Development:** 15 Oct 2024 → 1 Apr 2026, in 6 quarterly walk-forward folds.
- **Holdout:** 1 Apr → 12 Oct 2026.
- **Costs:** recorded spread on the correct side, 0.5-spread stop slippage, IC-Markets-Raw-style commission.

| Strategy | Dev trades | Win rate | Expectancy (95% CI) | PF | Positive folds | ×2 costs | Holdout |
|---|---|---|---|---|---|---|---|
| trendline_v5 | 6,665 | 24% | **-0.19R** (-0.24, -0.15) | 0.77 | 0/6 | -0.35R | -0.26R (n=2,501) |
| support_resistance | 522 | 28% | **-0.15R** (-0.28, -0.01) | 0.80 | 2/6 | -0.26R | -0.02R (n=175) |
| trend_momentum | 76 | 28% | -0.26R (-0.56, +0.02) | 0.65 | 1/6 | -0.34R | -0.13R (n=28) |
| smc | 133 | 36% | +0.06R (-0.20, +0.32) | 1.08 | 3/6 | +0.01R | -0.23R (n=51) |

Gross expectancy (exit spread, slippage and commission removed) shows how much of the loss is costs:

| Strategy | Gross R/trade | Net R/trade | Cost per trade |
|---|---|---|---|
| trendline_v5 | -0.04 (CI -0.08, +0.01) | -0.19 | 0.15R |
| support_resistance | -0.09 (CI -0.22, +0.04) | -0.15 | 0.06R |
| trend_momentum | -0.14 | -0.26 | 0.13R |
| smc | +0.09 (CI -0.17, +0.35) | +0.06 | 0.03R |

### A3. Diagnosis: what is causing the poor performance

The task asked whether it is the strategies, the outcome tracking, unrealistic targets, or a combination. All three contribute, in very different proportions.

- **Strategy weakness (dominant).** trendline_v5's entries are statistically indistinguishable from random before costs. Across 6,665 development trades, no subgroup is positive: not by direction, hour, H4 alignment, stop distance, planned R or instrument (only XAUUSD is about 0).
- **Tight stops make costs decisive.** Stops sit at about 1 M15 ATR; 54% of trendline stops are hit within an hour. A wider volatility stop cut the loss from -0.19R to -0.11R but did not make it positive.
- **Unrealistic targets (Trend/Momentum).** Median planned R was 4.8 on live signals. In the replay, `apply_plan` now caps targets at H1 swings, so TM produces far fewer signals (131 in 2 years). Capping at 2R did not rescue it either.
- **Outcome tracking (secondary).** The old 24h, bid-only labels hid stops and missed one target. The new resolver fixes this (section B4) but changes the totals only slightly.
- **Counter-intuitive results:**
  - H4 trend alignment makes trendline_v5 **worse** (-0.23R vs -0.17R), so the "trade with the trend" assumption doesn't hold for this entry.
  - Higher scores are not reliably better: score ≥ 80 is -0.17R for trendline and -0.52R for Trend/Momentum.
- **Over-trading.** The replay produces about 380 trendline_v5 trades per month across 16 instruments. That volume of near-random entries is a cost machine and creates alert fatigue.

## B. Experimental strategy results

All 28 experiments, and the 4 baselines, are in the ledger `data/research/ledger.jsonl`, failures included. Each experiment's hypothesis and rationale were written in `research/experiments.py` before it was run.

Verdict rule: **CANDIDATE** requires all of the following:
- at least 30 out-of-sample development trades
- a 95% CI lower bound above 0
- PF above 1
- a positive holdout
- positive expectancy at double costs

Otherwise the verdict is INCONCLUSIVE (positive point estimate only) or REJECTED.

| Experiment | Dev trades | Expectancy (95% CI) | Positive folds | ×2 costs | Holdout | Verdict |
|---|---|---|---|---|---|---|
| trendline_v5: H4 alignment | 2,647 | -0.23 (-0.30, -0.16) | 0/6 | -0.38 | -0.13 | Rejected |
| trendline_v5: London/NY only | 3,685 | -0.15 (-0.21, -0.09) | 0/6 | -0.28 | -0.31 | Rejected |
| trendline_v5: exclude rollover | 5,734 | -0.16 (-0.21, -0.11) | 0/6 | -0.29 | -0.25 | Rejected |
| trendline_v5: score ≥ 80 | 2,948 | -0.17 (-0.23, -0.11) | 0/6 | -0.31 | -0.28 | Rejected |
| trendline_v5: volatility stop (WF) | 5,360 | -0.11 (-0.16, -0.06) | 0/6 | -0.22 | -0.12 | Rejected |
| trendline_v5: target cap (WF) | 7,243 | -0.18 (-0.21, -0.15) | 0/6 | -0.32 | -0.18 | Rejected |
| S&R: H4 alignment | 245 | -0.18 (-0.38, +0.03) | 2/6 | -0.28 | +0.17 | Rejected |
| S&R: London/NY only | 329 | -0.03 (-0.19, +0.15) | 3/6 | -0.15 | +0.11 | Rejected |
| S&R: exclude rollover | 475 | -0.17 (-0.31, -0.04) | 2/6 | -0.29 | -0.01 | Rejected |
| S&R: score ≥ 80 | 447 | -0.16 (-0.30, -0.02) | 2/6 | -0.26 | +0.06 | Rejected |
| S&R: volatility stop (WF) | 512 | -0.16 (-0.29, -0.02) | 2/6 | -0.24 | -0.06 | Rejected |
| S&R: target cap (WF) | 532 | -0.21 (-0.32, -0.10) | 0/6 | -0.31 | -0.04 | Rejected |
| TM: H4 alignment | 76 | -0.26 (-0.56, +0.02) | 1/6 | -0.34 | -0.13 | Rejected (TM is already H4-aligned) |
| TM: London/NY only | 23 | +0.05 (-0.50, +0.65) | 3/6 | +0.03 | -0.42 | Insufficient sample |
| TM: exclude rollover | 62 | -0.23 (-0.54, +0.10) | 1/6 | -0.26 | -0.11 | Rejected |
| TM: score ≥ 80 | 38 | -0.52 (-0.84, -0.13) | 0/6 | -0.54 | -0.14 | Rejected |
| TM: volatility stop (WF) | 76 | -0.26 | 1/6 | -0.34 | -0.13 | Rejected (stops already wider than 2 ATR) |
| TM: target cap (WF) | 76 | -0.20 (-0.49, +0.11) | 1/6 | -0.27 | -0.22 | Rejected |
| SMC: H4 alignment | 98 | -0.07 (-0.37, +0.25) | 2/6 | -0.11 | -0.35 | Rejected |
| SMC: London/NY only | 63 | -0.05 (-0.42, +0.34) | 3/6 | -0.10 | -0.42 | Rejected |
| SMC: exclude rollover | 116 | -0.04 (-0.30, +0.23) | 3/6 | -0.09 | -0.22 | Rejected |
| SMC: score ≥ 80 | 114 | +0.07 (-0.21, +0.36) | 2/6 | +0.03 | -0.20 | Inconclusive |
| SMC: volatility stop (WF) | 133 | +0.02 (-0.23, +0.28) | 2/6 | -0.02 | -0.23 | Inconclusive |
| SMC: target cap (WF) | 134 | -0.01 (-0.24, +0.22) | 2/6 | -0.06 | -0.24 | Rejected |
| **Trendline V6** (H4 + no rollover + WF stop) | 2,035 | -0.18 (-0.25, -0.11) | 0/6 | -0.26 | +0.03 | Rejected |
| **S&R V2** (London/NY + no rollover + WF stop) | 321 | -0.01 (-0.18, +0.16) | 4/6 | -0.11 | +0.06 | Rejected, closest to viable |
| **Momentum V2** (no rollover + WF target cap) | 62 | -0.19 (-0.50, +0.13) | 0/6 | -0.22 | -0.21 | Rejected |
| **SMC V2** (new: previous-day sweep + reclaim + displacement, H4-aligned) | 947 | -0.15 (-0.25, -0.07) | 0/6 | -0.21 | -0.14 | Rejected |

Expectancy is in R per trade. WF = parameter chosen walk-forward on the 6 months before each fold; the choices are stored in the ledger. For example, trendline's stop floor picked "2.0 ATR" in 5 of 6 folds.

What we learned:
- The one consistent improvement is a **wider volatility stop**. It reduces cost drag on every strategy where stops were tight, but only moves results towards zero.
- **S&R in liquid hours** is the only line of work near break-even with stable folds (4/6 positive) and a positive holdout. It deserves continued paper observation, not promotion.

## C. Recommended strategy improvements

In order of evidence strength:

1. **Stop treating Trendline alerts as trade ideas.** Pause them, or move trendline_v5 to SHADOW, until a version passes the lab. This is the clearest result in the study (13k+ trades, CI entirely below zero), and it currently produces most Telegram alerts.
2. **Move Trend/Momentum to SHADOW:** 0 targets in 12 resolved live signals, negative in every variant.
3. **Keep S&R live but labelled "experimental", and run S&R V2 in shadow** for forward evidence. This is the only near-break-even line.
4. **Next research directions,** to be built only in the lab:
   - **Fewer, higher-timeframe setups:** H1/H4 entries with D1 context. Cost per R falls roughly with the inverse of stop size.
   - **Mean-reversion vs momentum split by volatility regime.** The diagnostics hint that the same entry behaves differently, but the samples are too small to claim it.
   - **Exit research:** partial take-profit and trailing exits measured against MFE. The median trendline trade reaches 0.85R before reversing.
5. **Do not raise the score threshold as a "quality" fix.** It cuts frequency without improving expectancy (score ≥ 80 is rejected for every strategy).

## D. Daily Telegram reporting status

- **Built:** `reports.py` (daily: Monday–Friday 23:00 Africa/Kampala).
- **Window:** since the previous daily slot, so Monday's report includes the weekend.
- **Content:**
  - New confirmations, kept separate from outcomes realised in the window
  - TP, SL, active, ambiguous and unverifiable counts
  - Win rate among resolved signals and net theoretical R
  - Best and worst strategy, and performance by instrument
  - Observations, and engine uptime in the window
  - Every report is labelled theoretical, not trading profit.
- **Duplicates and restarts:**
  - Reports are keyed per slot in `data/reports/reports.jsonl`, so a restart never sends a report twice.
  - Missed slots are generated after a restart (up to 5 daily and 2 weekly) and marked "Late".
  - Nothing is sent for slots before activation.
  - Temporary Telegram errors are retried with backoff.
- **Uptime:** a heartbeat thread (always on, sends nothing) records engine uptime in `data/engine_heartbeat.jsonl`. Time before the first heartbeat is reported as "not measured", never as "offline".
- **Verified:** 10 unit tests, plus a dry run on real data (`data/report_samples/daily/2026-10-02.txt`).
- **Status: DISABLED.** It needs `TRADEDEN_TELEGRAM_REPORTS_ENABLED=1` **and** `TRADEDEN_SIGNAL_OUTCOMES_ENABLED=1` (reports read the authoritative outcome store, which only stays current while the resolver runs), then an engine restart.

## E. Weekly PDF reporting status

- **Built:** Sunday 19:00 Kampala, covering the previous Sunday 19:00 → this Sunday 19:00.
- **Content:**
  - Totals, wins/losses, win rate and expectancy
  - Cumulative theoretical R
  - Breakdowns by strategy, instrument, session (London / NY / overlap / Asia) and strategy × direction
  - Maximum theoretical drawdown
  - Downtime and data-quality counts
  - The previous 4 weeks
  - Evidence-gated recommendations (minimum sample sizes)
- **Delivery:** the text goes as a message and the PDF (matplotlib; text pages plus a cumulative-R and per-strategy chart) through `sendDocument`. Copies are stored in `data/reports/weekly/`.
- **Sample:** `data/report_samples/weekly/2026-10-04.pdf` (dry run, not sent).
- **Status: DISABLED,** with the same flags as D.

## F. Test results and remaining limitations

**Tests:** `python tests/run_suite.py` → **562 tests, OK** (final run, including the concurrent T-031B session's tests). New tests:
- `test_signal_outcomes.py` (13): chronology inside the confirmation candle, SELL fills at the ask, M1 tie-break, ambiguous and unavailable states, downtime recovery, revisions and audit trail, no duplicates, restart.
- `test_reports.py` (10): Kampala schedule, windows cover each hour exactly once, content separation, theoretical labelling, downtime vs not-measured, catch-up after restart, no duplicates, retry, PDF.
- `test_research_lab.py` (11): no look-ahead (verified by injecting a leak, which the test catches), simulator fills, gaps, slippage, commission, ambiguity, timeout, metrics.

**Lab fidelity check:** for live signals of the same strategy version, the replay reproduced the strategy decision on the same bar:
- trendline v5.1: 30/31
- Trend/Momentum v2: 10/11
- S&R v2: 2/6 and SMC: 0/1. These rules check reward/risk at the *live intra-bar price*, which the live engine re-tests every 30 s. The replay sees only the bar open, so the lab under-samples S&R and SMC signals.

**Limitations:**
- TRADEden **cannot scan markets, send alerts or resolve outcomes while the laptop or engine is offline**. Missed reports and outcomes are recovered afterwards; missed *signals* cannot be.
- MT5 keeps M1 history for only about 95 days, so older same-candle ties stay AMBIGUOUS. The lab counts them as stops (pessimistic); they are rare.
- The MT5 bar `spread` field may understate real spreads at news times and rollover, and commission is an IC-Markets-Raw-style assumption (`research/simulate.py`). The ×2-cost stress is reported for this reason.
- The replay evaluates each M15 bar at its open; the live engine also sees intra-bar prices (see the fidelity check).
- The development and holdout periods cover one market history (Oct 2024 – Oct 2026). Regime changes beyond it are untested.
- Telegram TP/SL follow-ups still use the old per-horizon labels (`telegram_notifier.py` is owned by the T-031B session and was not touched).

## G. Changes requiring CEO approval

1. **Enable the authoritative outcome resolver:** `TRADEDEN_SIGNAL_OUTCOMES_ENABLED=1` and an engine restart. It is read-only towards markets and writes `data/signal_outcomes.jsonl`.
2. **Enable the daily and weekly Telegram reports:** `TRADEDEN_TELEGRAM_REPORTS_ENABLED=1`, which requires item 1. First activation sends nothing for earlier slots.
3. **Switch Telegram TP/SL follow-ups to the authoritative outcomes,** coordinated with the T-031B presentation work.
4. **Strategy changes** (none made). Proposed:
   - (a) pause Trendline alerts or move trendline_v5 to SHADOW
   - (b) move Trend/Momentum to SHADOW
   - (c) label S&R alerts "experimental"
   - (d) run S&R V2 in shadow for forward evidence
5. **Dashboard:** show the authoritative outcome totals (`GET /api/market/signal-outcomes`) instead of the 40-per-strategy archive sample.
6. **Commit** this work. It is uncommitted on `codex/commercial-mvp-phase1`, nothing is pushed, and the files are listed below.

### Files

- **New:**
  - `research/` (`__init__.py`, `history.py`, `replay.py`, `simulate.py`, `metrics.py`, `lab.py`, `experiments.py`)
  - `signal_outcomes.py`, `reports.py`
  - `tests/test_signal_outcomes.py`, `tests/test_reports.py`, `tests/test_research_lab.py`
  - this report, and `SIGNAL_AUDIT_2026-10-19.md` (earlier audit)
- **Modified:**
  - `main.py`: lifespan threads behind flags, health fields, `GET /api/market/signal-outcomes`
  - `telegram_notifier.py`: `send_document` (already committed with the T-031B session's commit `7767acb`)
- **Data (git-ignored, not committed):**
  - `data/research/` (bar cache, signals, ledger)
  - `data/signal_outcomes.jsonl`
  - `data/report_samples/`

### Reproduce

```
python -m research.lab generate      # ~15 min, 16 processes; needs the MT5 terminal
python -m research.lab baseline
python -m research.lab experiments
python -m research.lab report
python signal_outcomes.py backfill --engine http://127.0.0.1:8000
```
