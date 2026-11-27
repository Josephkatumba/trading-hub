# Live laboratory provider handoff

The CEO narrowed the current implementation to the shared pipeline and an actual Codex model. Claude and Kimi remain `PENDING_ACTUAL_AI_MODEL`. Their directories and historical evaluator are not substitutes for independently authored executable models.

Each actual AI session can register its own source and manifest using the local owner CLI in `backend/quant_live/__main__.py`. Registration requires its actual session reference. This is recorded provenance, not cryptographic proof of which AI wrote a file. Do not invent another provider's provenance.

## Executable contract

Implement `detect(snapshot)` returning a list of zero to four dictionaries, each with exactly:

```python
{'direction': 'LONG', 'stop_loss': 1.05, 'take_profit': 1.12,
 'horizon_seconds': 43200, 'atr': 0.01, 'rationale': 'Describe the detected conditions.'}
```

The current economic identity allows one signal per model/version/instrument/closed primary bar. The initial execution protocol supports market paper quotes, fixed SL/TP and a time limit. New order or exit types require a versioned protocol extension; do not silently reinterpret this schema.

Input contains `symbol`, `broker_symbol`, `source`, `source_basis`, `asof` UTC epoch, `time_verified`, `input_sha256`, `quote` (`bid`, `ask`, `tick_at`), `metadata`, `data_quality` and `frames`. Candle rows contain `utc` **opening** UTC epoch, OHLC, historical spread in **price units**, and broker tick volume when supplied. Only closed, valid candles are supplied. A candle's close time is its opening time plus the timeframe duration. Missing rows remain missing. There is no synthetic filling of live history.

Data is recursively immutable. Pure numerical functions, loops, comprehensions, container operations, `math` and `statistics` are supported. File/network/process imports, reflection, I/O builtins, arbitrary attributes and broker access are rejected. The model receives no MT5 module, terminal handle, account credential, Telegram client or trading function.

All registered models run in a fresh restricted worker with Windows Job Object limits: 192 MiB committed memory, 15% machine CPU, 4 seconds CPU time, one process and below-normal priority; the parent enforces a 5-second elapsed timeout. An infinite-loop test verifies termination. These are application and worker boundaries, not an adversarial sandbox for unrestricted shells running under the same Windows account.

## Manifest

Required fields: `lab` (`codex`, `claude`, `kimi`), a stable `key`, semantic `version`, human `name`, primary `timeframe`, `instruments`, and `requirements` mapping timeframes to requested bar counts. Supported fixed timeframes are M1/M5/M15/H1/H4/D1, with a 12,000-bar per-frame safety limit. Instrument names must match the engine's product symbols. The collector scans the existing configured watchlist; adding an instrument to a manifest does not silently add it to that watchlist.

Declare known limitations, risk methodology and entry type. A manifest example is the actual Codex Compression Escape manifest beside its source. Model versions are immutable. Increment the version when source or manifest changes. Multiple models and versions may be registered; there is no strategy-count limit. A worker cycle rotates at most eight models within ten seconds; this is a laptop scheduling limit, not a research limit.

From the backend directory, use:

```powershell
python -m quant_live --store <explicit-local-registry-directory> register --manifest <own-manifest.json> --source <own-model.py> --session-reference <actual-authoring-session-reference>
python -m quant_live --store <explicit-local-registry-directory> report
python -m quant_live --store <explicit-local-registry-directory> status --lab claude --key <own-key> --version <own-version> --set ARCHIVED
```

The live registry is `<TRADING_HUB_DATA_DIR>/quant_live` (default `backend/data/quant_live`). The old `quant_labs` frozen research registry is a separate system. Never point these commands at that old evaluator or change its frozen files.

Registration always creates an EXPERIMENTAL model with scanning allowed and experimental alert permission disabled. The CLI cannot self-assign VERIFIED or activate Telegram. Disabling, archiving or rejecting a model revokes scanning and suppresses queued previews. Changes made during a worker run are checked again before signal creation.

## Local integration

The code integrates into the existing scanner and MT5 session. `TRADEDEN_QUANT_LIVE_ENABLED=1` enables the consumer on a controlled **local** engine start. It defaults off. The MT5 source timezone must already be explicitly verified in the existing engine configuration. Missing tradability metadata, stale quotes, invalid inputs, excessive spread or insufficient net planned RR fail closed. Broker fee estimates are disclosed research assumptions, not verified account fees.

The owner view is `GET /api/quant-labs/live`, restricted to loopback clients in private mode. The dashboard adds Quant Labs only when served on loopback. It shows separate laboratory identities, source/version evidence, latest signals, lifecycle/outcomes, paper performance, unavailable actual executed R and unsent previews. Hosted OIDC routes remain blocked by the existing commercial allowlist as well as the new route guard.

No experimental outbound activation mechanism is wired in this release. Review the successful synthetic dry-run proof and message first. Actual live-collector observation, broker cost review and explicit CEO approval must precede any later outbound implementation. Never replay old previews on activation.

## Next-phase lab-scoped bridge

The current Codex consumer is now observing genuine MT5 data. Claude and Kimi still require their actual sessions to author their models. The bridge below was tested with isolated, explicitly non-strategy contract fixtures for all three identities and with the actual Codex source on genuine cached MT5 data. This does **not** claim that Claude or Kimi has authored or run a model.

Use only your own `.lab-token` through `TRADEDEN_LAB_TOKEN`; never use another laboratory's token or an owner/reviewer capability. From the repository root, the actual Claude session can run:

```powershell
$env:TRADEDEN_LAB_TOKEN = [System.IO.File]::ReadAllText('quant_labs/state/labs/claude/.lab-token').Trim()
python -m quant_labs.provider_bridge register --lab claude --manifest <own-manifest.json> --source <own-model.py>
python -m quant_labs.provider_bridge probe --lab claude --manifest <own-manifest.json> --symbol BTCUSD
python -m quant_labs.cli submit claude <own-key> <own-version> <causally-generated-intents.json>
```

Kimi substitutes `kimi` in both its own credential path and command lab argument. Register requires own-lab manifest and actual authoring-session provenance; token/manifest/source/version bindings are checked. Registration into the shared research ledger does not activate live scanning or alerting. It stores source for review. The frozen evaluator consumes the causal intents, never the laboratory's executable. Only the owner-side operator runs its bounded worker; the lab credential cannot self-run the common worker or self-certify a result. Its reviewed source can later be admitted to the existing experimental paper provider using the live registry interface above, without any new broker connection.

The read-only probe consumes the existing collector's genuine quote/metadata and completed OHLC/spread cache. It uses a bounded pure-model worker, validates freshness and completed context, and writes no live signal, outbox, order or approval record. The cache does not retain optional tick-volume features: volume-dependent models must validate those through the full live provider interface; this probe is not a substitute for that check. Stale input is rejected, not refreshed by changing its timestamp.

Each model's own causal replay must expose only completed feature bars. A historical entry-bar open and recorded spread can be an explicitly disclosed quote proxy; never expose that bar's future high/low/close. The chronological historical partitions already seen in prior research are not an untouched holdout. Register all variants and failed trials, disclose missing histories, and retain all frozen evaluator output. The seven new Codex executables are offline candidates, not references for another lab to copy.

Tests of capability boundaries are application-level controls. They do not turn an unrestricted shell under the same Windows identity into an adversarial sandbox, nor does a supplied session reference cryptographically verify an AI's authorship. Actual Claude/Kimi session provenance remains a required outstanding integration step.
