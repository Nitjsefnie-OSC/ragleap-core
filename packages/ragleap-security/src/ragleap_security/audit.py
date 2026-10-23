"""A tamper-evident, append-only audit log: JSON Lines with a SHA-256 hash chain.

Tamper-EVIDENT, not tamper-proof. verify() detects an edited, reordered, inserted or removed record
in the middle of the log. It cannot detect that the END of the log was cut off, or that someone who
can rewrite the whole file recomputed every hash, unless you keep the last hash (or the record count)
somewhere they cannot write and pass it to verify() as an anchor."""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from .scope import Scope, require_scope
from .secrets import SecretStr

try:  # POSIX cross-process lock; on platforms without fcntl only threads in one process are safe
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

GENESIS = "0" * 64
MAX_RECORD_BYTES = 65_536
_EVENT = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_KEYS = {"seq", "ts", "event", "scope", "data", "prev", "hash"}


class AuditError(Exception):
    """The log cannot be appended to (corrupt, too large, bad input). Appends fail closed."""


def _default(o: Any) -> Any:
    if isinstance(o, SecretStr):
        return "[REDACTED]"
    raise TypeError(f"value of type {type(o).__name__} is not JSON serializable")


def _canon(record: Dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_default).encode("ascii")


def _digest(record_without_hash: Dict[str, Any]) -> str:
    return hashlib.sha256(_canon(record_without_hash)).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records: int
    last_hash: str
    error: Optional[str] = None
    line: Optional[int] = None


def verify(path: str, *, expected_count: Optional[int] = None, expected_last_hash: Optional[str] = None) -> VerifyResult:
    """Check every record's sequence number, chain link and hash. A missing or empty file is a valid
    empty log. Pass expected_count / expected_last_hash (kept outside the log) to detect truncation."""
    path = os.fspath(path)
    prev, count = GENESIS, 0

    def bad(msg: str, line: int) -> VerifyResult:
        return VerifyResult(False, count, prev, msg, line)

    if os.path.exists(path):
        with open(path, "rb") as f:
            for n, raw in enumerate(f, start=1):
                if len(raw) > MAX_RECORD_BYTES + 1:
                    return bad("record too large", n)
                if not raw.endswith(b"\n"):
                    return bad("last record is incomplete", n)
                try:
                    rec = json.loads(raw)
                except ValueError:
                    return bad("record is not valid JSON", n)
                if not isinstance(rec, dict) or set(rec) != _KEYS:
                    return bad("record has the wrong fields", n)
                if rec["seq"] != count + 1 or isinstance(rec["seq"], bool):
                    return bad("sequence number is out of order", n)
                if rec["prev"] != prev:
                    return bad("chain link does not match the previous record", n)
                body = {k: v for k, v in rec.items() if k != "hash"}
                if not isinstance(rec["hash"], str) or not hmac.compare_digest(rec["hash"], _digest(body)):
                    return bad("record hash does not match its content", n)
                prev, count = rec["hash"], count + 1
    if expected_count is not None and expected_count != count:
        return VerifyResult(False, count, prev, "record count does not match the anchor", None)
    if expected_last_hash is not None and not hmac.compare_digest(expected_last_hash, prev):
        return VerifyResult(False, count, prev, "last hash does not match the anchor", None)
    return VerifyResult(True, count, prev)


class AuditLog:
    """Append-only audit log at `path` (created with mode 0600). Safe for several threads, and for
    several processes on POSIX."""

    def __init__(self, path: str):
        self.path = os.fspath(path)
        self._tlock = threading.Lock()

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with self._tlock:
            if fcntl is None:  # pragma: no cover
                yield
                return
            fd = os.open(self.path + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)  # closing releases the flock

    def _last(self) -> tuple:
        try:
            size = os.path.getsize(self.path)
        except FileNotFoundError:
            return 0, GENESIS
        if size == 0:
            return 0, GENESIS
        window = 2 * MAX_RECORD_BYTES
        with open(self.path, "rb") as f:
            f.seek(max(0, size - window))
            tail = f.read()
        if not tail.endswith(b"\n"):
            raise AuditError("the log ends with an incomplete record; refusing to append")
        lines = tail.split(b"\n")
        try:
            rec = json.loads(lines[-2])
            body = {k: v for k, v in rec.items() if k != "hash"}
            if set(rec) != _KEYS or rec["hash"] != _digest(body):
                raise ValueError
            return rec["seq"], rec["hash"]
        except (ValueError, TypeError, IndexError, AttributeError):
            raise AuditError("the last record is not valid; refusing to append") from None

    def append(self, event: str, data: Optional[Dict[str, Any]] = None, scope: Optional[Scope] = None) -> Dict[str, Any]:
        """Append one record and return it. `event` is lower-case words (a-z 0-9 . _ -). SecretStr
        values in `data` are written as [REDACTED]. Raises AuditError rather than write a bad record."""
        if not isinstance(event, str) or not _EVENT.match(event):
            raise AuditError("invalid event name")
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise AuditError("data must be a dict")
        scope_key = require_scope(scope).key if scope is not None else None
        with self._locked():
            seq, prev = self._last()
            body = {
                "seq": seq + 1,
                "ts": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                "event": event,
                "scope": scope_key,
                "data": data,
                "prev": prev,
            }
            try:
                record = dict(body, hash=_digest(body))
                line = _canon(record) + b"\n"
            except (TypeError, ValueError) as e:
                raise AuditError(f"data cannot be serialized: {e}") from None
            if len(line) > MAX_RECORD_BYTES:
                raise AuditError(f"record is larger than {MAX_RECORD_BYTES} bytes")
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                view = memoryview(line)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            return json.loads(line)

    def verify(self, *, expected_count: Optional[int] = None, expected_last_hash: Optional[str] = None) -> VerifyResult:
        with self._locked():
            return verify(self.path, expected_count=expected_count, expected_last_hash=expected_last_hash)
