# Frozen evidence: TradeDen Scalper tds-1.0 (2026-11-23)

Archived before Edge Discovery V2 began. Do not edit these files. `MANIFEST.sha256`
holds their checksums (`sha256sum -c MANIFEST.sha256`).

- `walkforward_*.json`, `oos_trades_*.csv`: walk-forward output of `ctrader_scalper/engine`
  (288 configs, train 6 weeks / test 2 weeks, IC Markets M1 data from Aug 13 to Nov 23, 2026).
- `TradeDenScalper-tds-1.0.cs.txt`: the exact cBot source that was evaluated.

Verdict: **NO_EDGE** on XAUUSD, BTCUSD, EURUSD and GBPUSD. Portfolio out-of-sample:
227 trades, PF 0.54, -0.30R per trade, t = -4.2. The signals score about 0R before costs.
See `ctrader_scalper/README.md#results`.
