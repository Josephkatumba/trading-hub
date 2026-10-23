# Codex contributions audit — 23 October 2026 (EAT)

## Findings and counting rules

Compression Escape is the only Codex family integrated into the current live paper scanner. The complete record is larger: **8 provider-compatible executable models across 3 families**, plus **5 earlier executable H1 backtest hypotheses**. There are **13 trading strategy IDs** in the shared research registry, plus one non-strategy evaluation fixture (14 registry rows total). Registration is not qualification or scanner integration.

The earlier H1 Compression Release and later M15 Compression Escape share compression-to-expansion economics. Counting them as separate independent discoveries would inflate the contribution. Across all history, there are **8 named research lines, or 7 broad entry mechanisms after combining those compression implementations**. Persistent drift and trend pullback/reclaim also share a broad momentum theme, although their entry mechanisms differ. These taxonomy counts are descriptive, not evidence of return independence. No correlation-based independence claim is made.

## Full strategy inventory and every version

| Research line | Version / variations | Implemented mechanism and exits | Integration / disposition |
|---|---|---|---|
| Drift48 | 1.0.0; 16 instrument cases | H1 48-return normalized directional drift and efficiency; four UTC decision times; 2 ATR stop, 1.5R target, 24h horizon | Executable offline H1 runner; imported research registration; no live adapter; unqualified |
| Robust Revert | 1.0.0; 16 cases | H1 median/MAD extreme plus first reversal; 1.5 ATR stop; frozen median target, minimum 1R; 12h | Executable offline runner; research registration only; unqualified |
| Compression Release | 1.0.0; 16 cases | Prior 12 H1 range compression then 0.1 ATR escape; 1.5 ATR stop, 2R target, 12h | Executable offline runner; research registration only; related to Compression Escape |
| Shock Fade | 1.0.0; 16 cases | Large H1 shock followed by midpoint reversal; stop beyond shock; target shock open, minimum 1.2R; 6h | Executable rules; no qualified final-test entries; research registration only |
| Relative Lag | 1.0.0; BTCUSD and ETHUSD supported; 14 unsupported cases | Rolling BTC/ETH OLS residual extreme fade; unhedged single leg; 1.5 ATR stop, 1.5R target, 6h | Executable offline runner; research registration only; not market-neutral arbitrage |
| Compression Escape | 0.1.0; conditional 3R/4R exits inside one model | Closed M15 24-bar range escape with H1 persistence; structural 0.5–3 ATR risk; 12h | Provider executable; shared research and live registry; experimental paper scanner enabled |
| Trend Reclaim | All 0.1.0: r2, r3, r4, r5, r7, r9; horizons 6/8/12/18/24/36h | Persistent H1 EMA20/50 trend, slope/efficiency; M15 pullback reclaim; structural 0.5–3 ATR risk; cost-buffered targets | Six complete provider executables; shared research registration/evaluation; not live registered; unqualified |
| Range Sweep Reversion | 0.1.0; three instrument cases | Low-persistence H1; failed M15 range escape; target opposite observed boundary, capped at 9 gross R; minimum 2 net planned R; 12h | Complete provider executable; shared research registration/evaluation; not live registered; unqualified |

No other Codex model versions were found in its workspace, source registry or saved run history. The two October 19 H1 run directories preserve a correctness rerun of the same five 1.0.0 hypotheses, not five additional strategies. Their hypothesis-source hash is identical. Execution foundation versions and fixture revisions are infrastructure versions, not strategy versions. The 3R/4R Compression Escape branch is a conditional exit rule, not two separately tested models.

All six Trend Reclaim source files differ in the declared target constant; the target determines the horizon. They must not be counted as six independent entry discoveries. Market cases, normal/stress accounting, train/validation/test splits, and reruns are experimental variations, not additional families.

## Historical evidence and out-of-sample meaning

