# Intelligence Chart redesign — investigation and delivery

Date: 2026-10-28

## Investigation

The old Markets view (`src/intelligenceChart.mjs`) called `/api/market/chart` and sent every returned episode and outcome to `chartMarkers`. There was no overview/research boundary, visibility limit, grouping, strategy filter or horizon selector. Each episode produced an observation/confirmation arrow; every distinct observation/horizon/label-definition evaluation could add another verbose arrow. Candles were obscured by labels rather than by a single demonstrably duplicated record set.

The chart endpoint read up to 200 episodes **per strategy**, filtered by instrument only, and returned up to 1,000 unique evaluations. Selecting a different chart timeframe did not filter the research timeframe. The old marker mapper snapped timestamps to the preceding available candle, which could attach an event to a candle across a market-data gap. It excluded events after the last candle opening even if they occurred within that last candle. Evaluations were placed at a barrier-hit timestamp when provided or at a derived horizon boundary, so their markers were visually detached from the originating observation. `resolved_at` is evaluation generation time, not a historical hit time.

### Actual sources and definitions

- `backend/intelligence_chart.py`: MT5 OHLC candles, verified source-time normalization, instrument precision/tick size. Response timestamp is fetch time, not quote freshness. The final candle may still be forming.
- `backend/observations.py`: append-only snapshots, lifecycle events and immutable confirmation records. `setup_episodes` projects the latest snapshot and recorded confirmation plan. Latest observation prices can drift; confirmed plans preserve their original levels. SHADOW episodes are research; historical LIVE confirmations alone are not current opportunities.
- `backend/main.py::trade_opportunities`: the existing source of current qualified opportunities. Requires a FRESH scanner result, a LIVE plan already marked trade-qualified, and a successful repeat of the existing qualification gate. No alternate frontend qualification policy was added.
- `backend/qualification.py`: existing executable-price, quote freshness, spread/cost, barriers and minimum reward/risk checks. These remain unchanged.
- `backend/outcomes.py`: hypothetical target/invalidation first-touch labels over 15m, 1h, 4h and 24h. WIN: target first; LOSS: invalidation first; NO_HIT: neither; AMBIGUOUS: both touched within one candle with unknown order. Missing levels can leave labels absent. These are not execution results. Outcome generation waits for closed evaluation candles and preserves timestamp/data-quality evidence.
- `backend/outcome_identity.py`: unique outcome keys include setup, observation, horizon and label definition; conflicting duplicate evidence is quarantined. Separate execution/signal outcome records are not supplied by this chart endpoint.
- Quant Labs' experimental paper approvals are separate from production qualification and are not imported into Qualified Signals.

### Bounded local data-quality inspection

Read only the final approximately 2 MB of each local JSONL archive; did not scan or modify the full archive. Files are actively appended, so counts describe this sample at inspection time.

| Sample | Rows | Unique setups | Repeated identity keys |
| --- | ---: | ---: | ---: |
| Observation snapshots | 339 | 45 | 0 observation-ID repetitions |
| Hypothetical evaluations | 1,093 | 94 | 0 setup/observation/horizon/definition repetitions |

The sampled evaluations included 393 × 15m, 315 × 1h, 140 × 4h and 245 × 24h, with 499 WIN, 168 LOSS, 409 NO_HIT and 17 AMBIGUOUS labels. These are sampled label counts, **not trading performance**. All sampled records used M15. Multiple snapshots per setup and overlapping horizons explain strong correlation without proving a storage duplicate. No claim is made that the entire archive is duplicate-free or that every timestamp/label is correct. Observation archive was about 2.5 GB and market-outcome archive about 977 MB.

## Changes and new experience

1. **Market Overview (default):** clean broker candles, last candle close, instrument/timeframe, candle and fetch timestamps, current qualified-plan count, honest Unavailable assessments. No research history read by the chart endpoint. Optional candle-window high/low are descriptive extrema, not invented support/resistance.
2. **Qualified Signals:** existing current-opportunities endpoint only. Green BUY below candles, red SELL above candles; same-candle/same-direction plans grouped. Marker selection or the accessible record buttons reveal recorded strategy, source timestamp, levels, R:R, lifecycle fields and unavailable values. No historical confirmation or experimental paper approval is promoted.
3. **Research Intelligence:** opt-in request for bounded research, including SHADOW episodes. Instrument/timeframe apply to the server response; strategy, type, horizon, label and UTC date filters apply to the loaded window. Initially at most 20 candle groups, configurable to 50/100/200. Each compact count retains every grouped source record, with detail inspection and a separately selected hypothetical plan overlay. Observation, confirmation, expiration and hypothetical evaluation are distinct event types. Conflicting outcomes stay quarantined.

