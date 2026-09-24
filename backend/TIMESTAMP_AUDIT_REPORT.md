# Trading Hub timestamp integrity audit

Audit captured: 2026-09-23 23:03 UTC. Existing JSONL files were read only.

## Contract and observed behavior

Trading Hub's Python timestamps use explicit `datetime.now(timezone.utc)` and are aware UTC datetimes. Persisted observation, lifecycle, confirmation, and outcome timestamps use ISO-8601 strings with `+00:00`. The timestamp helper accepts a source basis only when configured; without one, it keeps the raw MT5 epoch and its UTC-wall interpretation, sets normalization to `UNVERIFIED`, and emits no normalized timestamp.

MetaQuotes' [Python `copy_rates_from` documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py) says MT5 stores and returns bar/tick times in UTC. The live read-only diagnostic in this Trading Hub session did not match that contract: at `2026-09-23T23:03:33.352673+00:00`, the raw quote epoch `1790215413.659` converts as UTC to `2026-09-24T02:03:33.659+00:00`, **10,800.306 seconds in the future**. The latest M15 open similarly converts to `02:00Z`, in the future relative to the Python clock. MT5 returned chronological bars, and the tick was 213.659 seconds after the latest bar open. No independent broker-server wall clock is exposed by the current integration, so this audit does not select a timezone or apply a correction.

## Persisted examples

| Record | Raw source time | Interpreted as UTC | Persisted/backend time | Status |
|---|---:|---|---|---|
| Recent XAUUSD setup snapshot | bar epoch `1790172000`; tick epoch `1790172408.061` | bar `2026-09-23T14:00:00Z`; tick `2026-09-23T14:06:48.061Z` | received `11:06:45.625Z`; observed `11:06:46.026Z`; `source_timestamp=null` | basis and data quality `UNVERIFIED`; raw epochs retained |
| Older XAUUSD setup snapshot linked to an outcome | raw epoch unavailable in legacy row | source timestamp persisted as `11:15Z` | observed `08:15:49.102Z` | linked source timestamp is 2h59m10.898s after observation; no `time_provenance` object |
| Linked 15m outcome | raw candle epoch unavailable in legacy row | outcome data-quality source timestamp `11:45Z` | resolved `08:45:07.336Z` | source timestamp is 2h59m52.664s after resolution; verification metadata is absent |

The first example's raw epochs, interpreted times, backend receive time, observation time, and quality are preserved in the append-only observation log. The audit API now returns up to five examples with these fields. The API also returns outcome examples with linked observation times, outcome source/resolution times, and quarantine reasons.

## Existing-data audit

At capture time, the read-only dataset audit found:

- 25,248 observations total; 9,704 prospective records with raw bar and tick provenance.
- 0 time-verified prospective observations; all 9,704 prospective records were time-unverified.
- 0 usable dataset observations.
- 66 market outcome records, all quarantined.
- 0 malformed JSONL lines.

Each of the 66 outcomes lacks outcome timestamp quality, outcome data-quality timestamp quality, outcome-time validity, and the structured outcome-time validation result. Each linked observation is also unverified under the current rules. Their former `data_quality.status="OK"` does not establish the timestamp basis. Historical raw candles are not persisted, so the OHLC path and its ordering cannot be independently reconstructed.

## Integrity decision

No historical record was rewritten or promoted. The 66 outcomes and all legacy/unverified observations remain excluded. The current audit reports the exact missing or invalid fields and fails closed on naive timestamps, future source timestamps, and outcomes whose linked observations are unverified.

New observations continue to use aware UTC backend timestamps. Until the MT5 epoch semantics for this actual terminal/server are independently resolved, source candle/tick time is stored as raw provenance with `UNVERIFIED` quality, and it is not admitted to research outcomes. Once verified, all normalized source timestamps and candidate candle times must be aware UTC instants, strictly after the decision time for outcomes, and chronologically ordered.

Tomorrow, query `GET /api/market/diagnostics/mt5-time?symbols=XAUUSD,EURUSD&bars=5` and compare its Python UTC sample with MT5's independently displayed server/chart clock. Record the terminal build, broker server, displayed server time and UTC time together. Repeat across a daylight-saving transition (or obtain the broker's written timezone/DST policy) before setting `TRADING_HUB_MT5_SOURCE_TIMEZONE`. Keep it unset while the readings disagree.

## Phase 8 (2026-09-24): broker time basis verified

Read-only investigation against the connected terminal: server `ICMarketsSC-Demo`
(Raw Trading Ltd), MetaTrader 5 IC Markets Global build 6182, MetaTrader5 Python
package 5.0.6180.

### Evidence