Training: 15 October 2024–30 September 2025. Validation: 1 October 2025–31 March 2026. Final historical test: 1 April–30 September 2026. The dataset was already exposed to earlier research. These are chronological historical splits, not a fresh firm-wide holdout or prospective trading. R is simulated net return per planned risk unit. Expectancy excludes unresolved outcomes; their counts remain explicit. Aggregated standalone streams overlap and are not a portfolio. Cost/financing assumptions are proxies, not certified historical account charges.

### Earlier H1 research: final-test family aggregates

80 preregistered hypothesis/instrument cases; 66 supported and 14 unsupported; 11,188 standalone plans across the complete historical run. All 66 supported cases were NOT_QUALIFIED. Provisional labels: 57 NEEDS_DATA, 8 REJECTED, 1 REVIEW_ONLY, plus 14 UNSUPPORTED. The five implementations reside in `research_autonomous/hypotheses.py` and are driven by `experiment.py`; these are working backtest code, not merely ideas, but do not implement the live detect(snapshot) contract.

| Line | Resolved / unknown | Net R | Test expectancy R | Stress expectancy R |
|---|---:|---:|---:|---:|
| drift48 | 303 / 120 | -30.178 | -0.100 | -0.190 |
| robust_revert | 922 / 203 | -180.117 | -0.195 | -0.320 |
| compression_release | 803 / 92 | -103.892 | -0.129 | -0.203 |
| shock_fade | 0 / 0 | +0.000 | — | — |
| relative_lag | 204 / 3 | -17.789 | -0.087 | -0.150 |

Explicit provisional REJECTED cells: robust_revert@1.0.0:BTCUSD, compression_release@1.0.0:BTCUSD, relative_lag@1.0.0:BTCUSD, compression_release@1.0.0:EURUSD, compression_release@1.0.0:GBPUSD, compression_release@1.0.0:USDCAD, robust_revert@1.0.0:NZDUSD, compression_release@1.0.0:GBPJPY.

Compression Release/EURJPY was REVIEW_ONLY: test +0.121R expectancy on 62 resolved / 3 unknown, stressed +0.063R; 95% weekly interval [-0.197, +0.418]R and Holm p=1.0. Its training expectancy was -0.005R and validation -0.222R. It was not qualified. Shock Fade produced no final-test executable trades; its reversal/stop/target geometry was infeasible or insufficiently attractive. Zero trades is not evidence of positive expectancy.

Three executable selection overlays were also tested, not three new entry families:

| Overlay | Test resolved / unknown | Net R | Test expectancy R |
|---|---:|---:|---:|
| static_diverse | 659 / 137 | -112.310 | -0.170 |
| train_market | 0 / 0 | +0.000 | — |
| train_regime | 0 / 0 | +0.000 | — |

Train-market and train-regime selectors selected no final-test trades under their rules; they did not discover positive strategies.

### Trend Reclaim and Range Sweep: every model/market test

21 cases: 18 canonical COMPLETE and 3 canonical FAILED with PermissionError(13). Exact immutable requests for the three failures completed through the same frozen evaluator in clean temporary directories. Those are supplemental recovery results; original FAILED ledger states remain. No operational failure was relabeled as a statistical rejection.

