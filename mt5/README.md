# Trading Hub MT5 Bridge

The EA in `mt5/TradingHub_Bridge.mq5` is a **read-only heartbeat bridge**.

It does not place, modify, or close trades.

## Install

1. Open MetaTrader 5.
2. Open **File → Open Data Folder**.
3. Open `MQL5/Experts`.
4. Copy `TradingHub_Bridge.mq5` into that folder.
5. Open MetaEditor and compile it.
6. Attach **TradingHub_Bridge** to a chart.
7. Leave the EA running while the Python engine is running.

The EA writes `trading_hub_heartbeat.json` into MT5's common files directory. Trading Hub Python reads that heartbeat automatically on Windows.

## What it reports

- MT5 account login
- broker/server
- terminal build
- selected symbol
- bid/ask
- balance/equity
- bridge timestamp
- execution_enabled=false

The bridge is deliberately read-only while the scanner is being validated.
