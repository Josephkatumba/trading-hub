"""TRADEden Strategy Bank: 20 independent, rule-based signal strategies (EXPERIMENTAL).

MT5 bars -> 20 independent strategy scanners -> confirmation gates -> opportunity dedupe ->
signal store -> (optional) Telegram -> authoritative outcomes -> per-strategy statistics.

Inert by default: nothing runs unless TRADEDEN_STRATEGY_BANK_ENABLED=1, and nothing is sent to
Telegram unless TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED=1 as well. Strategies #1-3 are LINKED to the
existing production strategies (trendline_v5 BREAK / REVERSAL, support_resistance): the bank does not
re-implement or re-send them, it attributes and measures them.

  indicators.py   causal indicator arrays (value at bar i uses bars <= i only)
  rules.py        the 20 strategy specifications and their decide() functions
  engine.py       confirmation gates, duplicate control, opportunity merging, signal store, statistics
  telegram.py     bank alert format and delivery (separate dedupe store; reuses the live client)
  worker.py       the live loop (MT5 fetch on bar closes, outcome resolution)
"""