| Model | Market | Train E[R] | Validation E[R] | Test E[R] | Stress test E[R] | Test resolved / unknown | Test net R | Record |
|---|---|---:|---:|---:|---:|---:|---:|---|
| trend_reclaim_r2 | EURUSD | +0.144 | -0.915 | -0.120 | -0.231 | 18 / 1 | -2.165 | canonical complete |
| trend_reclaim_r3 | EURUSD | -0.141 | -0.557 | -0.567 | -0.676 | 17 / 1 | -9.636 | canonical complete |
| trend_reclaim_r4 | EURUSD | -0.251 | -0.662 | -0.821 | -0.931 | 16 / 1 | -13.135 | canonical complete |
| trend_reclaim_r5 | EURUSD | -0.271 | -0.580 | -0.955 | -1.068 | 16 / 1 | -15.287 | canonical complete |
| trend_reclaim_r7 | EURUSD | -0.425 | -0.418 | -1.030 | -1.142 | 16 / 1 | -16.474 | canonical complete |
| trend_reclaim_r9 | EURUSD | -0.341 | -0.189 | -1.108 | -1.221 | 16 / 1 | -17.726 | canonical complete |
| range_sweep_reversion | EURUSD | -0.288 | -0.389 | +0.482 | +0.333 | 22 / 0 | +10.606 | canonical complete |
| trend_reclaim_r2 | XAUUSD | +0.268 | -0.158 | +0.311 | +0.303 | 11 / 1 | +3.420 | canonical complete |
| trend_reclaim_r3 | XAUUSD | +0.110 | -0.783 | -0.879 | -0.887 | 12 / 3 | -10.548 | supplemental retry |
| trend_reclaim_r4 | XAUUSD | +0.126 | -0.727 | -0.810 | -0.819 | 12 / 3 | -9.721 | canonical complete |
| trend_reclaim_r5 | XAUUSD | -0.105 | -0.671 | -0.872 | -0.880 | 11 / 3 | -9.587 | canonical complete |
| trend_reclaim_r7 | XAUUSD | -0.626 | -1.007 | -1.008 | -1.017 | 10 / 4 | -10.077 | canonical complete |
| trend_reclaim_r9 | XAUUSD | -0.477 | -1.007 | -1.008 | -1.017 | 10 / 4 | -10.077 | canonical complete |
| range_sweep_reversion | XAUUSD | -0.124 | +0.911 | -1.010 | -1.024 | 10 / 1 | -10.101 | canonical complete |
| trend_reclaim_r2 | BTCUSD | +0.097 | -0.107 | +0.354 | +0.321 | 20 / 0 | +7.084 | canonical complete |
| trend_reclaim_r3 | BTCUSD | -0.113 | +0.241 | +0.053 | +0.005 | 22 / 0 | +1.165 | supplemental retry |
| trend_reclaim_r4 | BTCUSD | +0.195 | +0.265 | +0.330 | +0.285 | 21 / 0 | +6.932 | canonical complete |
| trend_reclaim_r5 | BTCUSD | -0.068 | +0.449 | +0.585 | +0.545 | 19 / 0 | +11.110 | canonical complete |
| trend_reclaim_r7 | BTCUSD | -0.168 | +0.286 | +0.817 | +0.771 | 18 / 0 | +14.712 | supplemental retry |
| trend_reclaim_r9 | BTCUSD | +0.144 | +0.269 | +0.636 | +0.580 | 16 / 0 | +10.170 | canonical complete |
| range_sweep_reversion | BTCUSD | -0.093 | -0.146 | +0.371 | +0.325 | 20 / 1 | +7.424 | canonical complete |

None of the seven candidates was certified or admitted live. Test samples contain only 10–22 resolved outcomes per cell. The smallest raw positive-edge weekly p-value exceeded 0.05 before multiple-testing adjustment; the phase report recorded a shared testing family of 131 at that time (not a claim about today’s global denominator). Positive BTC Trend Reclaim and EURUSD Range Sweep cells are exploratory, correlated findings, not established independent edges. Negative EURUSD higher-R Trend Reclaim and XAUUSD Range Sweep results are retained and argue against promotion as tested.

### Compression Escape: later external historical evaluation

The Codex-authored model has a later evaluation in Claude’s workspace. This is **Claude-run evaluation of Codex source**, not additional backtesting work claimed by Codex. Recorded source SHA matches the current Codex executable and live registry: `e1544089d460ed90050b1db223143581cb907963b9f3446f20fb1023690d54f9`. The saved evaluator is tradeden-shared-eval-1.0.0 on the same immutable dataset; this audit inspected its evidence, not reran the experiment.

| Split | Resolved / unknown | Net R | Expectancy R | Stress expectancy R |
|---|---:|---:|---:|---:|
| train | 430 / 116 | -22.092 | -0.051 | -0.114 |
| validation | 242 / 54 | -66.571 | -0.275 | -0.321 |
| test | 208 / 44 | -1.059 | -0.005 | -0.073 |

