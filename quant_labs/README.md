# TradeDen independent laboratories

Start with [CEO_IMPLEMENTATION_REPORT.md](CEO_IMPLEMENTATION_REPORT.md), the local
[dashboard snapshot](dashboard.html), and [integration instructions](docs/INTEGRATION.md).

The isolated prototype provides Codex, Claude and Kimi workspaces, immutable version
registries, append-only evidence, a frozen common evaluator, validated shared data,
bounded sequential workers, pause/resume checkpoints and read-only local research UI.

It does not change the operational TradeDen app, engine, alerts or trading permissions.
No external Claude/Kimi model has been invoked and no strategy is certified profitable.

```text
python -m quant_labs.bootstrap
python -m quant_labs.validate
python -m quant_labs.preview --export
python -m quant_labs.preview --port 8766
```

The optional preview is a foreground local process; stop it with Ctrl+C. Worker runs
require the separately provisioned operator capability and explicit `run-one` command.
No scheduler is installed. Do not commit capability files or alter frozen contracts.

The isolation is application-level, not a security sandbox around unrestricted
same-account shells. See the report and integration guide before connecting agents.
