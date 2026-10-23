"""Secret handling: a wrapper that never prints its value, env lookup by name, and redaction."""
from __future__ import annotations

import hmac
import os
import re
from typing import Iterable, Optional, Union

from .limits import LimitError

MASK = "[REDACTED]"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
MIN_REDACT_LEN = 6  # exact-value redaction ignores values shorter than this (it would shred text)


class SecretError(Exception):
    """A secret is missing or misused. The message never contains a secret value."""


class SecretStr:
    """Holds a secret. str(), repr(), format() and f-strings show a mask; reveal() returns the value.
    It cannot be pickled or used as a dict key, and equality is constant-time."""

    __slots__ = ("_v",)

    def __init__(self, value: str):
        if not isinstance(value, str):
            raise TypeError("SecretStr needs a str")
        self._v = value

    def reveal(self) -> str:
        return self._v

    def __repr__(self) -> str:
        return "SecretStr('**********')"

    def __str__(self) -> str:
        return "**********"

    def __format__(self, spec: str) -> str:
        return "**********"

    def __bool__(self) -> bool:
        return bool(self._v)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            other_v = other._v
        elif isinstance(other, str):
            other_v = other
        else:
            return NotImplemented
        return hmac.compare_digest(self._v.encode("utf-8", "surrogatepass"), other_v.encode("utf-8", "surrogatepass"))

    __hash__ = None  # type: ignore[assignment]

    def __reduce__(self):
        raise TypeError("SecretStr cannot be pickled")

    def __copy__(self) -> "SecretStr":
        return SecretStr(self._v)

    def __deepcopy__(self, memo) -> "SecretStr":
        return SecretStr(self._v)


def from_env(name: str, *, required: bool = True) -> Optional[SecretStr]:
    """Read a secret from the environment variable `name`. An unset or empty variable is missing.
    The error names the variable, never a value."""
    if not isinstance(name, str) or not _ENV_NAME.match(name):
        raise SecretError("invalid environment variable name")
    value = os.environ.get(name)
    if not value:
        if required:
            raise SecretError(f"environment variable {name} is not set")
        return None
    return SecretStr(value)


_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----.{0,8000}?-----END [A-Z ]{0,30}PRIVATE KEY-----", re.S), MASK),
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:(?:bearer|basic|token)\s+)?[A-Za-z0-9._~+/=-]{8,512}"), r"\1" + MASK),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,512}"), "Bearer " + MASK),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,200}"), MASK),
    (re.compile(r"\bgsk_[A-Za-z0-9]{16,200}"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,60}"), MASK),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,100}"), MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,120}"), MASK),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,100}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),
]


def redact(text: str, secrets: Iterable[Union[SecretStr, str]] = (), *, max_chars: int = 1_000_000) -> str:
    """Replace known secret values and common credential formats in text with a mask.

    This is a heuristic. It removes the exact values you pass in `secrets` (values shorter than
    MIN_REDACT_LEN characters are ignored) and credentials that match well-known formats. It cannot
    find a secret in a format it does not know. Treat it as a last line of defence for logs and
    error messages, never as a reason to log secrets."""
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    if len(text) > max_chars:
        raise LimitError(f"text is longer than {max_chars} characters")
    out = text
    for s in secrets:
        v = s.reveal() if isinstance(s, SecretStr) else s
        if isinstance(v, str) and len(v) >= MIN_REDACT_LEN:
            out = out.replace(v, MASK)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