| Market | Train E[R] | Validation E[R] | Test E[R] | Stress test E[R] | Test resolved / unknown |
|---|---:|---:|---:|---:|---:|
| BTCUSD | +0.190 | -0.343 | -0.360 | -0.407 | 27 / 1 |
| ETHUSD | -0.377 | -0.289 | -0.496 | -0.605 | 15 / 1 |
| EURUSD | -0.057 | -0.369 | +0.413 | +0.339 | 28 / 2 |
| GBPJPY | -0.285 | +0.309 | +0.383 | +0.171 | 26 / 1 |
| GBPUSD | +0.162 | -0.513 | -0.263 | -0.328 | 31 / 2 |
| GER40 | -0.058 | -0.285 | -0.288 | -0.308 | 15 / 9 |
| NAS100 | -0.007 | -0.167 | +0.157 | +0.140 | 30 / 10 |
| US500 | -0.152 | -0.616 | -0.499 | -0.552 | 13 / 11 |
| XAUUSD | -0.154 | -0.510 | +0.384 | +0.378 | 23 / 7 |

Compression Escape test aggregate is approximately flat before stress and negative under stress. Its weekly test expectancy interval is [-0.225, +0.207]R. Positive individual markets do not erase negative validation or establish qualification. Historical opportunities existed; zero current paper detections does not mean this executable can never generate an intent.

## Registration, actual scanning, and unfinished integration

Current read-only checks confirm 13 strategy IDs in the shared research control SQLite database. The first five H1 entries import earlier research; they have no strategy jobs in the common queue. Compression Escape has a research-source entry but no Codex common-queue historical job. The other seven executables have 21 common-queue jobs (18 COMPLETE, 3 FAILED). One COMPLETE evaluation_contract_smoke job and its registry entry are infrastructure testing and must be excluded from strategy counts.

Live registry: only **codex/compression_escape/0.1.0**, status EXPERIMENTAL, scan_enabled=1. It is not VERIFIED. At observation, the common consumer was enabled/running, MT5 connected, with no current runtime error. Retained run evidence contains **269 COMPLETE Codex source executions and zero decisions**; latest retained execution was 23 October 2026 02:45:35 EAT. The live signals table contains **zero Codex signals**, so there is no forward paper expectancy, win rate or outcome evidence to report. These are retained records, not a guarantee of full uninterrupted coverage since launch.

The current Codex alert_enabled field is 1, unlike the zero recorded in the earlier session handoff. The observed global delivery mode remains DRY_RUN with outbound activation approval false; execution_enabled is false. This audit made no permission change. Existing uncommitted work from other sessions was present before the audit and was left untouched.

Not live integrated: all six Trend Reclaim variants and Range Sweep Reversion (complete compatible source; need separate reviewed paper admission), plus all five H1 implementations (need genuine live adapters and review; their original <2R configurations are not automatically compatible with the later minimum-2-net-R paper gate). No missing strategy should be silently changed to satisfy that gate under its old version.

“Under development” is not an active autonomous job: the seven offline candidates are implemented but unqualified research, and their live integration is incomplete. No evidence shows a Codex strategy-development process continuing after the session ended on October 20. Compression Escape continues paper observation; this does not mean research itself runs without a session. No additional partially implemented Codex model or undeclared version was found.

## Ideas versus executable contributions

The five H1 hypotheses and eight provider models are executable. Evaluation fixtures, accounting fixes, backtest competition, allocation profiling, lab registration, safety gates and dashboard work are infrastructure contributions, not strategies. ML and centralized-volume/order-flow/order-book mechanisms were discussed or deferred; no executable Codex strategy of those types was found and none is counted. Synthetic fixtures and synthetic previews are not discoveries or forward performance.

## What limited discovery, and what would help

