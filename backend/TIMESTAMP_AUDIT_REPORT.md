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