Research evaluation markers now anchor to the originating observation candle; evaluation horizon/end/definition and timestamp quality remain in details. This is a documented presentation change, not a change to outcome calculations. Naive/invalid dates, timestamps across missing-candle gaps, and out-of-window events do not snap to unrelated candles. The UI reports research omissions and limits. Refresh preserves the viewport; changing instrument/timeframe resets it. Stale request responses cannot overwrite a newer selection.

Retained Lightweight Charts crosshair, price/time scales, dragging, scrolling and pinch zoom. Added explicit zoom/reset and marker visibility controls, responsive controls, keyboard-accessible record buttons, data definitions and optional candle-window extrema. Official TradingView reference remains opt-in.

### Files

- `src/intelligenceChart.mjs`: three-mode workspace, summary, controls, inspection, refresh and source separation.
- `src/intelligencePresentation.mjs`: pure filtering, grouping, alignment and source-gate helpers.
- `src/styles.css`: scoped chart summary, detail and responsive styling.
- `backend/intelligence_chart.py`: research opt-in, bounded research response, instrument/timeframe matching, source strategy metadata and malformed observation-date handling.
- `tests/intelligencePresentation.test.mjs`: alignment, strict source separation, all research filter dimensions, grouping and limits.
- `backend/tests/test_chart_presentation.py`: default skips research reads; research instrument/timeframe isolation.
- `tests/browser/markets.spec.mjs`: all modes, details, research label filter, selections, zoom/reset, responsive canvas, third-party widget stub, authentication isolation and runtime/console errors.
- This report.

## Data integrity

No strategy, signal generator, qualification threshold, risk rule, broker permission, Telegram delivery code, research label calculation or historical record was changed. Visual grouping does not delete or deduplicate source records. The existing read-time outcome identity/quarantine behavior remains in use. No push, deployment or live service restart was performed.

## Actual verification

- `npm test`: **191 passed**, including four new presentation tests.
- `python -m unittest discover -s backend/tests -p test_chart_presentation.py`: **2 passed**.
- `python -m unittest discover -s backend/tests -p test_outcome_labels.py`: **16 passed**.
- Signal-outcome suite with `PYTHONPATH=backend`: **13 passed**.
- Commercial/API suite: **15 passed**.
- Authenticated production build with `VITE_BASE_PATH=/` and `VITE_AUTH_REQUIRED=1`: **passed**.
- `npx playwright test tests/browser/markets.spec.mjs`: **2 passed**. Uses synthetic broker/API fixtures for XAUUSD, BTCUSD and EURUSD; not a claim of live MT5 connectivity. No chart runtime or console errors in the successful run. Desktop and 390px mobile screenshots inspected.
- Standard production build also passed earlier. Existing Vite warnings remain for large Garden chunks and mixed static/dynamic imports.

Initial restricted backend runs encountered Windows temporary-file access errors; reruns with permitted file access passed. Initial browser server startup timed out; after stopping the stuck test session, rebuilt at the correct local base URL. The authentication test required the authenticated build. A pre-existing forced sidebar-click assertion failed; navigation now explicitly invokes the intended click handler. Visual inspection found and fixed an `aside` styling collision in the new detail panel. Final browser run passed after these corrections.

## Remaining limits and proposed follow-up

- Research uses the latest **500 global episodes**, then selects instrument/timeframe, and up to **1,000 unique evaluations** for those setups. Filters operate inside this disclosed window; an empty result is not proof that the full archive has no matches. Increasing visible marker groups does not fetch an older page. Full historical date-range browsing needs indexed server-side symbol/time/date pagination and totals, with an independent archive-scale performance benchmark.
- Existing episode projection uses incremental JSONL indexes but still assembles episode state. Cold index construction can be expensive for multi-GB archives. Overview now skips research reads entirely; no new database query or full-archive JSON transfer was introduced. Research latency at archive scale has not been benchmarked.
- Research presents latest episode snapshots and linked evaluations, not every historical snapshot or the separate Strategy Bank/Quant Labs databases. A future archive API should make those sources explicitly selectable without weakening their access controls.
- Structure, momentum and market-session assessments are Unavailable from the chart response. Current price is explicitly a candle close, not a live bid/ask. Reliable integration of additional market analysis, session calendars and quote timestamps remains future work.
- Qualified Signals is a current qualified-plan view, not a historical signal ledger. Missing lifecycle, recorded R:R or verified execution results remain Unavailable. Historical verified-trade overlays require a separately authorized, identity-safe join to actual verification records.
- The sampled data audit cannot establish full-archive correctness or statistical independence. Do not remove correlated snapshots or overlapping evaluations; investigate identity/time/label anomalies independently before proposing any research change.
- Browser tests used deterministic fixtures; live terminal/feed connectivity and real-market visuals require a later check against the running service. No fabricated candles or simulated results are represented as live data.