1. **Research effort allocation and breadth.** Much of my session repaired measurement, built the shared labs, integrated the provider, investigated data and memory, and prepared handoffs. The later phase explored two new mechanisms over only three markets; six of seven new files varied exits. That was a narrow discovery effort. Infrastructure work and parameter variants do not compensate for a lack of independently tested mechanisms.
2. **Finite sessions.** My development session was explicitly concluded on October 20. The engine can keep scanning a fixed model, but it does not create or evaluate new ideas. A separately authorized research session or bounded scheduled research job with checkpoints is needed for sustained discovery.
3. **Data and identification.** Existing broker histories are reused, incomplete in places, and share a largely price-only feature space. Short M1 history, bid-bar spread proxies, unverified historical sessions/ask extremes and financing reduce confidence. Longer clean bid/ask/tick history, account-specific costs and calendars, and a sealed future period would help distinguish real mechanisms from artifacts. Event/calendar, cross-market or market-microstructure mechanisms would need appropriate timestamped licensed data; MT5 tick volume cannot substitute for centralized volume.
4. **Protocol scope.** The current provider supports single-instrument market-paper entries, fixed SL/TP and horizons. It cannot honestly express hedged pairs, multi-leg relative value, staged entries or dynamic exits without a separately reviewed versioned protocol extension. This narrows the mechanisms that can be integrated. It does not prevent researching broader hypotheses offline.
5. **Small samples and multiple comparisons.** The newest test cells are tiny; six targets are correlated trials. More retuning on the same history would not produce independent evidence. Predeclare economically distinct mechanisms, disclose all trials, use rolling validation and then a genuinely new holdout/prospective interval. Keep rejection criteria and opportunity capture complete.
6. **Operational limits.** The engine was memory-heavy and three evaluator jobs failed on file access. The later working tree contains runtime-relocation work by other sessions; this audit does not claim those earlier issues remain unfixed. Dedicated nonsynchronized scratch storage, reproducible checkpoints and bounded research workers would reduce friction. Live laptop worker limits should remain; there is no evidence a GPU or larger model is the first bottleneck.

No strategy-count cap, absent Claude/Kimi session, or required 60–70% win rate prevented my own discovery. The main controllable limitation was research prioritization and a narrow set of price mechanisms. A useful next mandate would allocate explicit time to independent mechanisms and a predeclared validation plan, rather than a quota of model files or a promised hit rate. These are proposals only; nothing was activated during this audit.

## Appendix: all 80 original H1 case registrations

