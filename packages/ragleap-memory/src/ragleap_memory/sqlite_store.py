"""SQLiteStore: durable memory in one SQLite file (or in memory), with FTS5 keyword search.

Every operation takes a Scope and is filtered by it inside the SQL, not by the caller. A scope sees
the entries whose scope it covers: a tenant-wide scope sees everything in the tenant, a narrower scope
sees only its own subject/agent/session, and an entry without a subject is not visible to a scope that
names one."""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

from ragleap_security import (AuditLog, Scope, check_json_shape, check_size, require_scope)

from .model import (ID_RE, KINDS, SOURCE_RE, TRUSTS, InvalidEntryError, MemoryEntry, MemoryStoreError,
                    NotFoundError, SearchHit, trust_rank)

SCHEMA_VERSION = 1
_SCOPE_FIELDS = ("tenant", "subject", "agent", "session")
_TOKEN = re.compile(r"\w+")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories(
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    tenant TEXT NOT NULL, subject TEXT, agent TEXT, session TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('episode','fact','summary')),
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    trust TEXT NOT NULL CHECK(trust IN ('untrusted','model','owner')),
    importance REAL NOT NULL CHECK(importance >= 0 AND importance <= 1),
    created_at TEXT NOT NULL,
    expires_at TEXT,
    superseded_by TEXT,
    derived_from TEXT NOT NULL,
    metadata TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_scope ON memories(tenant, subject, agent, session);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, content='memories', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
