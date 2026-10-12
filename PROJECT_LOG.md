# PROJECT_LOG — TradeDen (trading-hub)

## Final integrity follow-up — 2026-10-12

- Continued from `3bca4b216c08f4d0fce873f6e5e22ccd53b8a8d2` with a clean working tree.
- Created verified private backups and a clean historical projection without
  rewriting the live store. Quarantined 127 unrecoverable damaged lines as raw
  bytes; omitted 809 repeat outcome copies only from the projection and retained
  1,356 differing evidence variants across 1,346 keys. Conflicts are excluded from
  verified outcomes, research classification and training at read time.
- Added retry idempotency, streaming cold index reads, integrity audit/recovery
  tools and actual Windows/MT5 resource measurements. Streaming cold-index peak
  decreased from 2,633 to 639 MiB. Complete worker startup peaked at 4,034 MiB;
  recommend a licensed 2-vCPU/8-GB/80-GB Windows VM, subject to server soak tests.
- Audited gateway-only authentication and browser-local journals. Documented a
  minimal OIDC/PostgreSQL/user-ownership/entitlement path for Free and $19 Pro;
  subscription accounts and payments are not implemented.
- The frozen projection is not the active live store. Rollout must take a fresh
  stopped-writer backup and recovery to retain intervening appends. No hosting
  purchase, public launch or real-money execution occurred.
- See [readiness and provenance](deploy/READINESS.md) for detailed evidence and
  remaining operational gates. Earlier unfinished-work and duplicate counts below
  describe their historical audit dates, not the current committed code.
- Verification passed: 464 isolated backend tests, 164 frontend tests, production
  build, all seven real-store comparison cases and eight synthetic cases. The
  complete comparison run revealed an obsolete live-view fixture filter; its
  corrected episode case passed on rerun. Compilation, script syntax and diff
  whitespace checks passed. Historical comparisons operate on frozen copies.

Operational history, reconstructed from repository evidence: git history (commit dates are
author dates), the reports in `backend/*_REPORT.md`, module docstrings and the test suites.
Work that exists only as uncommitted working-tree files is marked **uncommitted**; no date is
claimed for it unless a file records one.

## Current architecture (as of 2026-10-03)

- **Frontend** (`src/`, Vite): TRADeden Garden: setup cards, lifecycle garden, Priority Watch,
  Analyst, Strategy Lab, archive. Every value shown comes from the engine API or is labelled
  unavailable.
- **Engine** (`backend/`, FastAPI on port 8000, local-only): MT5 market data, the strategy
  registry (`backend/strategies/`), an append-only JSONL observation store with indexes
  (`backend/data/`), the setup lifecycle, market outcomes, performance, Strategy Lab and the
  evaluation layer.
- **Strategies** (all LIVE in TradeDen; LIVE is not a profitability claim). Each one is scoped by
  `strategy_id`:

  | strategy_id | version | lifecycle |
  |---|---|---|
  | `trendline_v5` | `trendline-first-v5.1` | confirmed events |
  | `support_resistance` | `sr-levels-v2` | level episodes |
  | `trend_momentum` | `tm-pullback-v2` | confirmed events |
  | `smc` | `smc-confluence-v1` | confirmed events |

- **Universe**: 10 official instruments (XAUUSD, BTCUSD, ETHUSD, EURUSD, GBPUSD, GBPJPY, USDJPY,
  NAS100, US500, GER40) plus 6 extras by default (USDCHF, USDCAD, AUDUSD, NZDUSD, XAGUSD, EURJPY).
  Every strategy runs on all of them.
- **Company HQ** is a separate project. Its TradeDen bridge reads `/api/health`,
  `/api/market/performance` and the observation records only. TradeDen executes nothing.
  Since 2026-10-03, HQ's paper Trading Floor consumes all four strategies across the 16-symbol
  universe; desk P04 consumes SMC. HQ is paper only, and everything is gated by its Risk Desk.

## History

### 2026-09-21 — Trading Hub foundation
Product vision, `docs/product-plan.md`, `docs/data-model.md`, `docs/v0.1-ui.md`; V0.1 dashboard;
GitHub Pages deployment; CSV trade import and trade analytics; a persistent trade review journal.

