"""ragleap_agents.state - where a paused run lives between run() and resume().

A run's state is a plain JSON-safe dict, so any store that can keep a string
works (a file, Redis, a database row). The library ships two stores: the
in-memory store and a SQLite store (standard library only).

Concurrency: resume() claims a paused run before it executes anything. A store
that offers save_if_status(run_id, state, expected_status) -> bool (an atomic
compare-and-set; both shipped stores do) makes that claim safe across threads
and processes. A store with only save() and load() cannot: if several workers
can resume the same run, give your store an atomic compare-and-set (or a row
lock) around that sequence.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, Optional, Protocol

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STATUSES = frozenset({"running", "awaiting_approval", "done", "rejected", "failed", "stopped"})


class StateStore(Protocol):
    def save(self, run_id: str, state: Dict[str, Any]) -> None: ...

    def load(self, run_id: str) -> Optional[Dict[str, Any]]: ...


class AtomicStateStore(StateStore, Protocol):
    def save_if_status(self, run_id: str, state: Dict[str, Any], expected_status: str) -> bool:
        """Save state only if the stored state's status is expected_status. True if saved."""
        ...


class InMemoryStateStore:
    """Keeps states as JSON text, so anything that cannot be serialised
    fails here, in development, and not in a real database later."""

    def __init__(self) -> None:
        self._data: Dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, run_id: str, state: Dict[str, Any]) -> None:
        text = json.dumps(state)
        with self._lock:
            self._data[run_id] = text

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            text = self._data.get(run_id)
        return None if text is None else json.loads(text)

    def save_if_status(self, run_id: str, state: Dict[str, Any], expected_status: str) -> bool:
        text = json.dumps(state)
        with self._lock:
            current = self._data.get(run_id)
            if current is None or json.loads(current).get("status") != expected_status:
                return False
            self._data[run_id] = text
        return True


def _check_run_id(run_id: Any) -> None:
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        raise ValueError("invalid run id: use 1-64 of A-Z a-z 0-9 _ -")


def _check_state(run_id: str, state: Any) -> None:
    if not isinstance(state, dict) or state.get("run_id") != run_id or state.get("status") not in _STATUSES:
        raise ValueError("invalid run state: it must be a dict whose run_id matches and whose status is known")


def _parse(run_id: str, text: Any) -> Dict[str, Any]:
    try:
        state = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError("stored run state is corrupt") from None
    if not isinstance(state, dict) or state.get("run_id") != run_id or state.get("status") not in _STATUSES:
        raise ValueError("stored run state is corrupt")
    return state


class SQLiteStateStore:
    """A durable store in one SQLite file (standard library only).

    - JSON text only; nothing is unpickled.
    - A new file is created with mode 0600 (an existing file keeps its mode).
    - Run ids are limited to 1-64 of A-Z a-z 0-9 _ -.
    - save_if_status is atomic across threads and processes (BEGIN IMMEDIATE).
    - A stored row that is not valid JSON, is not a dict, names another run or
      has an unknown status is refused with ValueError, never executed.
    - The file is not encrypted. Protect it like the data it holds: tool
      arguments and observations are saved in it.
    - Use a real file path. ':memory:' is refused: every connection would get
      its own empty database.
    """

    def __init__(self, path: Any, timeout: float = 30.0) -> None:
        if not isinstance(path, (str, os.PathLike)) or os.fspath(path) in ("", ":memory:"):
            raise ValueError("path must be a file path (':memory:' is not supported)")
        self._path = os.fspath(path)
        self._timeout = float(timeout)
        if not os.path.exists(self._path):
            os.close(os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600))
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL)")

    @contextlib.contextmanager
    def _db(self):
        conn = sqlite3.connect(self._path, timeout=self._timeout, isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()

    def save(self, run_id: str, state: Dict[str, Any]) -> None:
        _check_run_id(run_id)
        _check_state(run_id, state)
        text = json.dumps(state)
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO runs (run_id, state, updated) VALUES (?, ?, ?)", (run_id, text, time.time()))

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        _check_run_id(run_id)
        with self._db() as db:
            row = db.execute("SELECT state FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else _parse(run_id, row[0])

    def save_if_status(self, run_id: str, state: Dict[str, Any], expected_status: str) -> bool:
        _check_run_id(run_id)
        _check_state(run_id, state)
        text = json.dumps(state)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT state FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                if row is None or _parse(run_id, row[0])["status"] != expected_status:
                    db.execute("ROLLBACK")
                    return False
                db.execute("UPDATE runs SET state = ?, updated = ? WHERE run_id = ?", (text, time.time(), run_id))
                db.execute("COMMIT")
                return True
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    db.execute("ROLLBACK")
                raise
