# Phase 9: session-time A/B (LEGACY vs CORRECTED), trendline strategy

Generated 2026-09-24 with `python tests/tools/session_ab_report.py OUT.json` (read-only:
MT5 history + the real JSONL store; nothing written). Production was unchanged by the experiment;
the correction was then adopted as **trendline-first-v4** (see "Adoption" at the end). Below,
"production" / "LEGACY" means the pre-v4 behaviour.

## Where session time enters the trendline strategy

- `main.session_context(rows, price)` builds the context passed to `scanner.analyze_symbol`:
  - `session` (Asia / London / Overlap / New York / Off-hours) from the real UTC clock — correct;
  - `london_high/low/date/complete` from the most recent London 08:00-16:30 window, selecting
    M15 bars with `_bar_dt(row)` = **raw MT5 epoch read as UTC** — the bug. MT5 epochs encode the
    broker server clock (New York + 7 h), so the window lands 2-3 hours early;
  - `session_alignment` (New York session only, London complete, price within 8% of the London
    range from its high or low).
- `scanner.analyze_symbol` reads only `session` and `session_alignment`: alignment → session score
  5 (+ a reason), otherwise London/NY label → 3. Alignment only exists in the New York session, where
  the label already gives 3, so **the maximum score difference is ±2**. Direction, family, entry,
  stop, target and invalidation do not read session data. State uses score thresholds 50/65.
- The context is also persisted in `snapshot.session` and quoted by the analyst.

LEGACY = production (`session_time.legacy_bar_time`, proven identical to `main.session_context`).
CORRECTED = the same logic with bar times converted through the verified basis
`America/New_York+07:00` (`session_time.corrected_bar_time`); DST-invalid bars are skipped.

## Samples and results

| | Walk-forward (hourly, 10 official instruments, 2025-09 → 2026-09) | DST weeks (±4 days, every M15 bar) | Stored scan moments (real observation times) |
|---|---|---|---|
| Samples | 64,361 | 23,113 | 654 |
| Session record differs (London high/low/range) | 58,265 (90.5%) | 21,264 (92.0%) | 591 (90.4%) |
| London date/complete differs | 7,309 (11.4%) | 2,680 (11.6%) | 68 (10.4%) |
| Scanner output differs | 2,977 (4.63%) | 1,061 (4.59%) | 93 (14.2%) |
| — score / session score (±2 only) | 2,977 | 1,061 | 93 |
| — alignment gained (+2) / lost (−2) | 1,706 / 1,271 | 604 / 457 | 61 / 32 |
| — reason text | 2,849 | 1,006 | 84 |
| Score crosses 50 or 65 | 190 | 71 | 11 |
| State, direction, setup family | 0 | 0 | 0 |
| Entry, stop loss, take profit, invalidation | 0 | 0 | 0 |
| Confirmation eligibility (`strategy_valid`) | 0 | 0 | 0 |

- Threshold crossings never change state: they occur in directional-context WATCHING samples (no
  trendline gate, state does not use the score thresholds) or in gated DEVELOPING setups crossing 65
  without `confirmation_alignment` (CONFIRMING also requires it). No sample crossed 50 in a way that
  changes DEVELOPING/WATCHING.
- Confirmation onsets in the walk-forward: 744 LEGACY vs 744 CORRECTED. Eligibility flips: 0, so no
  counterfactual outcome differs. Of 45 stored confirmations that could be replayed, validity differs
  in 0.
