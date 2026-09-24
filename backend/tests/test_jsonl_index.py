"""Recovery behaviour of the derived JSONL index: it must always agree with the JSONL file."""
from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import jsonl_index  # noqa: E402
from jsonl_index import JsonlIndex, ensure_trailing_newline, indexed_jsonl_records  # noqa: E402


def summarize(row):
    return {"sid": str(row["sid"])} if "sid" in row else {}


def full_scan(path: Path, sid: str) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "sid" in row and str(row["sid"]) == sid:
            out.append(row)
    return out


def append(path: Path, *rows) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class JsonlIndexRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "obs.jsonl"
        append(self.path, *({"sid": f"s{i % 5}", "n": i} for i in range(50)))

    def tearDown(self):
        self.tmp.cleanup()

    def new_index(self):
        return JsonlIndex(self.path, summarize, ("sid",), schema="test-v1")

    def rows(self, index, sid):
        return index.load(index.lookup("sid", sid))

    def assert_matches_file(self, index):
        for sid in ("s0", "s1", "s4", "nope"):
            self.assertEqual(self.rows(index, sid), full_scan(self.path, sid))

    def force_persist(self, index):
        index.refresh()
        index._maybe_persist(force=True)
        self.assertTrue(index.sidecar_path.exists())

    def test_records_written_before_any_index_are_indexed(self):
        index = self.new_index()
        self.assert_matches_file(index)
        self.assertEqual(index.stats()["rows"], 50)

    def test_missing_sidecar_is_built_and_persisted(self):
        index = self.new_index()
        self.assert_matches_file(index)
        self.force_persist(index)
        reloaded = self.new_index()
        self.assert_matches_file(reloaded)
        self.assertEqual(reloaded.rebuilds, 0)

    def test_stale_sidecar_catches_up_incrementally(self):
        index = self.new_index()
        self.force_persist(index)
        append(self.path, {"sid": "s1", "n": 1000}, {"sid": "new", "n": 1001})
        reloaded = self.new_index()
        self.assert_matches_file(reloaded)
        self.assertEqual(self.rows(reloaded, "new"), [{"sid": "new", "n": 1001}])
        self.assertEqual(reloaded.rebuilds, 0, "stale-but-valid sidecar should not force a rebuild")

    def test_live_appends_are_visible_on_the_next_query(self):
        index = self.new_index()
        self.assertEqual(len(self.rows(index, "s2")), 10)
        append(self.path, {"sid": "s2", "n": 999})
        self.assertEqual(len(self.rows(index, "s2")), 11)

    def test_corrupted_sidecar_is_ignored_and_rebuilt(self):
        index = self.new_index()
        self.force_persist(index)
        for damage in ("{garbage", json.dumps({"checksum": "0" * 64, "body": "{}"}), ""):
            index.sidecar_path.write_text(damage, encoding="utf-8")
            reloaded = self.new_index()
            self.assert_matches_file(reloaded)
            self.assertEqual(reloaded.stats()["rows"], 50)

    def test_tampered_sidecar_body_fails_checksum(self):
        index = self.new_index()
        self.force_persist(index)
        document = json.loads(index.sidecar_path.read_text(encoding="utf-8"))
        body = json.loads(document["body"])
        body["rows"][0] = {"sid": "s4"}           # silently wrong mapping
        document["body"] = json.dumps(body)
        index.sidecar_path.write_text(json.dumps(document), encoding="utf-8")
        self.assert_matches_file(self.new_index())

    def test_schema_change_forces_rebuild(self):
        index = self.new_index()
        self.force_persist(index)
        other = JsonlIndex(self.path, summarize, ("sid",), schema="test-v2")
        self.assertEqual(other.stats()["rows"], 50)
        self.assert_matches_file(other)

    def test_replaced_or_truncated_source_forces_rebuild(self):
        index = self.new_index()
        self.force_persist(index)
        # Same-length rewrite with different content before the indexed offset.
        text = self.path.read_text(encoding="utf-8").replace('"s0"', '"s9"')
        self.path.write_text(text, encoding="utf-8")
        reloaded = self.new_index()
        self.assert_matches_file(reloaded)
        self.assertEqual(self.rows(reloaded, "s0"), [])
        self.assertGreaterEqual(reloaded.rebuilds, 1)
        # Truncation below the indexed offset, on a live index.
        self.path.write_text(json.dumps({"sid": "s0", "n": -1}) + "\n", encoding="utf-8")
        self.assertEqual(self.rows(reloaded, "s0"), [{"sid": "s0", "n": -1}])

    def test_interrupted_write_is_not_indexed_until_complete(self):
        index = self.new_index()
        index.refresh()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"sid": "s3", "n": 5')                  # writer mid-line
        self.assertEqual(len(self.rows(index, "s3")), 10)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('00}\n')                                   # writer finishes
        self.assertEqual(self.rows(index, "s3")[-1], {"sid": "s3", "n": 500})

    def test_crashed_half_line_cannot_swallow_the_next_record(self):
        index = self.new_index()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"sid": "s3", "n": 7')                  # writer crashed here
        self.assertTrue(ensure_trailing_newline(self.path))
        append(self.path, {"sid": "s3", "n": 8})
        rows = self.rows(index, "s3")
        self.assertEqual(rows[-1], {"sid": "s3", "n": 8}, "record after a crash must not be lost")
        self.assertEqual(index.stats()["unparseable_lines"], 1, "damage is counted, not silent")
        self.assertFalse(ensure_trailing_newline(self.path))

    def test_bad_lines_are_skipped_and_counted_like_the_full_scan(self):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n{nope\n[1,2]\n\"str\"\n")
        append(self.path, {"sid": "s0", "n": 77})
        index = self.new_index()
        self.assert_matches_file(index)
        self.assertEqual(index.stats()["unparseable_lines"], 3)

    def test_missing_file_is_empty_then_indexed_when_created(self):
        missing = Path(self.tmp.name) / "later.jsonl"
        index = JsonlIndex(missing, summarize, ("sid",), schema="test-v1")
        self.assertEqual(index.lookup("sid", "s0"), [])
        append(missing, {"sid": "s0", "n": 1})
        self.assertEqual(index.load(index.lookup("sid", "s0")), [{"sid": "s0", "n": 1}])


class GenericLookupTests(unittest.TestCase):
    def test_indexed_jsonl_records_equals_linear_scan(self):
        rng = random.Random(7)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "life.jsonl"
            rows = []
            for i in range(400):
                row = {"n": i}
                if rng.random() > 0.1:
                    row["setup_id"] = rng.choice(["a", "b", "c", 1, None, "1"])
                rows.append(row)
            append(path, *rows)
            for value in ("a", "b", 1, "1", "None", None, "zzz"):
                expected = [] if value is None else [r for r in rows if "setup_id" in r and str(r["setup_id"]) == str(value)]
                self.assertEqual(indexed_jsonl_records(path, "setup_id", value), expected, value)
            append(path, {"setup_id": "a", "n": "late"})
            self.assertEqual(indexed_jsonl_records(path, "setup_id", "a")[-1], {"setup_id": "a", "n": "late"})
        jsonl_index._REGISTRY.clear()


if __name__ == "__main__":
    unittest.main()
