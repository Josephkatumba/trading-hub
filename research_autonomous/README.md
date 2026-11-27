# Independent offline research

Read [CEO_RESEARCH_REPORT.md](CEO_RESEARCH_REPORT.md) for findings and limits.

This package reads the existing `backend/data/research/bars` cache. It never initializes MT5, changes production settings, sends Telegram messages or executes orders. Run commands from the repository root. Python and NumPy are the only competition dependencies; no installation is needed in the current environment.

```text
python -m research_autonomous.validate
python -m research_autonomous.experiment --max-seconds 240
python -m research_autonomous.verify_run
python -m research_autonomous.replay_corrections
python -m research_autonomous.report
```

Each competition run has a unique directory under `runs/`. Preserve all previous directories, configurations, failed experiment events and source/data hashes. The correction ledger lives exclusively in `corrections/revisions.jsonl`; repeated identical corrections are deduplicated. Never substitute this ledger for production outcomes without an approved migration.

The default batch declares five fixed hypotheses across 16 instruments and three selection policies. Its multiple-testing family size is explicitly frozen at 83 registrations. Adding hypotheses, variants, instruments or policies requires a new batch configuration, revised trial inventory and denominator, and a future untouched validation interval. It does not require a profitable outcome. Do not tune rules against the current final-test results.

The file-driven `forward` module accepts a prospectively captured snapshot and metadata:

```text
python -m research_autonomous.forward snapshot.json metadata.json
```

Snapshot fields: `symbol`, epoch-UTC `asof`, `quote` with `bid`, `ask`, `tick_at`, and `frames.H1` containing completed bid OHLC bars with explicit price-unit `spread` and epoch-UTC `utc`. Optional `benchmark_H1` supports BTC/ETH residual signals. Metadata needs `tick_size`. This collector records **shadow observations only**; no actual prospective performance has been measured. It requires a current snapshot and rejects historical files relabelled as forward evidence. It has no recurring worker or network feed.

The alert/lifecycle functions are isolated replacement contracts. They have not been wired into the running platform. Production compatibility, regression tests, historical migration and deployment remain subject to CEO approval.
