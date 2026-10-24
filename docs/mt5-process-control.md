# Tradeden process control — 24 October 2026

The owner controls in the repository root are:

- `START TRADING HUB.bat`: start or resume the managed engine and watchdog; opens the existing dashboard launcher.
- `PAUSE TRADING HUB.bat`: suspend scanning, notifications, outcomes, strategy-bank work and scheduled reports. Keep the dashboard API available. Data and approval settings are retained.
- `STOP TRADING HUB.bat`: persist STOPPED, gracefully stop the managed engine and exit the watchdog. MT5 and the dashboard frontend remain under owner control; no applications are killed by port or executable name.

From `backend`, the equivalent commands are `python -m ops.control start|resume|pause|stop|status`.
Use these controls instead of launching uvicorn directly. State is local, ignored by Git, in `backend/data/ops/control.json` (override with the absolute `TRADEDEN_CONTROL_FILE` environment variable consistently in every launcher). Atomic writes and a writer lock prevent a late connection failure from undoing STOPPED. Missing or corrupt intent means STOPPED.

## Investigation

Commit `27c40d1` hid watchdog launches; it did not change MT5 recovery. At inspection, one scheduled task (`TradeDen Engine Watchdog`, logon trigger, IgnoreNew) ran one pythonw watchdog. Its child was the uvicorn engine; MT5 PID 23216 was a direct child of that engine PID 26244. No second watchdog or active deployment supervisor was found. The CompanyHQ Tradeden bridge task was disabled.

`ensure_mt5()` called `mt5.initialize()` again when terminal information disappeared. That API can launch MT5, so health requests and autonomous scans reopened a manually closed terminal. The old STOP launcher force-killed whichever processes listened on ports 8000/5173 and did not tell the watchdog to stop. The watchdog could therefore undo intentional engine shutdown.

## Recovery policy

RUNNING permits bounded engine crash recovery (three absent-port checks, four-minute launch grace, three launches per hour per watchdog lifetime). The watchdog never kills a degraded live engine. Engine and watchdog each hold a separate exclusive local socket to reject duplicate managed instances. All automated launches retain CREATE_NO_WINDOW and file logging; no cmd wrapper is used.

PAUSED disables engine recovery and starts no background workers. A state transition drains the active lifespan and briefly rebinds the API. Resume uses existing configuration and starts a fresh worker lifespan. STOPPED exits the engine and watchdog. An ordinary managed engine exit also records STOPPED; an unexpected exception leaves recovery enabled. Task Manager force-kill is indistinguishable from a crash: use the owner STOP control for intentional shutdown.

Windows logon respects saved intent: RUNNING can recover, STOPPED stays stopped, and missing/corrupt intent cannot launch MT5. PAUSED is not automatically recovered if its API process is absent.

Broker disconnects retain the IPC session and let MT5 reconnect itself, without invoking initialize again. A vanished terminal, liveness exception or failed initialization changes RUNNING to PAUSED and requires explicit resume. The MT5 API cannot reliably distinguish a terminal crash from closing its window; both conservatively pause. An explicit start/resume may initialize/launch the configured MT5 terminal. Tradeden never terminates an MT5 installation.

Broker execution remains disabled. No Telegram category, qualification rule, strategy configuration, data store or research history is changed. Telegram sends already in flight may finish while workers drain. A pre-existing experimental report rendering error with missing uptime coverage now displays `unknown`.

## Verification

- Unit tests simulate MT5 loss, broker disconnection, initialization failure, graceful engine exit, engine exceptions, saved intent, inactive recovery, launch limits and duplicate guards.
- `python tests/smoke_process_control.py` tests an actual PAUSED API, inactive Telegram/report workers, duplicate engine rejection and STOPPED exit using temporary data and without initializing MT5.
- `python tests/run_suite.py` runs isolated backend regressions. Set `TRADEDEN_CONTROL_FILE` to a temporary file and initialize it to RUNNING for scanner fixtures; never point tests at owner intent.
- Live operational observations and final suite results are recorded in the delivery message.

Shutdown waits for in-flight scans and network operations. A hung native MT5 call may delay graceful shutdown; the controls intentionally avoid killing unrelated applications. Separate deployment supervision must use the same control file; its readiness-based policy is retained, and it now checks owner intent before launching a replacement.

## Observed delivery results

The full isolated backend suite passed 696 tests (two skipped); subsequent focused checks cover the added persisted-pause and keyboard-interrupt cases. The dashboard suite passed all 187 tests. Live RUNNING connected to the existing MT5 process, completed scans of 16 markets with all four production strategies reporting zero errors, and ran the existing Telegram/report/outcome/bank workers with broker execution disabled. Live PAUSED drained those workers and retained the API. The identified MT5 window was closed normally once while PAUSED and stayed absent beyond the 60-second watchdog interval. Final STOPPED shutdown exited both managed processes; MT5 remained closed and the scheduled task was Ready. No scripted terminal restart loop was used, and no test Telegram messages were sent.