1. **Live offset.** For all 10 official instruments, the tick epoch minus the backend's
   UTC clock was +10,800.0 to +10,801.8 s: the MT5 epoch encodes the server wall clock,
   currently UTC+3 (the remainder is network/processing latency).
2. **Exchange opens as independent anchors** (largest M15 tick-volume surge, weekdays,
   server wall time read from the epoch):

   | Period | US500 / NAS100 (US cash open 09:30 New York) | GER40 (Xetra open 09:00 Frankfurt) |
   |---|---|---|
   | Winter, Jan 12 - Feb 6 2026 | 16:30 | 10:00 |
   | Mar 9-27 2026 (US DST on, EU off) | 16:30 | 11:00 |
   | Oct 27-31 2025 (US DST on, EU off) | 16:30 | 11:00 |
   | Summer, Jul 6-31 2026 | 16:30 | 10:00 |

   The US open is at server 16:30 in every regime, and the Xetra open moves only in the
   weeks where US and EU daylight saving disagree. Only **server = New York wall clock +
   7 h** fits all four rows: a fixed UTC+3 clock predicts 17:30 in winter; an EU-DST clock
   (e.g. `Europe/Athens`) predicts 15:30 in the mismatch weeks.
3. **Clock changes in 24/7 data.** BTCUSD M15 has no bars at server 09:15-09:45 on Sunday
   2026-03-08 (US spring-forward; server 09:00-10:00 does not exist) and merges the
   repeated hour on 2025-11-02 (US fall-back).
4. **FX week and day.** Every EURUSD week (57 weeks, Sep 2025 - Sep 2026, including the
   mismatch weeks) opens Monday 00:00 server and ends with the Friday 23:00 bar; D1 bars
   open at server 00:00 (= 17:00 New York, the FX day roll); H4 at server 00/04/.../20.
5. **Stored snapshots.** Under this basis, 3,000 recent stored snapshots re-normalize with
   median tick age -0.8 s (max 115 s), bar open 0-27 min before observation and no quality
   flags. A basis one hour off fails immediately (UTC+2: every source time in the future;
   UTC+4: every tick one hour stale).

### Standard

- **Canonical internal time:** timezone-aware UTC (ISO-8601 with `+00:00`), as before.
- **MT5 server time:** the wall clock of basis `America/New_York+07:00`
  (`TRADING_HUB_MT5_SOURCE_TIMEZONE`); UTC+3 during US daylight-saving time, UTC+2
  otherwise, switching on US dates (second Sunday of March, first Sunday of November).
- **Pipeline:** raw MT5 epoch -> server wall clock -> minus 7 h -> New York local time
  (IANA `America/New_York`, DST-aware) -> UTC instant -> display zone (UI shows UTC;
  performance reports use `TRADING_HUB_REPORTING_TIMEZONE`, default Africa/Nairobi).
  The host's local timezone is never used (tested under several `TZ` settings).
- **DST edges fail closed:** server times in the spring-forward gap are INVALID and the
  repeated fall-back hour is UNVERIFIED (ambiguous); such bars are dropped, not guessed.
  Both occur on Sunday mornings (server 09:00 / 08:00), so only 24/7 instruments are affected.
- Stored records keep their raw epochs and original fields; nothing is rewritten. Records
  written after the engine restarts with the basis carry verified provenance.

### Historical outcome audit (read-only, `time_reverification.py`)

Trendline confirmations, 252 (no S/R records exist in the real store yet):

| | Before (stored) | After (verified views + historical MT5 bars, existing outcome engine) |
|---|---|---|
| pending | 210 | 0 |
| unverified | 42 | 0 |
| verified target first | 0 | 55 |
| verified stop first | 0 | 102 |
| verified other (no hit / ambiguous) | 0 | 15 |
| not time-verifiable | - | 80 |

The 80: 58 confirmations were recorded before raw MT5 epochs were stored (before
2026-09-23 10:53 UTC), and 22 were backfilled from pre-episode legacy rows (no snapshot,
no raw epoch). The 66 stored outcome records remain quarantined: they carry no
outcome-level chronology proof, and records are not rewritten. The derived outcomes are
computed in memory only; persisting them would be a separate, explicit decision.

### Known limitation (not changed in Phase 8; resolved by trendline-first-v4, see SESSION_AB_REPORT.md)

`main.session_context` selects the London-session bars by reading raw MT5 epochs as UTC,
so its London high/low window is 2-3 hours early. On the cached real bars (1,200 hourly
samples) the London range differed in 90% of samples and the trendline
`session_alignment` input (+5 score and a reason) in 5.7%. The session label itself uses
the real clock and is correct. Fixing it changes live trendline scoring and needs an
explicit decision. **Resolved:** the Phase 9 A/B test measured the correction and it was adopted as
trendline-first-v4; records written before it keep trendline-first-v3 and are not rewritten.