### 2026-09-22 — Behaviour analytics, Market Radar, first scanner
- Behavioural intelligence engine and an "Ask Trading Hub" coach; real MT5 trade sample loaded.
- MT5 market engine backend and Market Radar; first trendline scanner connected to MT5.
- Transparent setup scoring, London/New York context, macro fundamentals, symbol aliases, buy/sell
  direction, structure invalidation, price-action/CRT lenses and calculated entry/stop/target.
- "Trading Hub V3: trendline-first scanner and MT5 bridge" (`a22e5bc`). The confirmation gate was
  relaxed without weakening the trendline (`6ebf1e3`), and trade levels are shown only once a setup
  develops (`00e51e6`).

### 2026-09-23 — Analytics quality
Expectancy, risk, data-quality, confidence and consistency intelligence for imported trades.

### 2026-09-24 — Engine hardening, Garden, strategy platform
- Hardening: one canonical port (8000), no MT5 account identifiers exposed, local-only engine,
  reused MT5 connection, trade time-basis normalisation, idempotent CSV import, an indexed
  observation store (`6571804`).
- TRADeden Garden UI (`39cd695` onward) and the contextual Analyst.
- Strategy platform: a Phase 0 trendline baseline/golden tests (`6cc6685`); the strategy contract
  and registry (`b2d3a5b`); strategy-aware persistence and lifecycle (`921de55`), API/UI and
  Strategy Lab (`a5bf06d`); the official 10-instrument universe with H4/D1 context (`73c6ca1`).
- Support & Resistance `sr-levels-v1` added in SHADOW mode (`1099304`), plus Strategy Lab
  measurement and the ML audit (`7e4c91e`).
- A verified MT5 broker time basis and outcome re-verification (`203bddd`). The session-time A/B
  (`884a3cf`, `backend/SESSION_AB_REPORT.md`) led to `trendline-first-v4` (`c5e2948`).
- Trend / Momentum `tm-pullback-v1` added in SHADOW mode (`5e2ca8c`).

### 2026-09-25 — Three strategies LIVE (`04c4b2a`)
Trendline v4, S/R v1 and Trend/Momentum v1 were all made LIVE in the Garden, with per-strategy
identity on cards, alerts and counters. SHADOW mode was kept for research.

### Uncommitted working-tree work after `04c4b2a` (in the tree, tested, not yet committed)
- **Phase 11** (`backend/TM_STOP_AB_REPORT.md`, generated 2026-09-25; `tests/test_phase11.py`):
  - The T/M stop model was A/B tested, leading to `tm-pullback-v2` (structure + ATR-guard stop).
  - Confirmed plans became immutable (a reported 1:79 R:R display came from re-planning after
    confirmation).
  - Confirmed-events lifecycle; historical evaluation layer (`backend/evaluation.py`).
- **Trendline v5:**
  - Introduced as a SHADOW experiment (`trendline-first-v5-shadow`), with closed bars only and
    H1 structural targets (`shadow_report.py`).
  - It then replaced v4 as the live trendline under its own `strategy_id` `trendline_v5`. The v4
    history is kept apart (`tests/test_trendline_replacement.py`).
- **S/R level episodes** (`LEVEL_EPISODES_LIFECYCLE`, `tests/test_sr_episodes.py`): the scanner's
  other candidate no longer invalidates an open S/R episode, and suppression is per level.
- **Garden:** command centre, Priority Watch / attention freshness, Market Research drawer.

### 2026-10-02 — Autonomous scanning (`25b6c3c`)
The engine runs a background observational scan every 30 s (`autonomous_market_worker`), serialised
with browser requests. The commit is titled "activate autonomous paper trading floor"; the paper
trading floor itself lives in Company HQ, not in this repository.

### 2026-10-03 — Strategy Upgrade Phase 1 (uncommitted; under engineering review)
Report: `backend/STRATEGY_UPGRADE_PHASE1_REPORT.md`.

- **Shared candle confirmation** (`strategies/price_action.py`): any one of wick rejection (≥ 50%
  level-side wick), engulfing, or a close beyond the touch candle, closing on the trade side.
