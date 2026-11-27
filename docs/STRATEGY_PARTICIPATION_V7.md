# TRADEDEN V7: strategy participation, diversification and light mode

Date: 2026-11-27. Reports: `backend/data/strategy_bank/participation_before.json` (07:16 UTC) and
`participation_after.json` (07:52 UTC). Dashboard: **Strategy Participation** (`#/participation`).

All "live" numbers are recorded signal outcomes in R (hypothetical, not executed trades). All
"historical" numbers are simulated on MT5 history with spread, commission, stop slippage and financing
(development 2024-10-15 → 2026-04-01, untouched test 2026-04-01 → 2026-10-12). Nothing in V7 changes a
live strategy rule, a deployment status, an alert route or an execution permission.

## 1. Headline

* **Trendline dominance is real, and it is not earned.** The trendline produces **74%** of the live
  scanner's confirmations (362 of 488). Historically it is the most negative strategy in the system:
  10,229 simulated trades, **−0.226 R per trade**, 95% CI [−0.261, −0.189] (evidence tier SUSPENDED).
* **The other families are not broken; they are filtered by reward/risk.** Every live strategy and
  every bank strategy is executed on every scan (verified). The gate that stops the non-trendline
  strategies is almost always the 1.5R minimum reward/risk, measured at the executable price.
* **Relaxing those gates was tested and rejected.** The two candidate fixes multiplied participation by
  5–25× but did not produce a positive expectancy (pre-registered rule, development period only).
  Production rules are therefore unchanged.
* **No strategy has a validated edge after costs**, so the new advisory allocation gives every strategy
  zero weight. Eight strategies are "promising but unproven" (positive after costs, failing at least one
  validation test). Suspension is advised (owner decision, nothing switched off) for 11 strategies that
  are significantly negative, including the live trendline and Support & Resistance.

## 2. Pipeline audit (Market Data → Detection → Setup → Confirmation → Validation → Lifecycle → Performance)

Two systems produce TRADEDEN signals:

| System | Strategies | Path |
|---|---|---|
| Live scanner (`strategies.REGISTRY`, `main._market_snapshot`) | trendline_v5, support_resistance, trend_momentum, smc | MT5 bars → strategy payload → `trade_planning.apply_plan` (executable plan) → `qualification.apply` (executable R:R ≥ 1.5, fresh quote) → observations / episodes / confirmations → Telegram → `signal_outcomes` |
| Strategy bank (`strategy_bank.worker`) | 17 core (16 EXPERIMENTAL, VWAP UNSUPPORTED), 8 ICT + 6 upgrades (RESEARCH, shadow) | closed bars → `decide()` → `engine.confirm` (drift, stop 0.2–5 ATR, spread ≤ 25% risk, min R:R) → bank store → outcomes |

**Are all strategies executed?** Yes. `research/scan_cycle_check.py` ran one full cycle on all 16
symbols with the new code: 4/4 live-registry strategies evaluated 16 times each, 30/30 scannable bank
strategies evaluated, 0 errors. The live engine's own tally agrees (`/api/health`: ok=16, error=0 for
each live strategy). Expansion candidates: 0 admitted by the qualification registry (unchanged).

### Live scanner funnel (full production observation store)

| Strategy | Episodes | Setups (≥ DEVELOPING) | Reached CONFIRMING | Confirmed | Confirmation rate |
|---|---:|---:|---:|---:|---:|
| Trendline | 8,272 | 3,502 | 1,635 | 362 | 10.3% |
| Support & Resistance | 19,224 | 8,228 | 1,907 | 100 | 1.2% |
| Trend / Momentum | 161 | 69 | 38 | 15 | 21.7% |
| SMC | 486 | 197 | 87 | 11 | 5.6% |

Replay sample (production code, no look-ahead, every M15 bar of June 2026 on 16 symbols, 34,586
bar-evaluations per strategy) — why setups do not confirm:

| Strategy | Most frequent "no setup" reason | Top rejections at CONFIRMING |
|---|---|---|
| Trendline | almost never "no setup" (55 bars): two swing points always form a line | the strategy's own break-and-retest gate |
| Support & Resistance | no meaningful level near price (969 bars) | **min_rr 1,833 of 1,837** (99.8%) |
| Trend / Momentum | **no H4 trend: 65% of bars** (22,591) | **executable min_rr 219**, stop_ok 42, min_rr 32, not_chasing 20 |
| SMC | M15 structure not aligned with H4 (49% of bars); CHoCH without sweep / FVG (20%) | **min_rr 209**, target 53, not_chasing 23, stop_ok 13 |

Bank strategies confirm 63–100% of their rule decisions; their frequency is set by the rule itself.

## 3. Root causes

1. **Trendline: permissive detection.** Any two consecutive swing highs (lows) on M15 form a line
   (`scanner._trendline_signal`), so a trendline context exists on nearly every bar and every scan
   produces a WATCHING "structure bias" episode. Volume therefore comes from detection breadth, not from
   quality. Historically it is significantly negative; 1 of 7 walk-forward folds positive for the
   break-retest family and 0 of 7 for the bounce family. *Unchanged* (production; see §5).
