"""Separately versioned M5 research extension (tradeden-m5-extension-1.0.0).

Adds M5 registration, submission and evaluation alongside the frozen v1 evaluator
without modifying it or its trusted interfaces. M5 candles are derived only from
complete, contiguous validated shared M1 candles; accepted intents are then scored by
the unchanged frozen v1 evaluator using its M1 confirming frame.
"""