- Every scanner change occurs in the New York session (Asia, London, Overlap, Off-hours: 0).
- By instrument (walk-forward, scanner changed / samples): BTCUSD 409/8,521 · ETHUSD 368/8,517 ·
  EURUSD 269/6,089 · GBPJPY 231/6,087 · GBPUSD 258/6,087 · GER40 260/5,637 · NAS100 327/5,777 ·
  US500 314/5,777 · USDJPY 266/6,087 · XAUUSD 275/5,782. By family: BREAK 469/8,326 · REVERSAL
  331/6,480 · directional context 2,177/49,555. By direction: LONG 1,567/32,595 · SHORT 1,402/31,680.
  Timeframe: M15 only (the trendline strategy's timeframe). Monthly rates stay within 3.9-5.8%.
- Replay fidelity (stored moments): the LEGACY replay reproduces the stored London high/low in
  85.5% and the stored scanner state in 42.7% of moments — live scans evaluated the still-forming
  candle, history holds the completed one. Both A and B use the same reconstructed inputs, so this
  does not bias the comparison, but those 654 results are reconstructions.

## DST and boundary behaviour (CORRECTED)

- Rates in each DST week (EU/US fall-back, US/EU spring-forward) match the rest of the year
  (3.6-5.6%); no transition produces a spike.
- Only 24/7 instruments have bars in the skipped/repeated hours (BTCUSD, ETHUSD: 5 each over the
  four changes); they are skipped, never guessed. 10 scan instants inside those hours were not
  evaluated. 1,196 windows contained such bars; they are Sunday-morning server times, outside London
  hours, so the London window is unaffected.
- Broker midnight = 17:00 New York; weekend crypto sessions are handled as recorded; missing session
  data and an unusable basis fail closed (no London range, no alignment).

## Performance

Session context per market (300 M15 bars): production LEGACY 0.53 ms, CORRECTED 0.32 ms warm
(2.8 ms cold, conversion cache) — the corrected version converts each bar once instead of up to 8
times. A full 10-market scan would not slow down. The A/B run: 90 s for 87,474 walk-forward/DST
samples, 2.3 s for the stored moments, 3-15 s to load MT5 history.

## Conclusion

The correction changes the **recorded London session range in ~90%** of samples and the
**trendline score by ±2 in ~4.6%** (New York session only), with the corresponding reason text. It
changed **no** state, direction, setup family, entry, stop, target, invalidation, confirmation
eligibility, confirmation onset or outcome in 88,128 samples, including all four DST transitions
and 654 real historical scan moments. It is not materially different for trading decisions under
the current thresholds; it is a data-correctness fix for the recorded session range and score.
Adopting it changes recorded strategy output (score, reason, session fields), so it must ship as a
new trendline version, not a silent edit.

## Adoption: trendline-first-v4

Approved after this report. `TrendlineStrategy` (strategies/trendline.py) is now
`trendline-first-v4` and is the registered LIVE trendline. Its session context uses the CORRECTED path
(`main.session_context` delegates to it, basis from `TRADING_HUB_MT5_SOURCE_TIMEZONE`; without a basis
the London range is unavailable rather than guessed). Detection, scoring thresholds, confirmation,
levels, lifecycle and setup families are unchanged; `scanner.analyze_symbol` only gained a
`strategy_version` label parameter (default `trendline-first-v3`).

- `LegacyTrendlineStrategy` (`trendline-first-v3`, unregistered) keeps the old raw-epoch session
  context; tests/legacy_session_context.py is a verbatim frozen copy of the pre-v4 production function.
- Records keep the version that wrote them: nothing is rewritten, relabelled or migrated. Both versions
  share `strategy_id` `trendline`, and the episode matcher is unchanged, so an episode open across the
  upgrade has v3 snapshots followed by v4 snapshots.
- Goldens: the Phase 0/3 scanner and persistence goldens remain the v3 baseline (reproduced by running
  the v3 strategy); v4 persistence goldens are in tests/fixtures/golden/persistence_trendline-first-v4
  and differ from v3 only in the version label.
- Support & Resistance (shadow) does not read the session context; its snapshots record the scan's
  shared market session context, which is now the corrected London range.
- tests/test_trendline_v4.py compares full scans under both versions: only the London fields, the
  session alignment, the session score (±2, New York only) with the total score and reason text, and the
  version label differ.
