# T-031 Telegram integration: BUILD / VERIFY report

Status: **BUILD and VERIFY complete. Phase 1 connectivity verified: bot @tradedensignalbot reachable, private chat ID stored in backend/.env, test message accepted by Telegram (message_id 4) and receipt confirmed by the owner on 2026-10-19. CEO approved activation on 2026-10-19: live alerts are ON.**
Branch: `codex/commercial-mvp-phase1` (not committed yet). Date: 2026-10-19.

## What was built

| File | Purpose |
|---|---|
| `telegram_notifier.py` | Bot API client, notification history, signal and outcome notifier, engine thread |
| `telegram_setup.py` | `check` / `discover` (stores the chat ID) / `test` (sends the test message) / `status` |
| `main.py` (+7 lines) | starts the notifier thread in `lifespan` only when enabled; `/api/health` → `telegram_alerts` |
| `tests/test_telegram_notifier.py` | 24 tests: unit, reliability and an end-to-end test on the real stores |
| `.env.example`, `README.md` | configuration and runbook |

There are no changes to strategies, qualification, risk parameters, the scanner path or execution.

## How signals are selected (Phase 2)

The source is the existing `setup_confirmations.jsonl`. A confirmation is sent only when **all** of these hold:
- it is not shadow, and its strategy is LIVE in the registry
- its snapshot has `strategy_valid` = true and the executable-price qualification has `qualified` = true
- its plan has a direction, entry, stop loss and take profit
- its lifecycle state is not INVALIDATED, EXPIRED or RESOLVED
- it was confirmed less than 10 minutes before it is first seen

The plan values are the immutable ones the signal was confirmed with (`observations.confirmed_plan`). R:R is the executable value (spread included). Time is shown in EAT (UTC+3).

## Outcomes (Phase 3)

Outcomes are tracked only for signals that were actually alerted. The notifier uses `strategy_lab.classify_outcome`, the same verified rule the Strategy Lab and performance report use. A follow-up is sent only on a verified WIN (TP) or LOSS (SL). Pending, unverified, NO_HIT and AMBIGUOUS outcomes send nothing, and tracking stops after 48 hours. Each message says it describes the signal's market path, **not an executed trade**.

## Reliability (Phase 4)

- **Persistent history:** decisions are stored in `data/telegram_notifications.jsonl` (gitignored), keyed `signal:<setup_id>` and `outcome:<setup_id>`. This stops duplicates, including across restarts.
- **No replay:** on first activation, every existing confirmation becomes `baseline` and is never sent. A confirmation found late after downtime is skipped. An alert still undelivered after 30 minutes is marked `expired`, not sent late.
- **Retries:** 429 waits for `retry_after` and pauses the queue. 5xx and network errors back off exponentially (up to 8 attempts, capped at 300 s). Other 4xx errors fail at once.
- **Pacing:** at most about 1 message per second.
- **Non-blocking:** the notifier runs in its own `tradeden-telegram-notifier` thread. Each tick reads only the newly appended bytes of the confirmation file, and uses indexed lookups for snapshots, lifecycle and outcomes.
- **No dashboard needed:** it runs inside the backend process, so alerts work with the dashboard closed.
- **Token never exposed:**
  - It is read only from the environment and never logged.
  - Bot API errors are redacted and not chained.
  - `httpx` request logging is raised to WARNING.
  - `/api/health` shows no token and no chat ID.

## Verification (Phase 5)

- `python tests/run_suite.py`: **507 tests, OK** (483 existing + 24 new).
- New tests cover these cases:
  - **Sending:** messages go out, and every field is in the message.
  - **Signal selection:** BUY/SELL mapping is correct. Shadow, non-LIVE, unqualified, invalid, incomplete-plan, invalidated/expired/resolved and stale confirmations are not sent.
  - **Duplicates and replay:** duplicates are prevented across restarts, history is not replayed on activation or after downtime, and a partially written line is handled.
  - **Delivery failures:** 5xx/network retries, 429 `retry_after`, permanent 4xx and expiry.
  - **Outcomes:** TP and SL follow-ups are sent once each. Nothing is sent for unverified outcomes or signals that were never alerted.
  - **Isolation:** alerts are disabled by default and the scanner code never references Telegram. A hanging Telegram call does not block other threads. Steady-state tick cost is under 50 ms with 2,000 confirmations.
  - **End-to-end on the real stores:** `record_markets` → confirmation → alert. A detected-only setup and one that fails 1.5R at the executable price are not sent, and a repeat is not re-sent. Then `resolve_due_market_outcomes` → verified TP → follow-up.
- **Scanner performance:** the scan code path is unchanged. With alerts disabled, no thread is started.

## Activation (2026-10-19, CEO approved)

- `TRADEDEN_TELEGRAM_ALERTS_ENABLED=1` was set in `backend/.env`, and the engine was restarted on port 8000.
- `/api/health` → `telegram_alerts`: enabled, configured, running, no error. MT5 is CONNECTED and scans are completing.
- First activation recorded all 395 existing confirmations as `baseline`. No historical signal was sent.

## Outstanding

1. Regenerate the bot token with BotFather (`/revoke`), because it was pasted into a chat. Put the new token in `backend/.env`, run `python telegram_setup.py check`, and restart the engine.
2. In production, add the three `TRADEDEN_TELEGRAM_*` keys to the protected runtime JSON.
