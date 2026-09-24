"""Derived, recoverable indexes over append-only JSONL stores.

The JSONL files stay the only source of truth. An index here records, for each
complete line, its byte span plus a small caller-defined summary, and builds
key -> row maps from those summaries. Full rows are always re-read from the
JSONL file by byte offset, so an index can never return data the file does not
contain.

Freshness: every query stats the file and indexes only bytes appended since the
last query. There is no time-based cache, so readers see each append as soon as
its trailing newline is written.

Recovery (all paths fall back to a rebuild from the JSONL source):
- missing sidecar          -> full build, then persisted
- stale sidecar            -> incremental catch-up from its recorded offset
- corrupted sidecar        -> checksum/schema/shape mismatch -> full rebuild
- replaced/truncated file  -> head/tail fingerprint or size mismatch -> rebuild
- interrupted write        -> a trailing line without "\\n" is not indexed
                              until it is completed
- pre-index records        -> indexed by the first build like any other line
Lines that are not valid JSON objects are counted in `stats()` (never silently
dropped from accounting); readers skip them exactly as the old full scans did.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

LOGGER = logging.getLogger("trading_hub.jsonl_index")

SIDECAR_VERSION = 1
_HEAD_BYTES = 65536
_TAIL_BYTES = 4096
_PERSIST_EVERY_LINES = 2000
_PERSIST_EVERY_SECONDS = 300.0

Summarize = Callable[[dict[str, Any]], dict[str, Any]]


def ensure_trailing_newline(path: Path) -> bool:
    """Terminate an interrupted final line before appending.

    Without this, the next record would be glued onto a half-written line and
    both would become unparseable. Returns True if a newline was added.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size == 0:
        return False
    with path.open("rb+") as handle:
        handle.seek(size - 1)
        if handle.read(1) == b"\n":
            return False
        handle.seek(size)
        handle.write(b"\n")
    LOGGER.warning("Terminated an incomplete trailing line in %s before appending", path)
    return True


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class JsonlIndex:
    """Byte-offset index + per-row summaries for one append-only JSONL file."""

    def __init__(self, path: Path, summarize: Summarize, keys: Iterable[str],
                 schema: str, persist: bool = True) -> None:
        self.path = Path(path)
        self.summarize = summarize
        self.keys = tuple(keys)
        self.schema = schema
        self.persist = persist
        self._lock = threading.RLock()
        self.rebuilds = 0
        self.generation = 0                  # bumped whenever positions may no longer line up
        self._reset()
        self._loaded_sidecar = False

    # ----- state -----------------------------------------------------------
    def _reset(self) -> None:
        self.generation = getattr(self, "generation", 0) + 1
        self.offset = 0                      # bytes covered by complete, indexed lines
        self.spans: list[tuple[int, int]] = []
        self.rows: list[dict[str, Any]] = []  # summary per valid JSON-object line
        self.bad_lines: list[int] = []        # start offsets of unparseable/non-object lines
        self.maps: dict[str, dict[Any, list[int]]] = {key: {} for key in self.keys}
        self._head_hash = ""
        self._tail_hash = ""
        self._verified_stat: tuple[int, int] | None = None
        self._unpersisted = 0
        self._last_persist = 0.0

    def _add(self, start: int, raw: bytes) -> None:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            value = None
        if not isinstance(value, dict):
            if raw.strip():
                self.bad_lines.append(start)
            return
        position = len(self.rows)
        summary = self.summarize(value)
        self.spans.append((start, len(raw)))
        self.rows.append(summary)
        self._map_row(position, summary)

    def _map_row(self, position: int, summary: dict[str, Any]) -> None:
        for key in self.keys:
            if key in summary:
                value = summary[key]
                try:
                    hash(value)
                except TypeError:
                    value = json.dumps(value, sort_keys=True, default=str)
                self.maps[key].setdefault(value, []).append(position)

    # ----- fingerprints ----------------------------------------------------
    def _fingerprints(self, handle, end: int) -> tuple[str, str]:
        handle.seek(0)
        head = handle.read(min(_HEAD_BYTES, end))
        start = max(0, end - _TAIL_BYTES)
        handle.seek(start)
        tail = handle.read(end - start)
        return _sha(head), _sha(tail)

    # ----- refresh ---------------------------------------------------------
    def refresh(self) -> None:
        with self._lock:
            if not self._loaded_sidecar:
                self._loaded_sidecar = True
                self._load_sidecar()
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                if self.offset or self.rows:
                    self._reset()
                return
            size = stat.st_size
            if size < self.offset:
                LOGGER.warning("%s shrank below the indexed offset; rebuilding index", self.path)
                self._rebuild()
                return
            stamp = (size, stat.st_mtime_ns)
            if stamp == self._verified_stat:
                return
            with self.path.open("rb") as handle:
                if self.offset and self._fingerprints(handle, self.offset) != (self._head_hash, self._tail_hash):
                    LOGGER.warning("%s changed before the indexed offset; rebuilding index", self.path)
                    self._rebuild()
                    return
                if size > self.offset:
                    self._consume(handle, size)
            self._verified_stat = (size, stat.st_mtime_ns) if size == self.offset else None
            self._maybe_persist()

    def _consume(self, handle, size: int) -> None:
        handle.seek(self.offset)
        data = handle.read(size - self.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return  # only an incomplete (possibly in-progress) trailing line
        position = self.offset
        for raw in data[:end + 1].split(b"\n")[:-1]:
            self._add(position, raw)
            self._unpersisted += 1
            position += len(raw) + 1
        self.offset = position
        self._head_hash, self._tail_hash = self._fingerprints(handle, self.offset)

    def _rebuild(self) -> None:
        self._reset()
        self.rebuilds += 1
        with self.path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            self._consume(handle, size)
        self._maybe_persist(force=True)

    # ----- persistence -----------------------------------------------------
    @property
    def sidecar_path(self) -> Path:
        return self.path.parent / ".index" / (self.path.name + ".idx.json")

    def _payload(self) -> dict[str, Any]:
        return {"version": SIDECAR_VERSION, "schema": self.schema, "source": self.path.name,
                "offset": self.offset, "head_hash": self._head_hash, "tail_hash": self._tail_hash,
                "spans": self.spans, "rows": self.rows, "bad_lines": self.bad_lines}

    def _maybe_persist(self, force: bool = False) -> None:
        if not self.persist or not self.offset:
            return
        due = (self._unpersisted >= _PERSIST_EVERY_LINES or
               (self._unpersisted and time.monotonic() - self._last_persist >= _PERSIST_EVERY_SECONDS))
        if not (force or due):
            return
        payload = self._payload()
        body = json.dumps(payload, separators=(",", ":"), default=str)
        document = json.dumps({"checksum": _sha(body.encode("utf-8")), "body": body})
        target = self.sidecar_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
            temporary.write_text(document, encoding="utf-8")
            os.replace(temporary, target)  # atomic: readers see old or new, never half
        except OSError:
            LOGGER.exception("Could not persist index sidecar %s (index stays in memory)", target)
            return
        self._unpersisted = 0
        self._last_persist = time.monotonic()

    def _load_sidecar(self) -> None:
        if not self.persist:
            return
        target = self.sidecar_path
        try:
            document = json.loads(target.read_text(encoding="utf-8"))
            body = document["body"]
            if _sha(body.encode("utf-8")) != document["checksum"]:
                raise ValueError("checksum mismatch")
            payload = json.loads(body)
            if payload.get("version") != SIDECAR_VERSION or payload.get("schema") != self.schema:
                raise ValueError("version/schema mismatch")
            spans = [tuple(span) for span in payload["spans"]]
            rows = payload["rows"]
            if len(spans) != len(rows) or not isinstance(payload["offset"], int):
                raise ValueError("shape mismatch")
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError) as exc:
            LOGGER.warning("Ignoring unusable index sidecar %s (%s); rebuilding from JSONL", target, exc)
            return
        self.offset = payload["offset"]
        self.spans = spans
        self.rows = rows
        self.bad_lines = list(payload.get("bad_lines") or [])
        self.generation += 1
        self._head_hash = payload["head_hash"]
        self._tail_hash = payload["tail_hash"]
        self.maps = {key: {} for key in self.keys}
        for position, summary in enumerate(self.rows):
            self._map_row(position, summary)
        self._last_persist = time.monotonic()

    # ----- queries ---------------------------------------------------------
    @property
    def lock(self) -> threading.RLock:
        """Hold across lookup + load so a concurrent rebuild cannot shift positions."""
        return self._lock

    def summary(self, position: int) -> dict[str, Any]:
        return self.rows[position]

    def lookup(self, key: str, value: Any) -> list[int]:
        self.refresh()
        return list(self.maps[key].get(value, ()))

    def groups(self, key: str) -> dict[Any, list[int]]:
        """key value -> row positions (file order); dict order is first appearance."""
        self.refresh()
        return {value: list(positions) for value, positions in self.maps[key].items()}

    def summaries(self) -> list[dict[str, Any]]:
        self.refresh()
        return list(self.rows)

    def delta(self, cursor: tuple[int, int] | None) -> tuple[tuple[int, int], bool, list[dict[str, Any]]]:
        """Summaries appended since `cursor`, for callers that derive state incrementally.

        Returns (new_cursor, reset, summaries). reset=True means the index was
        rebuilt (or the cursor is foreign): discard derived state and apply the
        returned summaries, which are then ALL rows, from position 0. Otherwise
        they start at position cursor[1]. Hold `lock` while using the positions.
        """
        with self._lock:
            self.refresh()
            generation, count = cursor if cursor else (None, 0)
            current = (self.generation, len(self.rows))
            if generation != self.generation or count > len(self.rows):
                return current, True, list(self.rows)
            return current, False, self.rows[count:]

    def load(self, positions: Iterable[int]) -> list[dict[str, Any]]:
        """Fresh full rows re-read from the JSONL file, in the given order."""
        positions = list(positions)
        if not positions:
            return []
        with self._lock:
            spans = [self.spans[position] for position in positions]
        out = []
        with self.path.open("rb") as handle:
            for start, length in spans:
                handle.seek(start)
                out.append(json.loads(handle.read(length)))
        return out

    def stats(self) -> dict[str, Any]:
        self.refresh()
        return {"indexed_bytes": self.offset, "rows": len(self.rows),
                "unparseable_lines": len(self.bad_lines), "rebuilds": self.rebuilds}


_REGISTRY: dict[tuple[str, str], JsonlIndex] = {}
_REGISTRY_LOCK = threading.Lock()


def index_for(path: Path, summarize: Summarize, keys: Iterable[str], schema: str,
              persist: bool = True) -> JsonlIndex:
    """One shared index per (file, schema); paths are resolved at call time."""
    resolved = str(Path(path).resolve())
    with _REGISTRY_LOCK:
        index = _REGISTRY.get((resolved, schema))
        if index is None:
            index = _REGISTRY[(resolved, schema)] = JsonlIndex(Path(path), summarize, keys, schema, persist)
        return index


def _key_summary(key: str) -> Summarize:
    def summarize(row: dict[str, Any]) -> dict[str, Any]:
        return {key: str(row[key])} if key in row else {}
    return summarize


def indexed_jsonl_records(path: Path, key: str, value: Any) -> list[dict[str, Any]]:
    """Every JSON object in `path` whose `key` field equals `value` (as strings), file order."""
    if value is None:
        return []
    index = index_for(path, _key_summary(key), (key,), schema="key:" + key, persist=False)
    return index.load(index.lookup(key, str(value)))
