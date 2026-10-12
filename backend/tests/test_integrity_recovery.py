import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from outcome_identity import unique_outcomes
from recover_store import backup_store, recovery_projection, recover_objects
from jsonl_index import JsonlIndex
from strategy_lab import classify_outcome
from ml_dataset import _outcome_quarantine_reasons
from store_audit import audit_store
from performance import _classify
import outcomes


def outcome(**changes):
    return {"record_type": "market_outcome", "setup_id": "s", "observation_id": "o", "horizon": "1h",
            "label_definition": "target-invalidation-first-v1", "outcome_id": "first", "label": "WIN",
            "future_price": 104, "data_quality": {"observed_at": "first", "source_age_seconds": 1}, **changes}


class IntegrityRecoveryTests(unittest.TestCase):
    def test_metadata_copies_collapse_but_price_changes_are_preserved_and_quarantined(self):
        first = outcome()
        copy = outcome(outcome_id="second", resolved_at="later", data_quality={"observed_at": "later", "source_age_seconds": 2})
        # Both original dictionaries contain the generation field (its value is immaterial).
        first["resolved_at"] = "earlier"
        self.assertEqual(len(unique_outcomes([first, copy])), 1)
        conflict = outcome(future_price=103)
        rows = unique_outcomes([first, copy, conflict])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["outcome_status"] == "DUPLICATE_OUTCOME_CONFLICT" for r in rows))
        self.assertIn("DUPLICATE_OUTCOME_CONFLICT", _outcome_quarantine_reasons(rows[0]))
        self.assertNotIn("outcome_status", first)
        self.assertEqual(unique_outcomes(rows), rows)
        self.assertEqual(classify_outcome({"observation_id": "o"}, rows, None)[0], "unverified")
        self.assertEqual(_classify(rows[0]), "PENDING")

    def test_distinct_horizons_and_label_definitions_remain_distinct(self):
        rows = [outcome(), outcome(horizon="4h"), outcome(label_definition="other")]
        self.assertEqual(unique_outcomes(rows), rows)
        incomplete = outcome(observation_id="")
        self.assertEqual(unique_outcomes([incomplete, incomplete]), [incomplete, incomplete])

    def test_audit_distinguishes_repeat_copies_from_evidence_conflicts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [outcome(), outcome(outcome_id="retry"), outcome(future_price=103)]
            (root / "market_outcomes.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            counts = audit_store(root)["market_outcomes.jsonl"]
            self.assertEqual(counts["duplicate_outcome_keys"], 2)
            self.assertEqual(counts["duplicate_exact_copies"], 1)
            self.assertEqual(counts["conflicting_extra_variants"], 1)
            self.assertEqual(counts["conflicting_groups"], 1)

    def test_quarantine_and_backup_preserve_original_bytes_and_recover_complete_embedded_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            first = outcome(resolved_at="earlier")
            copy = outcome(outcome_id="second", resolved_at="later")
            valid = json.dumps(first).encode() + b"\n"
            raw = valid + json.dumps(copy).encode() + b"\n" + b"\xff\x00unknown\n"
            (source / "market_outcomes.jsonl").write_bytes(raw)
            backup_store(source, root / "original")
            report = recovery_projection(root / "original", root / "clean")
            self.assertEqual((source / "market_outcomes.jsonl").read_bytes(), raw)
            self.assertEqual((root / "original/market_outcomes.jsonl").read_bytes(), raw)
            self.assertEqual(report["files"]["market_outcomes.jsonl"]["duplicate_copies_omitted"], 1)
            self.assertEqual(report["files"]["market_outcomes.jsonl"]["unrecoverable_lines"], 1)
            self.assertEqual((root / "clean/quarantine/market_outcomes.jsonl.3.bin").read_bytes(), b"\xff\x00unknown\n")
            recovered = recover_objects(b"\x00junk" + valid + b"\xff", "market_outcome")
            self.assertEqual(recovered[0][0], first)
            reordered = {"setup_id": "s", **first}
            self.assertEqual(recover_objects(b"junk" + json.dumps(reordered).encode(), "market_outcome")[0][0], first)
            (root / "original/market_outcomes.jsonl").write_bytes(b"changed")
            with self.assertRaises(RuntimeError):
                recovery_projection(root / "original", root / "refuse-modified-backup")

    def test_append_retry_is_idempotent_but_changed_evidence_remains(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(outcomes, "DATA_DIR", root), patch.object(outcomes, "MARKET_OUTCOMES_FILE", root / "market_outcomes.jsonl"):
                outcomes.append_market_outcome(outcome())
                outcomes.append_market_outcome(outcome(outcome_id="retry"))
                outcomes.append_market_outcome(outcome(future_price=102))
                self.assertEqual(len(outcomes.list_records(root / "market_outcomes.jsonl")), 2)
                outcomes.append_market_outcome(outcome(observation_id=""))
                outcomes.append_market_outcome(outcome(observation_id=""))
                self.assertEqual(len(outcomes.list_records(root / "market_outcomes.jsonl")), 4)

    def test_cold_index_obeys_a_bounded_read_budget_and_keeps_partial_tail(self):
        class BudgetedReader(io.BytesIO):
            def read(self, size=-1):
                if size < 0 or size > 65536:
                    raise AssertionError("unbounded historical allocation")
                return super().read(size)
        line = json.dumps({"sid": "s", "padding": "x" * 256}).encode() + b"\n"
        data = line * 5000 + b'{"sid":'
        index = JsonlIndex(Path("unused"), lambda r: {"sid": r["sid"]}, ("sid",), "test", persist=False)
        index._consume(BudgetedReader(data), len(data))
        self.assertEqual(len(index.rows), 5000)
        self.assertEqual(index.offset, len(line) * 5000)