| Strategy | Market | Recorded state | Train E[R] | Validation E[R] | Test E[R] | Stress test E[R] | Test resolved / unknown |
|---|---|---|---:|---:|---:|---:|---:|
| drift48 | XAUUSD | NEEDS_DATA | -0.173 | -0.320 | +0.664 | +0.661 | 6 / 20 |
| robust_revert | XAUUSD | NEEDS_DATA | -0.550 | -0.658 | -0.902 | -0.907 | 26 / 28 |
| compression_release | XAUUSD | NEEDS_DATA | -0.010 | +0.056 | -0.704 | -0.708 | 10 / 11 |
| shock_fade | XAUUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | XAUUSD | UNSUPPORTED | — | — | — | — | — |
| drift48 | XAGUSD | NEEDS_DATA | -0.437 | +0.490 | +0.234 | +0.204 | 2 / 16 |
| robust_revert | XAGUSD | NEEDS_DATA | -0.479 | -0.651 | -0.749 | -0.780 | 21 / 28 |
| compression_release | XAGUSD | NEEDS_DATA | -0.196 | -1.022 | -0.790 | -0.821 | 13 / 16 |
| shock_fade | XAGUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | XAGUSD | UNSUPPORTED | — | — | — | — | — |
| drift48 | BTCUSD | NEEDS_DATA | +0.069 | +0.007 | +0.098 | -0.070 | 37 / 3 |
| robust_revert | BTCUSD | REJECTED | -0.064 | -0.167 | -0.039 | -0.072 | 123 / 6 |
| compression_release | BTCUSD | REJECTED | -0.020 | +0.275 | -0.148 | -0.204 | 91 / 3 |
| shock_fade | BTCUSD | NEEDS_DATA | -0.148 | — | — | — | 0 / 0 |
| relative_lag | BTCUSD | REJECTED | -0.003 | +0.029 | -0.062 | -0.100 | 158 / 2 |
| drift48 | ETHUSD | NEEDS_DATA | +0.127 | -0.037 | -0.166 | -0.311 | 18 / 7 |
| robust_revert | ETHUSD | NEEDS_DATA | -0.180 | -0.298 | -0.164 | -0.376 | 44 / 5 |
| compression_release | ETHUSD | NEEDS_DATA | +0.010 | -0.097 | -0.263 | -0.478 | 23 / 2 |
| shock_fade | ETHUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | ETHUSD | NEEDS_DATA | -0.097 | -0.208 | -0.175 | -0.324 | 46 / 1 |
| drift48 | EURUSD | NEEDS_DATA | -0.089 | -0.056 | +0.086 | +0.026 | 21 / 2 |
| robust_revert | EURUSD | NEEDS_DATA | -0.121 | -0.150 | -0.185 | -0.266 | 64 / 5 |
| compression_release | EURUSD | REJECTED | +0.156 | -0.244 | -0.234 | -0.291 | 86 / 2 |
| shock_fade | EURUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | EURUSD | UNSUPPORTED | — | — | — | — | — |
| drift48 | GBPUSD | NEEDS_DATA | +0.067 | -0.109 | -0.115 | -0.171 | 22 / 2 |
| robust_revert | GBPUSD | NEEDS_DATA | -0.160 | -0.132 | -0.171 | -0.239 | 67 / 5 |
| compression_release | GBPUSD | REJECTED | +0.098 | -0.057 | -0.098 | -0.178 | 81 / 2 |
| shock_fade | GBPUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | GBPUSD | UNSUPPORTED | — | — | — | — | — |
| drift48 | USDJPY | NEEDS_DATA | -0.089 | +0.052 | -0.363 | -0.421 | 19 / 2 |
| robust_revert | USDJPY | NEEDS_DATA | -0.007 | -0.197 | -0.037 | -0.239 | 76 / 7 |
| compression_release | USDJPY | NEEDS_DATA | +0.157 | -0.243 | -0.027 | -0.077 | 54 / 1 |
| shock_fade | USDJPY | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | USDJPY | UNSUPPORTED | — | — | — | — | — |
| drift48 | USDCHF | NEEDS_DATA | -0.205 | +0.171 | -0.276 | -0.538 | 19 / 2 |
| robust_revert | USDCHF | NEEDS_DATA | -0.236 | -0.227 | -0.357 | -0.661 | 75 / 6 |
| compression_release | USDCHF | NEEDS_DATA | +0.084 | +0.071 | -0.270 | -0.462 | 57 / 3 |
| shock_fade | USDCHF | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | USDCHF | UNSUPPORTED | — | — | — | — | — |
| drift48 | USDCAD | NEEDS_DATA | +0.004 | +0.233 | -0.218 | -0.276 | 33 / 3 |
| robust_revert | USDCAD | NEEDS_DATA | -0.191 | -0.126 | -0.209 | -0.320 | 77 / 11 |
| compression_release | USDCAD | REJECTED | -0.088 | -0.280 | -0.035 | -0.106 | 78 / 4 |
| shock_fade | USDCAD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | USDCAD | UNSUPPORTED | — | — | — | — | — |
| drift48 | AUDUSD | NEEDS_DATA | -0.136 | +0.371 | -0.351 | -0.410 | 24 / 3 |
| robust_revert | AUDUSD | NEEDS_DATA | -0.030 | -0.186 | -0.071 | -0.158 | 81 / 6 |
| compression_release | AUDUSD | NEEDS_DATA | -0.099 | -0.021 | -0.165 | -0.240 | 55 / 3 |
| shock_fade | AUDUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | AUDUSD | UNSUPPORTED | — | — | — | — | — |
| drift48 | NZDUSD | NEEDS_DATA | +0.050 | +0.390 | -0.294 | -0.414 | 31 / 4 |
| robust_revert | NZDUSD | REJECTED | -0.006 | +0.038 | -0.161 | -0.238 | 69 / 3 |
| compression_release | NZDUSD | NEEDS_DATA | -0.155 | +0.014 | -0.003 | -0.074 | 42 / 2 |
| shock_fade | NZDUSD | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | NZDUSD | UNSUPPORTED | — | — | — | — | — |
| drift48 | EURJPY | NEEDS_DATA | -0.562 | +0.059 | -0.104 | -0.150 | 20 / 3 |
| robust_revert | EURJPY | NEEDS_DATA | -0.087 | -0.167 | -0.110 | -0.288 | 70 / 9 |
| compression_release | EURJPY | REVIEW_ONLY | -0.005 | -0.222 | +0.121 | +0.063 | 62 / 3 |
| shock_fade | EURJPY | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | EURJPY | UNSUPPORTED | — | — | — | — | — |
| drift48 | GBPJPY | NEEDS_DATA | -0.343 | -0.087 | +0.024 | -0.037 | 25 / 5 |
| robust_revert | GBPJPY | NEEDS_DATA | +0.061 | -0.183 | +0.050 | -0.199 | 69 / 7 |
| compression_release | GBPJPY | REJECTED | -0.055 | -0.318 | -0.062 | -0.151 | 66 / 1 |
| shock_fade | GBPJPY | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | GBPJPY | UNSUPPORTED | — | — | — | — | — |
| drift48 | NAS100 | NEEDS_DATA | -0.265 | -0.417 | +0.247 | +0.239 | 12 / 15 |
| robust_revert | NAS100 | NEEDS_DATA | -0.528 | -0.444 | -0.609 | -0.616 | 18 / 30 |
| compression_release | NAS100 | NEEDS_DATA | -0.142 | +0.267 | -0.186 | -0.195 | 33 / 11 |
| shock_fade | NAS100 | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | NAS100 | UNSUPPORTED | — | — | — | — | — |
| drift48 | US500 | NEEDS_DATA | -0.482 | +0.550 | -0.103 | -0.129 | 11 / 14 |
| robust_revert | US500 | NEEDS_DATA | -0.250 | -0.393 | -0.649 | -0.675 | 21 / 22 |
| compression_release | US500 | NEEDS_DATA | -0.186 | -0.106 | -0.164 | -0.186 | 46 / 25 |
| shock_fade | US500 | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | US500 | UNSUPPORTED | — | — | — | — | — |
| drift48 | GER40 | NEEDS_DATA | +0.067 | -0.170 | +0.664 | +0.661 | 3 / 19 |
| robust_revert | GER40 | NEEDS_DATA | -0.740 | -0.730 | -0.681 | -0.707 | 21 / 25 |
| compression_release | GER40 | NEEDS_DATA | -0.645 | -1.005 | -0.003 | -0.008 | 6 / 3 |
| shock_fade | GER40 | NEEDS_DATA | — | — | — | — | 0 / 0 |
| relative_lag | GER40 | UNSUPPORTED | — | — | — | — | — |

## Evidence map

- `research_autonomous/hypotheses.py`, both saved runs, original reports, family_aggregates.json, results.json and trades.jsonl. The latest run is the correctness rerun, not independent replication.
- `quant_labs/state/labs/codex/strategies/`, registry.jsonl, experiments.jsonl, performance.jsonl; read-only shared control.sqlite3 queries.
- `quant_labs/next_phase/{evaluations,retry_evaluations,summary,candidates}.json`; actual frozen outputs and supplemental failures/recoveries.
- `quant_labs/state/labs/claude/research/results/compression_escape_0.1.0_full.json` (externally conducted evaluation only).
- `quant_labs/CODEX_AUDIT_LIVE_EVIDENCE_2026-10-23.json`; current loopback API and read-only live SQLite records.
- All eight current executable sources match registered source text. Six Trend Reclaim working files have CRLF whereas registered source uses LF; normalized text hashes match exactly, so raw-byte mismatch alone is not a changed strategy.
- Git history includes these contributions in local commit 4be2010. Audit performed no new backtests, no new strategies, model edits, registrations, activation, execution, sends, restart, commit, push or deployment. Only this report and its filtered audit evidence were added.
