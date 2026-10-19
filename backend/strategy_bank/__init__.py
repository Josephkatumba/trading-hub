"""TRADEden Strategy Bank: independent, rule-based signal strategies (no fixed number).

MT5 bars -> N independent strategy scanners -> confirmation gates -> opportunity dedupe ->
signal store -> (optional) Telegram -> authoritative outcomes -> per-strategy statistics.

Inert by default: nothing runs unless TRADEDEN_STRATEGY_BANK_ENABLED=1, and nothing is sent to
Telegram unless TRADEDEN_STRATEGY_BANK_TELEGRAM_ENABLED=1 as well. Strategies #1-3 are LINKED to the
existing production strategies (trendline_v5 BREAK / REVERSAL, support_resistance): the bank does not
re-implement or re-send them, it attributes and measures them.

  indicators.py   causal indicator arrays (value at bar i uses bars <= i only)
  rules.py        strategy specifications, decide() functions, register() (dynamic, unlimited)
  expansion.py    researched expansion strategies (registered as RESEARCH only when admitted)
  qualification.py  lifecycle registry: timestamped status transitions, evidence-gated promotion
  engine.py       confirmation gates, duplicate control, opportunity merging, signal store, statistics
  telegram.py     bank alert format and delivery (separate dedupe store; reuses the live client)
  worker.py       the live loop (MT5 fetch on bar closes, outcome resolution)
"""