- **S/R `sr-levels-v2`**: v1 plus a required `pattern` gate. Levels, stops and targets are unchanged.
- **Trendline `trendline-first-v5.1`**: finding — v5 had no retest and confirmed BREAKs on the break
  candle itself. v5.1 adds the retest:
  - the break must cross the line;
  - within 12 bars, a later candle must retest the line (within 0.15 ATR) and reject it;
  - a close 0.08 ATR back through the line fails the break.

  REVERSAL output is byte-identical.
- **SMC `smc-confluence-v1`** (new, LIVE; TradeDen signals only at the time, consumed by HQ desk P04 since Trading Floor V2): requires all of
  - H4 structure in the trade direction;
  - an M15 BOS/CHoCH within 48 bars, with an FVG in the break leg and an order block before it
    (a CHoCH also needs a liquidity sweep);
  - an order-block retest, then a rejection candle;
  - risk/target/1.5R gates.

  It is not connected to Company HQ or execution.
- **Trend / Momentum**: reviewed and left unchanged (it already has a deterministic M15 trigger
  candle; no defect found).
- **Verification**: 180-day MT5 replay over 16 instruments (205,382 M15 bars), no costs, detection
  comparison only:

  | | Setups before → after | Target share |
  |---|---|---|
  | S/R | 193 → 139 | 30.1% → 36.7% |
  | Trendline (all) | 4,440 → 2,863 | 26.1% → 26.3% |
  | Trendline BREAK | 2,712 → 566 | — |
  | SMC (new) | 53 (45 BOS, 8 CHoCH + sweep) | 22.6% |

  - Outcome tracking is verified for all four strategies (`tests/test_live_strategies.py`).
  - The golden persistence and scanner snapshot suites pass unchanged.
  - The targeted backend and frontend strategy suites pass; the full suite was not run.

### 2026-10-03 — Company HQ Trading Floor V2 (in the Company HQ repository)
- HQ's paper Trading Floor now scans the full 16-symbol TradeDen universe. Non-USD quote
  currencies convert to USD via fresh same-feed quotes and fail closed when stale.
- The new desk P04 consumes TradeDen `smc-confluence-v1` setups through the Central Risk Desk
  (paper only, USD 10,000).
- TradeDen side: the TradeDen engine was restarted on the committed Phase 1 code, so SMC is live.
- The read-only tool `backend/tests/tools/smc_hq_replay_fixture.py` exports genuine historical
  SMC observations for HQ's acceptance replay. It runs TradeDen's own recorder on real MT5
  history in an isolated store and writes nothing to the live store.
- No TradeDen strategy logic changed.

### 2026-10-12 — TRADEden V2: audit and fixes (CEO-authorised execution cycle)
Audit of the live store and the code. Every fix applies going forward. Stored records are never
rewritten; where a stored record was misclassified, it is re-read at read time.

- **Store integrity.** On 2026-10-05 at 16:01Z, OneDrive sync-engine bytes were written into
  `setup_observations.jsonl` at byte ~955 MB (81 damaged lines). A NUL line was also written into
  `setup_lifecycle.jsonl`. The plain JSONL readers stopped on the non-UTF-8 bytes. They now read in
  binary and skip damaged lines, as the index already did. The lost lines are not reconstructed.
  The data directory sits in an over-quota OneDrive folder; it should move out of OneDrive.
- **Trade qualification** (`backend/qualification.py`, all strategies). Each strategy plans from
  the last closed close. A confirmation is now re-checked at the live quote. The checks: levels are
  present and on the correct sides; price has not already passed the stop or the target; the quote
  is at most 300 s old (an unverified quote age fails); and the executable R:R is ≥ 1.5, unrounded,
  with the spread paid. A setup that fails is not confirmed. The strategy's own decision is kept as
  `strategy_signal_valid`, and the checks are stored in `rule_evidence.qualification`.
  - Measured on the stored data: 2 confirmations were recorded with price already beyond the stop,
    29 had an executable R:R below 1.5, and 1 was issued on a 38-hour-old tick.