2. **Trend / Momentum: a planning conflict.** The strategy plans a measured-move target and gates on
   R:R ≥ 1.5 against it, but `trade_planning.apply_plan` caps the executed target at the nearest
   intervening H1 swing. In a pullback continuation the impulse high is always such a swing, so the
   executed target becomes the prior high, and in the 2-year replay the qualification layer cancels
   **4,399 of the 4,550 bars (97%)** on which the strategy's own rules had confirmed. This is a demonstrable inconsistency between the documented
   plan and the executed plan.
3. **SMC: a liquidity-target choice.** v1 targets the nearest H1 swing beyond entry, including swings
   price has already traded through (liquidity already taken); in the June 2026 replay min_rr is the
   top rejection at CONFIRMING (209 bars), followed by no target (53).
4. **Support & Resistance: the next-level target.** The target is the near edge of the next meaningful
   level; with stops beyond the zone, 1.5R is rarely available. This is the strategy's design, not a bug.
5. **Trend / Momentum and SMC are regime-specific by design.** TM requires a clean H4 trend (HH+HL,
   EMA50 slope, close beyond EMA50); SMC requires M15 structure aligned with H4. They are quiet in ranges
   on purpose.
6. **ICT and upgrade strategies look "inactive" live** only because they are RESEARCH (shadow) and
   were first loaded at the 2026-11-27 08:40 engine relaunch (1 live signal so far). Historically they
   produce 48–2,070 trades each.

## 4. Fix candidates and the decision (pre-registered, `research/v7_variants.py`)

Decision rule, written before the run: adopt a variant only if its **development-period** expectancy is
≥ production's **and** > 0 after costs. The test period is reported, never used to choose.

| Variant | Signals (2 yr) | Development exp. | Test exp. | All periods, 95% CI | Decision |
|---|---:|---:|---:|---|---|
| TM production (capped target) | 131 | −0.267 R | −0.151 R | −0.236 [−0.481, 0.029] | — |
| TM measured-move target | 3,260 | −0.067 R | −0.074 R | −0.069 [−0.182, 0.048] | **not adopted** (not > 0) |
| SMC v1 production | 197 | +0.039 R | −0.232 R | −0.036 [−0.264, 0.196] | — |
| SMC v2 untaken liquidity | 1,076 | −0.044 R | −0.305 R | −0.115 [−0.227, −0.008] | **not adopted** (worse) |

Both fixes would have made the bank "look" far more diversified (TM ×25, SMC ×5) without improving
quality, so neither ships. SMC v2 stays in the code as an unregistered research version
(`strategies.smc.SmcV2Strategy`, `smc-confluence-v2`); the TM planning conflict is documented here for
an owner decision (redefining TM as a "pullback to prior high" trade, or accepting its low frequency).

## 5. Strategies — fixed, unchanged, still underperforming

* **Fixed:** none of the production rules (no change met the evidence bar). Implemented improvements are
  measurement and transparency: participation/funnel reporting, regime classification and a regime tag
  on every new bank signal, diversification analysis, advisory allocation.
* **Unchanged, and why:** trendline (production; significantly negative, suspension advised, not
  switched off), S&R (filtering is by design; also significantly negative), TM and SMC (relaxation tested,
  §4), all 30 bank strategies (they already confirm 63–100% of decisions; their quality, not their
  frequency, is the problem), VWAP reversion (UNSUPPORTED: no real volume source).
* **Still underperforming / suspension advised (95% CI below zero):** trendline, support_resistance,
  ema_crossover, ema_pullback, donchian, liquidity_sweep, inside_bar_breakout, atr_breakout, ichimoku,
  ict_ob_reversal, trend_pullback_v2. Seven of these are also flagged **high volume, low quality**.
* **Promising but unproven (allocation class EXPERIMENTAL):** bollinger_reversion, london_breakout,
  opening_range_breakout, market_structure_break, ict_judas, divergence_v2, orb_v2, crypto_trend_v2.

## 6. Participation report (dashboard)

`python -m research.participation` (~100 s) reports, per strategy: family and concepts, instruments,
setups, confirmed, active, TP, SL, expired, invalidated, win rate, average R, net R, frequency,
confirmation rate, profit factor and max drawdown, both live and historical, plus the funnel, regime
table and allocation. Flags (fixed thresholds, `research/participation.py`):

| Flag | Rule | Count (after) |
|---|---|---:|
| Dominant | share ≥ max(25%, 2 × equal share) of its system's live confirmations | 1 (trendline) |
| Underrepresented | share < 0.25 × equal share | 3 |
| Inactive | scanned, no live confirmation | 13 (ICT / upgrades in shadow) |
| Excessive filtering | < 5% of setups confirm, ≥ 50 setups, one gate ≥ 50% of rejections | 1 (S&R) |
| Promising | evidence tier RESEARCH or better, or positive development and test with ≥ 100 trades | 8 |
| High volume · low quality | trades/month ≥ P75 and (CI below zero or expectancy ≤ −0.10 R) | 7 |

