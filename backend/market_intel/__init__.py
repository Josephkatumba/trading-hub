"""Explainable XAUUSD / BTCUSD market intelligence (analysis only, never trade signals).

Every conclusion is produced by an explicit, numbered rule over CLOSED candles available at the
evaluation time, and carries its observations, rules, data timestamp and missing or conflicting
evidence. Unavailable data (yields, economic calendar, funding, open interest, liquidations) is
reported as unavailable, never estimated. No entry, stop or target levels are produced here.
"""
