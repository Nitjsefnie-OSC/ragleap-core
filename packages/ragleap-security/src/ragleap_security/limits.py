"""Hard limits for untrusted input: size, nesting depth, node count, and deadlines."""
from __future__ import annotations

import time
from typing import Any, BinaryIO


class LimitError(ValueError):
    """A configured limit was exceeded. The message never contains the input."""


def _nonneg_int(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative int")


def check_size(data: Any, max_bytes: int, what: str = "input") -> None:
    """Raise LimitError if a str (measured as UTF-8) or bytes value is larger than max_bytes."""
    _nonneg_int(max_bytes, "max_bytes")
    if isinstance(data, str):
        n = len(data.encode("utf-8", "surrogatepass"))
    elif isinstance(data, (bytes, bytearray, memoryview)):
        n = len(data)
    else:
        raise TypeError("data must be str or bytes")
    if n > max_bytes:
        raise LimitError(f"{what} is larger than {max_bytes} bytes")


def check_json_shape(obj: Any, *, max_depth: int = 32, max_nodes: int = 100_000) -> None:
    """Raise LimitError if nested dict/list/tuple data is deeper than max_depth or has more than
    max_nodes values. Iterative, so hostile nesting cannot cause a RecursionError."""
    for name, v in (("max_depth", max_depth), ("max_nodes", max_nodes)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f"{name} must be a positive int")
    stack = [(obj, 1)]
    nodes = 0
    while stack:
        cur, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise LimitError(f"data has more than {max_nodes} values")
        if depth > max_depth:
            raise LimitError(f"data is nested deeper than {max_depth} levels")
        if isinstance(cur, dict):
            stack.extend((v, depth + 1) for v in cur.values())
        elif isinstance(cur, (list, tuple)):
            stack.extend((v, depth + 1) for v in cur)


def bounded_read(fp: BinaryIO, max_bytes: int, what: str = "input") -> bytes:
    """Read at most max_bytes from fp; raise LimitError if there is more."""
    _nonneg_int(max_bytes, "max_bytes")
    data = fp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise LimitError(f"{what} is larger than {max_bytes} bytes")
    return data


class Deadline:
    """A monotonic deadline. Use check() inside loops that handle untrusted work."""

    def __init__(self, seconds: float, clock=time.monotonic):
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError("seconds must be a non-negative number")
        self._clock = clock
        self._end = clock() + float(seconds)

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    def expired(self) -> bool:
        return self._clock() >= self._end

    def check(self, what: str = "operation") -> None:
        if self.expired():
            raise LimitError(f"{what} exceeded its deadline")