"""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _scope_clause(scope: Scope, alias: str = "") -> "tuple[str, list]":
    """SQL condition that matches exactly the entries `scope` covers."""
    p = f"{alias}." if alias else ""
    parts, params = [f"{p}tenant = ?"], [scope.tenant]
    for f in _SCOPE_FIELDS[1:]:
        v = getattr(scope, f)
        if v is not None:
            parts.append(f"{p}{f} = ?")
            params.append(v)
    return " AND ".join(parts), params


def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=row["id"],
        scope=Scope(row["tenant"], row["subject"], row["agent"], row["session"]),
        kind=row["kind"], text=row["text"], source=row["source"], trust=row["trust"],
        importance=row["importance"], created_at=row["created_at"], expires_at=row["expires_at"],
        superseded_by=row["superseded_by"], derived_from=tuple(json.loads(row["derived_from"])),
        metadata=json.loads(row["metadata"]),
    )


class SQLiteStore:
    def __init__(self, path: str = ":memory:", *, audit: Optional[AuditLog] = None,
                 clock: Optional[Callable[[], datetime]] = None, max_text_bytes: int = 8192,
                 max_results: int = 50):
        self.path = os.fspath(path)
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_text_bytes = max_text_bytes
        self.max_results = max_results
        self._lock = threading.RLock()
        if self.path != ":memory:" and not os.path.exists(self.path):
            os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600))
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.execute("PRAGMA secure_delete = ON")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self._db.close()
            raise MemoryStoreError(f"database schema version {version} is newer than this library supports")
        try:
            self._db.executescript(_SCHEMA)
        except sqlite3.OperationalError as e:
            self._db.close()
            raise MemoryStoreError("SQLite with FTS5 is required: %s" % e) from None
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # -- helpers -----------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            else:
                self._db.execute("COMMIT")

    def _log(self, event: str, scope: Scope, data: Dict[str, Any]) -> None:
        if self._audit is not None:  # inside the transaction: if the audit write fails, the change is rolled back
            self._audit.append(event, data, scope)

    def _visible(self, db: sqlite3.Connection, scope: Scope, entry_id: str) -> sqlite3.Row:
        clause, params = _scope_clause(scope)
        row = db.execute(f"SELECT * FROM memories WHERE id = ? AND {clause}", [entry_id, *params]).fetchone()
        if row is None:
            raise NotFoundError("no such entry")
        return row

    def _validate_new(self, scope: Any, text: Any, kind: str, source: str, trust: str, importance: Any,
                      expires_at: Any, metadata: Any) -> "tuple[Scope, str | None, str]":
        scope = require_scope(scope)
        if kind not in KINDS:
            raise InvalidEntryError("invalid kind")
        if trust not in TRUSTS:
            raise InvalidEntryError("invalid trust")
        if not isinstance(source, str) or not SOURCE_RE.match(source):
            raise InvalidEntryError("invalid source")
        if isinstance(importance, bool) or not isinstance(importance, (int, float)) or not 0 <= importance <= 1:
            raise InvalidEntryError("importance must be a number from 0 to 1")
        if not isinstance(text, str) or not text.strip():
            raise InvalidEntryError("text must be a non-empty string")
        check_size(text, self.max_text_bytes, "text")
        exp = None
        if expires_at is not None:
            if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
                raise InvalidEntryError("expires_at must be a timezone-aware datetime")
            exp = _iso(expires_at)
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise InvalidEntryError("metadata must be a dict")
        check_json_shape(metadata, max_depth=8, max_nodes=1000)
        try:
            meta_json = json.dumps(metadata, sort_keys=True)
        except (TypeError, ValueError):
            raise InvalidEntryError("metadata must be JSON serializable") from None
        check_size(meta_json, 4096, "metadata")
        return scope, exp, meta_json

    def _insert(self, db: sqlite3.Connection, scope: Scope, text: str, kind: str, source: str, trust: str,
                importance: float, exp: Optional[str], derived: Sequence[str], meta_json: str) -> MemoryEntry:
        entry_id = uuid.uuid4().hex
        created = _iso(self._clock())
        db.execute(
            "INSERT INTO memories(id, tenant, subject, agent, session, kind, text, source, trust, importance,"
            " created_at, expires_at, superseded_by, derived_from, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)",
            [entry_id, scope.tenant, scope.subject, scope.agent, scope.session, kind, text, source, trust,
             float(importance), created, exp, json.dumps(list(derived)), meta_json])
        return _row_to_entry(db.execute("SELECT * FROM memories WHERE id = ?", [entry_id]).fetchone())

    # -- public API --------------------------------------------------------------------------------

    def add(self, scope: Scope, text: str, *, kind: str = "fact", source: str = "api", trust: str = "untrusted",
            importance: float = 0.5, expires_at: Optional[datetime] = None, derived_from: Iterable[str] = (),
            metadata: Optional[Dict[str, Any]] = None) -> MemoryEntry:
        """Store an entry in exactly `scope`. trust defaults to the lowest level ("untrusted"): say
        "model" or "owner" explicitly. Every id in derived_from must be visible to `scope`."""
        scope, exp, meta_json = self._validate_new(scope, text, kind, source, trust, importance, expires_at, metadata)
        derived = list(derived_from)
        if len(derived) > 100 or len(set(derived)) != len(derived) or not all(isinstance(d, str) and ID_RE.match(d) for d in derived):
            raise InvalidEntryError("derived_from must be up to 100 distinct entry ids")
        with self._tx() as db:
            for d in derived:
                self._visible(db, scope, d)
            entry = self._insert(db, scope, text, kind, source, trust, importance, exp, derived, meta_json)
            self._log("memory.add", scope, {"id": entry.id, "kind": kind, "trust": trust})
        return entry

    def get(self, scope: Scope, entry_id: str) -> MemoryEntry:
        scope = require_scope(scope)
        with self._lock:
            return _row_to_entry(self._visible(self._db, scope, entry_id))

    def count(self, scope: Scope) -> int:
        scope = require_scope(scope)
        clause, params = _scope_clause(scope)
        with self._lock:
            return self._db.execute(f"SELECT COUNT(*) FROM memories WHERE {clause}", params).fetchone()[0]

    def search(self, scope: Scope, query: str, *, k: int = 5, kinds: Optional[Sequence[str]] = None,
               min_trust: str = "untrusted", include_superseded: bool = False,
               include_expired: bool = False) -> List[SearchHit]:
        """Keyword search (FTS5, bm25) over the entries `scope` can see. The query is split into
        words; any word may match. Operators in the query are treated as plain words."""
        scope = require_scope(scope)
        if not isinstance(query, str):
            raise InvalidEntryError("query must be a string")
        check_size(query, 1000, "query")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise InvalidEntryError("k must be a positive int")
        k = min(k, self.max_results)
        if min_trust not in TRUSTS:
            raise InvalidEntryError("invalid min_trust")
        kinds = tuple(kinds) if kinds is not None else KINDS
        if not kinds or any(x not in KINDS for x in kinds):
            raise InvalidEntryError("invalid kinds")
        tokens = _TOKEN.findall(query)[:32]
        if not tokens:
            return []
        match = " OR ".join('"%s"' % t for t in tokens)
        clause, params = _scope_clause(scope, "m")
        trusts = [t for t in TRUSTS if trust_rank(t) >= trust_rank(min_trust)]
        sql = (f"SELECT m.*, bm25(memories_fts) AS score FROM memories_fts JOIN memories m ON m.rowid = memories_fts.rowid"
               f" WHERE memories_fts MATCH ? AND {clause}"
               f" AND m.kind IN ({','.join('?' * len(kinds))}) AND m.trust IN ({','.join('?' * len(trusts))})")
        args: list = [match, *params, *kinds, *trusts]
        if not include_superseded:
            sql += " AND m.superseded_by IS NULL"
        if not include_expired:
            sql += " AND (m.expires_at IS NULL OR m.expires_at > ?)"
            args.append(_iso(self._clock()))
        sql += " ORDER BY score, m.created_at DESC LIMIT ?"
        args.append(k)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [SearchHit(_row_to_entry(r), -float(r["score"])) for r in rows]

    def supersede(self, scope: Scope, old_id: str, text: str, *, kind: Optional[str] = None, source: str = "api",
                  trust: str = "untrusted", importance: Optional[float] = None,
                  expires_at: Optional[datetime] = None, metadata: Optional[Dict[str, Any]] = None) -> MemoryEntry:
        """Replace an entry whose content changed. The new entry gets the old entry's exact scope; the
        old one stays in the store (see export, include_superseded) and points at its replacement."""
        scope = require_scope(scope)
        with self._tx() as db:
            old = self._visible(db, scope, old_id)
            if old["superseded_by"] is not None:
                raise InvalidEntryError("entry is already superseded")
            old_scope = Scope(old["tenant"], old["subject"], old["agent"], old["session"])
            kind = kind or old["kind"]
            importance = old["importance"] if importance is None else importance
            _, exp, meta_json = self._validate_new(old_scope, text, kind, source, trust, importance, expires_at, metadata)
            new = self._insert(db, old_scope, text, kind, source, trust, importance, exp, [old_id], meta_json)
            db.execute("UPDATE memories SET superseded_by = ? WHERE id = ?", [new.id, old_id])
            self._log("memory.supersede", scope, {"old": old_id, "new": new.id})
        return new

    def forget(self, scope: Scope, ids: Iterable[str]) -> int:
        """Delete the listed entries that `scope` can see; returns how many were deleted. They stop
        appearing in searches at once, but traces can stay in the database file until compact()
        or erase() runs."""
        scope = require_scope(scope)
        ids = list(ids)
        if len(ids) > 1000 or not all(isinstance(i, str) and ID_RE.match(i) for i in ids):
            raise InvalidEntryError("ids must be up to 1000 entry ids")
        if not ids:
            return 0
        clause, params = _scope_clause(scope)
        with self._tx() as db:
            n = db.execute(f"DELETE FROM memories WHERE id IN ({','.join('?' * len(ids))}) AND {clause}",
                           [*ids, *params]).rowcount
            self._log("memory.forget", scope, {"count": n})
        return n

    def export(self, scope: Scope) -> List[Dict[str, Any]]:
        """Every entry `scope` can see (superseded and expired ones too) as plain dicts."""
        scope = require_scope(scope)
        clause, params = _scope_clause(scope)
        with self._tx() as db:
            rows = db.execute(f"SELECT * FROM memories WHERE {clause} ORDER BY created_at, id", params).fetchall()
            self._log("memory.export", scope, {"count": len(rows)})
        return [_row_to_entry(r).to_dict() for r in rows]

    def erase(self, scope: Scope) -> int:
        """Delete everything `scope` can see, then rewrite the search index and checkpoint the
        journal so the deleted text is no longer in the database file. Returns the number deleted."""
        scope = require_scope(scope)
        clause, params = _scope_clause(scope)
        with self._tx() as db:
            n = db.execute(f"DELETE FROM memories WHERE {clause}", params).rowcount
            self._log("memory.erase", scope, {"count": n})
        self.compact()
        return n

    def sweep_expired(self, scope: Scope) -> int:
        """Delete expired entries inside `scope`; returns how many."""
        scope = require_scope(scope)
        clause, params = _scope_clause(scope)
        with self._tx() as db:
            n = db.execute(f"DELETE FROM memories WHERE {clause} AND expires_at IS NOT NULL AND expires_at <= ?",
                           [*params, _iso(self._clock())]).rowcount
            self._log("memory.sweep", scope, {"count": n})
        return n

    def compact(self) -> None:
        """Rewrite the full-text index and checkpoint the journal. Needed to remove deleted text from
        the file; erase() calls it. Can take a while on a large store."""
        with self._lock:
            self._db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('optimize')")
            if self.path != ":memory:":
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self) -> None:
        with self._lock:
            self._db.close()
