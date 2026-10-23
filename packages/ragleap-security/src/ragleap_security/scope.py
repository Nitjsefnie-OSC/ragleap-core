"""Immutable tenant scopes. Stores must require a Scope so isolation cannot be skipped by a caller."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}\Z")
_FIELDS = ("tenant", "subject", "agent", "session")


class ScopeError(ValueError):
    """An invalid scope, or something that is not a Scope was used where one is required."""


@dataclass(frozen=True)
class Scope:
    """Who a piece of data belongs to: a tenant, and optionally a subject, agent and session.

    Each part is 1 to 128 characters of letters, digits and _ . : @ -, starting with a letter or
    digit. '/' and '=' are not allowed, which makes `key` unambiguous: two different scopes never
    share a key."""

    tenant: str
    subject: Optional[str] = None
    agent: Optional[str] = None
    session: Optional[str] = None

    def __post_init__(self) -> None:
        for f in _FIELDS:
            v = getattr(self, f)
            if v is None:
                if f == "tenant":
                    raise ScopeError("tenant is required")
                continue
            if not isinstance(v, str) or not _PART.match(v):
                raise ScopeError(f"invalid {f}")

    @property
    def key(self) -> str:
        return "/".join(f"{f}={getattr(self, f)}" for f in _FIELDS if getattr(self, f) is not None)

    @classmethod
    def parse(cls, key: str) -> "Scope":
        if not isinstance(key, str) or not key:
            raise ScopeError("invalid scope key")
        values = {}
        last = -1
        for part in key.split("/"):
            name, sep, value = part.partition("=")
            if not sep or name not in _FIELDS or _FIELDS.index(name) <= last:
                raise ScopeError("invalid scope key")
            last = _FIELDS.index(name)
            values[name] = value
        if "tenant" not in values:
            raise ScopeError("invalid scope key")
        return cls(**values)

    def covers(self, other: Any) -> bool:
        """True if `other` is this scope or narrower: same tenant, and every part set here is equal
        there. A tenant-wide scope covers its subjects; a subject scope never covers its tenant."""
        if type(other) is not Scope:
            return False
        if self.tenant != other.tenant:
            return False
        return all(getattr(self, f) is None or getattr(self, f) == getattr(other, f) for f in _FIELDS[1:])

    def narrow(self, **parts: str) -> "Scope":
        """Return a narrower scope. Parts already set cannot be changed."""
        values = {f: getattr(self, f) for f in _FIELDS}
        for name, value in parts.items():
            if name not in _FIELDS or name == "tenant":
                raise ScopeError("only subject, agent and session can be narrowed")
            if values[name] is not None and values[name] != value:
                raise ScopeError(f"{name} is already set")
            values[name] = value
        return Scope(**values)


def require_scope(value: Any) -> Scope:
    """Return value if it is exactly a Scope. Strings, dicts, None and subclasses are refused, so
    a caller cannot pass a forged object that claims to cover more than it does."""
    if type(value) is not Scope:
        raise ScopeError("a Scope is required")
    return value
