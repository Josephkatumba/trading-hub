"""Phase 10 mutation tests: break one Trend / Momentum rule or one isolation
safeguard at a time and prove the real tests (test_trend_momentum) catch it.

Each mutation runs the named tests with the mutation patched in and requires at
least one failure; the same tests must pass unmutated (so a failure is caused by
the mutation, not by the test itself).
"""
from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support  # noqa: E402,F401  (puts backend/ on sys.path)

import observations  # noqa: E402
from strategies import LIVE  # noqa: E402
from strategies import trend_momentum as tm  # noqa: E402

TESTS = "test_trend_momentum."


def wrap(target, attribute, change):
    """Patch `target.attribute` with a wrapper that post-processes its result."""
    original = getattr(target, attribute)

    def mutated(*args, **kwargs):
        return change(original(*args, **kwargs))
    return mock.patch.object(target, attribute, mutated)


def _without(key):
    def change(snapshot):
        snapshot.pop(key, None)
        return snapshot
    return change


def _identity_without_strategy(snapshot):
    snapshot["episode_identity"] = {k: v for k, v in snapshot["episode_identity"].items() if k != "strategy_id"}
    return snapshot


MUTATIONS = {
    # Strategy rules
    "impulse gate removed": ([mock.patch.object(tm, "MIN_IMPULSE_ATR", 0.0)],
                             ["RejectionTests.test_insufficient_impulse_is_not_a_setup_candidate"]),
    "persistence gate removed": ([mock.patch.object(tm, "MIN_EFFICIENCY", 0.0)],
                                 ["RejectionTests.test_choppy_impulse_lacks_persistence"]),
    "pullback depth unbounded": ([mock.patch.object(tm, "MAX_RETRACEMENT", 1.0)],
                                 ["RejectionTests.test_failed_pullback_is_no_setup"]),
    "continuation trigger not required": ([wrap(tm, "m15_trigger", lambda t: {**t, "resumption": True})],
                                          ["ContinuationTests.test_controlled_pullback_without_a_trigger_is_developing"]),
    "D1 veto removed": ([wrap(tm, "d1_context", lambda d: {**d, "opposes": False})],
                        ["RejectionTests.test_higher_timeframe_disagreement"]),
    "H1 alignment ignored": ([wrap(tm, "h1_setup", lambda h: {**h, "aligned": True})],
                             ["RejectionTests.test_higher_timeframe_disagreement"]),
    "shorts never qualify (mirror broken)": ([wrap(tm, "h4_trend", lambda h: {**h, "direction": h["direction"] if h["direction"] == "LONG" else None})],
                                             ["ContinuationTests.test_bearish_continuation_is_the_exact_mirror"]),
    "stop placed at the pullback extreme": ([mock.patch.object(tm, "STOP_BUFFER_ATR", 0.0)],
                                            ["PlanTests.test_entry_stop_target_and_rr_long", "PlanTests.test_entry_stop_target_and_rr_short"]),
    "minimum R:R removed": ([mock.patch.object(tm, "MIN_RR", 0.0)],
                            ["PlanTests.test_insufficient_reward_blocks_confirmation"]),
    "risk bounds removed": ([mock.patch.object(tm, "MAX_RISK_ATR", 0.1)],
                            ["ContinuationTests.test_bullish_continuation_after_controlled_pullback_confirms"]),
    # Persistence identity and isolation
    "strategy_id removed from persistence": ([wrap(observations, "_snapshot", _without("strategy_id"))],
                                             ["PersistenceLifecycleTests.test_snapshots_carry_their_own_identity_and_research_flag"]),
    "strategy_id removed from episode identity": ([wrap(observations, "_snapshot", _identity_without_strategy)],
                                                  ["PersistenceLifecycleTests.test_snapshots_carry_their_own_identity_and_research_flag"]),
    "episodes/suppression not scoped by strategy": ([mock.patch.object(observations, "record_strategy_id", lambda record: "trendline")],
                                                    ["IsolationTests.test_simultaneous_trendline_and_trend_momentum_same_symbol",
                                                     "IsolationTests.test_a_trendline_direction_change_never_touches_trend_momentum",
                                                     "IsolationTests.test_a_closed_trend_momentum_episode_never_suppresses_trendline"]),
    "research confirmation treated as live": ([mock.patch.object(observations, "_strategy_mode", lambda *args: LIVE)],
                                              ["ResearchModeTests.test_research_confirmations_are_never_live"]),
}


def run(names, patches=()):
    suite = unittest.defaultTestLoader.loadTestsFromNames([TESTS + name for name in names])
    result = unittest.TestResult()
    with ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        suite.run(result)
    return result


class MutationTests(unittest.TestCase):
    def test_every_mutation_is_caught(self):
        for label, (patches, names) in MUTATIONS.items():
            with self.subTest(mutation=label):
                self.assertTrue(run(names).wasSuccessful(), "the targeted tests pass unmutated")
                result = run(names, patches)
                self.assertGreater(len(result.failures) + len(result.errors), 0, f"mutation not caught: {label}")

    def test_each_isolation_mutation_breaks_every_isolation_test(self):
        # Scoping by strategy is what keeps simultaneous setups apart: all three scenarios must notice.
        patches, names = MUTATIONS["episodes/suppression not scoped by strategy"]
        for name in names:
            with self.subTest(test=name):
                result = run([name], patches)
                self.assertGreater(len(result.failures) + len(result.errors), 0)


if __name__ == "__main__":
    unittest.main()