- **Lifecycle classification.** Under the confirmed-events lifecycle, an unconfirmed setup that the
  strategy stops reporting (direction or family change) is now `EXPIRED`, with reason
  `SIGNAL_WITHDRAWN:<why>`. It used to be marked `INVALIDATED` even though price never reached its
  invalidation (about 2,250 stored events). Those events also blocked the same setup from being
  detected again.
  - The Strategy Lab reads the stored withdrawals as `EXPIRED` and reports `closures` per strategy:
    price-invalidated, target-resolved, withdrawn, replaced and timed out.
  - The retired v4 matcher policy is unchanged.
- **Outcomes.** A market path is labelled only when the fetched bars reach back to the observation.
  Before, a window that started after the observation (for example after engine downtime) was
  labelled from a truncated path.
- **Performance.** `/api/market/performance` adds `verified` and `verified_by_strategy`. They use
  the Strategy Lab rule: only verified outcomes count, and the shortest horizon with a verified
  target or stop decides. Every confirmed setup falls into exactly one bucket, and `reconciled`
  checks that the buckets add up.
  - R-multiples: +planned R (executable when recorded) at the target, −1 at the stop. The report
    shows total R, and average R and profit factor only from 30 decisive outcomes.
  - The Strategy Lab reports the same R figures.
  - The per-horizon label tables remain, now titled as stored labels.
- **Scores.** The score is a sum of rule points; it is not calibrated, and the trendline score
  includes points for absent evidence. The UI now labels it "rule pts", with a note that it is not a
  probability. Strategy thresholds are unchanged.
- **Efficiency Phase A** (previously uncommitted) is included:
  - the radar serves the worker's latest scan;
  - an incremental outcome index;
  - read caches;
  - a shared, read-only strategy input.
- **Tests.** New: `backend/tests/test_tradeden_v2.py`. Stale expectations were updated to the
  current registry (v5.1, SMC, sr-levels-v2). The `test_scanner_quality` import path was fixed.

## Current limitations
- **Codex recovery, 2026-10-12:** inherited V2 changes preserved and verified; online
  preparation, configurable durable storage, scanner readiness, disconnected-terminal
  recovery and manual-outcome coverage added. See `docs/V2_RECOVERY.md` and
  `deploy/README.md`. The old note below about Phase 11 being uncommitted is stale:
  those features were already in the recovery baseline. No deployment or execution
  was enabled. The current audit finds 2,165 duplicate outcome keys and 45 damaged
  outcome lines (alongside 81 damaged observations and one lifecycle line).
  Final verification: 458 isolated backend tests, 164 frontend tests, production
  build and deployment script syntax passed. Real-store write equivalence passed
  after correcting the fixture-copy race. The complete optional real-store
  read-equivalence suite was not rerun; see the recovery report for its limits.
- Replay results exclude spread, slippage and commission; they are small samples over one 180-day
  window. Parameters were chosen before the replay and not fitted, and no strategy is shown to be
  profitable.
- S/R v2 deliberately rejects strong-bodied candles launched from the level without a wick or an
  engulfing body (a known trade-off; see the report).
- The Trendline retest window (12 bars) and tolerances are fixed conventions; REVERSAL logic is
  unchanged.
- SMC is new. Its order block is a single candle's range, swings are 2-bar fractals, H1 is used when
  H4 is unavailable, and there are only 53 replay setups.
- Trend/Momentum observations for later: the hold check uses the current EMA50, and there is no
  proximity requirement for the trigger candle.
- A large body of earlier work (Phase 11, v5 replacement, Garden command centre) is still
  uncommitted alongside Phase 1, so commits should be split by scope.
- `backend/data/` (the live JSONL store, over 1 GB) is untracked and must not be committed. It lives in
  an over-quota OneDrive folder, which already corrupted it once (2026-10-05).
- Outcome labels use M15 bars strictly after the observation: price movement inside the bar that was
  forming at observation time is not seen, and a bar touching both barriers is AMBIGUOUS.
- About 537 duplicate stored outcome keys (2026-09-25/29, identical labels) remain; the reports key by
  (setup, observation, horizon), so they are not double-counted.