Before vs after: live participation is identical except live growth during the session (trendline 360 →
362 confirmations); no strategy rule changed, by design. Verified: the bank replay on EURUSD reproduces
all 6,667 baseline signals of 30 strategies exactly, and the TM/SMC production replays reproduce exactly
131 and 197 signals.

## 7. Market regimes (`backend/market_regime.py`)

Eight causal regimes from closed H1 bars (H4 for the reversal test): strong uptrend, strong downtrend,
ranging, high volatility, low volatility, breakout, compression, reversal; thresholds inherited from
`signal_quality/regime.py` (not tuned). Each methodology family declares the regimes it is designed for
(`SUITABILITY`, from the strategy definitions). Findings: only **13 of 34** strategies perform better
inside their designed regimes than outside, so restricting strategies to "their" regime is not, on this
evidence, a source of edge; it is reported, not enforced. New bank signals carry
`regime = {regime, family, designed_for, in_design_regime}` (informational; a failure never blocks a signal).

## 8. Independence (diversification)

Over 35 strategies with ≥ 30 historical trades: **25.5 effective independent sources** (participation
ratio of the daily-R correlation matrix). Five near-duplicate groups trade the same opportunities:
{breakout, donchian, atr_breakout, breakout_v2, crypto_trend_v2}, {ema_pullback, trend_pullback_v2},
{rsi_divergence, divergence_v2}, {macd_momentum, momentum_v2}, {opening_range_breakout, orb_v2}. Pair
metrics: same-opportunity overlap, median entry difference (bps), directional agreement, daily outcome
correlation and shared exposure.

## 9. Allocation (`backend/strategy_bank/allocation.py`, `allocation_policy.json`)

Classes RESEARCH → EXPERIMENTAL → VALIDATED → PRODUCTION, derived only from evidence
(`evidence_tiers`); PRODUCTION additionally needs the forward gate and an owner-approved entry in the
policy file. Weight goes only to VALIDATED/PRODUCTION, proportional to the CI lower bound, shared within
near-duplicate groups, capped at 25%. Today: 27 RESEARCH, 8 EXPERIMENTAL, 0 VALIDATED, 0 PRODUCTION →
all weights 0. The module is advisory: it does not alter the registry, bank statuses, Telegram or execution.

## 10. Light mode

* **Architecture:** every colour in `src/app/app.css` is a token on `:root` (dark, unchanged identity);
  `:root[data-theme="light"]` redefines only tokens. Translucent tints are `color-mix(var(--token) n%,
  transparent)`, so one rule serves both themes. ~200 hard-coded literals were replaced; none remain in
  `src/app` outside the logo. Charts (`charts.mjs`) read the tokens when built and redraw on a theme change.
* **Switching:** sun/moon button in the header, `t` shortcut, and Dark / Light / System in Settings.
  The preference is stored in `localStorage.td_theme` and applied before first paint by an inline script
  in `index.html` (no flash); it persists across navigation, reloads and browser sessions, follows the OS
  when set to System, and syncs across tabs. Default: dark.
* **Light palette:** off-white canvas (#eef1f6), white panels, slate ink, deepened bullish (#0b8a5c) /
  bearish (#d3304e) / accent (#2563eb) / amber (#b45309) for contrast on white, soft shadows.

## 11. Tests completed

| Check | Result |
|---|---|
| Backend regression suite (`tests/run_suite.py`) | 812 passed, 1 skipped |
| New V7 tests (`tests/test_v7_participation.py`) | 15 passed (regime causality, coverage of every strategy, SMC v2 target, allocation, flags, diversification, regime tag never blocks) |
| Frontend unit tests (`npm test`) | 216 passed |
| Browser: terminal spec (incl. new theme + participation test) | 3 passed |
| Browser: markets spec (auth build) | 2 passed |
| Full scanner cycle with new code (`research/scan_cycle_check.py`) | 4/4 live + 30/30 bank strategies evaluated, 0 errors |
| Historical invariance | EURUSD bank replay identical (6,667 signals); TM/SMC production replays identical |
| Manual browser pass, both themes | all 10 pages, drawer, dropdown, modal, settings, mobile 375 px; no new console errors; no dev-server errors |

## 12. Known limitations

* The running engine still serves the old code. `/api/intelligence/participation` and the bank regime
  tag take effect only after the next engine restart (not done here: the engine runs the live scanner
  and Telegram). Until then the dashboard page shows "report unavailable" against the live engine.
* `participation.json` is produced by an offline job; re-run `python -m research.participation` to refresh.
* Historical significance for the merged live trendline and the TM/SMC replays is not Holm-adjusted
  with the bank family, so their tier cannot reach VALIDATED (they are negative anyway).
* Live records are short (≤ 2 months, mostly < 100 resolved signals per strategy): too few to judge
  expectancy; the historical record carries the evidence.
* The Classic Garden (`classic.html`) keeps its own legacy styling and is not themed.
* `quantLabs.spec.mjs` was not run: it overwrites tracked screenshots and does not touch V7 code.
