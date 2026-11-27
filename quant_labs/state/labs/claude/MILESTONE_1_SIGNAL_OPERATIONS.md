# Milestone 1 — Signal operations (CEO report, 2026-10-23)

## Completed

* **Audit of all 15 known strategies:**
  * All 15 are registered and scanning in the live registry. That's 4 Claude, 8 Codex and 3 Kimi, plus Compression Escape.
  * In the research ledger: Claude 16 versions, Codex 14, Kimi 6. Kimi's 6 research jobs are queued and not yet evaluated.
* **Delivery scope:**
  * Outbound Telegram is approved **only** for the two paper candidates, Index Trend-Day 0.2.0 and Crypto Trend Breakout 0.3.0. The approval record is `approvals/2026-10-23b_paper_candidates_only.json`.
  * The other 13 models are monitored internally, with paper signals and outcomes recorded but no outbound messages.
  * Enabling Compression Escape, Hourly Shock Drift and Index Gap Fade is prepared for your review in `approvals/PENDING_research_only_delivery_request.json`. I recommend not enabling them.
* **Message format (§1.3):**
  * researcher, strategy and version, instrument, direction, timeframe, actual entry, stop and target, and RR (planned and after estimated costs);
  * **WHY THIS SIGNAL?**, using the model's own rationale plus factual session, risk-in-ATR and spread context;
  * classification EXPERIMENTAL PAPER SIGNAL, plus a RESEARCH ONLY label where that applies;
  * the disclaimer and a unique signal ID.
* **Lifecycle (§1.4):**
  * Signals have unique IDs and durable states: detected, confirmed (market entry), active, TP, SL, time exit, unresolved, data conflict.
  * Outcomes are append-only revisions with net R after estimated costs.
  * An **outcome update** is sent only for signals that were actually delivered, once each.
  * Unresolved paths are never counted as wins.
  * Overlapping signals from the same model on the same instrument are excluded from statistics and counted separately.
  * Estimated costs are reported in R.
* **Diagnostics (Part 2):** per model, they separate:
  * evaluations with no setup;
  * setups;
  * insufficient data;
  * stale input;
  * quality-gate rejections (by reason);
  * worker or engine failures;
  * confirmed signals;
  * Telegram delivery states;
  * last successful evaluation;
  * closed candles never evaluated (outage or not scheduled).
* **Gate fix:** D1/H4 context was rejected as stale every Monday. That would have dropped 29% of Index Gap Fade's signals. It's now excused only for weekend hours actually spanned. No strategy rules changed.

## Tested

* New delivery suite: 16 tests, all passing. It covers:
  * approval and flag gates;
  * the exact format;
  * send-once across restarts;
  * crash and uncertain delivery never replayed;
  * failures and expiry;
  * outcome updates;
  * overlap exclusion;
  * each diagnostic category;
  * the weekend staleness rule;
  * an **end-to-end replay of all five integrated strategies on genuine historical MT5 snapshots**, through the real runtime, workers, delivery and resolution.
* Existing quant_live and provider tests: 25, all passing.
* **Full backend regression:** 57 of 60 test files pass. The other three are pre-existing or environmental, not caused by these changes:
  * `test_market_data`: affected by the existing `.env` quant-live flag;
  * `test_quant_live`: an import-path artefact, and it passes from `tests/`;
  * `test_observation_index`: replays the full real data store and exceeded 25 minutes, so it was not completed.
* **Telegram bot:** a clearly labelled delivery test reached your chat earlier today (message 118).

## Operational now

* TradeDen engine: MT5 connected, scanner READY, execution disabled.
* All 15 models are scanning.
* Since the 21:44 UTC restart, recorded evaluations (314) cover all expected model × instrument × candle combinations (264). The rotating consumer is **not** skipping candles.
* **0 signals so far.** That's consistent with conditions genuinely not being met during a short window, plus the engine being offline on 10-21. It is not a fault.

## Blocked: needs your action

* **Engine restart.** The new delivery, diagnostics and gate code only takes effect after the market engine restarts. The session's permission system blocked me from restarting production.
* Restart with `STOP TRADING HUB.bat` then `START TRADING HUB.bat`, or authorise me to do it.
* **Live delivery is not yet verified.** No qualifying signal has passed through the complete pipeline yet. It will be verified on the first real paper-candidate signal after the restart.

## Requires your approval

1. Engine restart (above).
2. The research-only delivery request (recommended: decline).
3. Pushing the commit `7afd025` (local only, not pushed).

## Next (Milestone 2)

* Research audit and A/B/C/D classification of all strategies, including Codex's Trend Reclaim and Range Sweep cells and Kimi's three families.
* Statistical significance, cost survival, period stability, variant correlation and dependence on single trades.
