"""Minimal TOML reader for the model manifest. Standard library only.

Uses tomllib when it exists (Python 3.11+). On Python 3.10 it falls back to a strict subset
parser that understands exactly what models.toml uses: comments, [[array]] table headers and
key = value with basic strings, true/false, integers and one-line lists of strings. Anything
else raises ValueError instead of guessing.
"""
import re

try:
    import tomllib as _tomllib
except ImportError:  # Python 3.10
    _tomllib = None

_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_INT = re.compile(r"^[+-]?(0|[1-9][0-9]*)$")
_HEADER = re.compile(r"^\[\[([A-Za-z0-9_-]+)\]\]\s*(#.*)?$")
_ESC = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}


def loads(text):
    if _tomllib is not None:
        return _tomllib.loads(text)
    return _loads_subset(text)


def _read_string(s, i, lineno):
    i += 1
    out = []
    while i < len(s):
        ch = s[i]
        if ch == '"':
            return "".join(out), i + 1
        if ch == "\\":
            i += 1
            if i >= len(s) or s[i] not in _ESC:
                raise ValueError("line %d: unsupported escape sequence" % lineno)
            out.append(_ESC[s[i]])
        else:
            out.append(ch)
        i += 1
    raise ValueError("line %d: unterminated string" % lineno)


def _end(rest, lineno):
    rest = rest.strip()
    if rest and not rest.startswith("#"):
        raise ValueError("line %d: unexpected text after value" % lineno)


def _parse_value(raw, lineno):
    s = raw.strip()
    if s.startswith('"""') or s.startswith("'"):
        raise ValueError("line %d: unsupported string form" % lineno)
    if s.startswith('"'):
        val, j = _read_string(s, 0, lineno)
        _end(s[j:], lineno)
        return val
    if s.startswith("["):
        i, items = 1, []
        while True:
            while i < len(s) and s[i] in " \t":
                i += 1
            if i >= len(s):
                raise ValueError("line %d: unterminated list (lists must fit on one line)" % lineno)
            if s[i] == "]":
                i += 1
                break
            if s[i] != '"':
                raise ValueError("line %d: only lists of strings are supported" % lineno)
            val, i = _read_string(s, i, lineno)
            items.append(val)
            while i < len(s) and s[i] in " \t":
                i += 1
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "]":
                pass
            else:
                raise ValueError("line %d: expected ',' or ']' in list" % lineno)
        _end(s[i:], lineno)
        return items
    token = s.split("#", 1)[0].strip()
    if token == "true":
        return True
    if token == "false":
        return False
    if _INT.match(token):
        return int(token)
    raise ValueError("line %d: unsupported value" % lineno)


def _loads_subset(text):
    result = {}
    current = result
    seen = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[["):
            m = _HEADER.match(s)
            if not m:
                raise ValueError("line %d: unsupported table header" % lineno)
            name = m.group(1)
            result.setdefault(name, [])
            if not isinstance(result[name], list):
                raise ValueError("line %d: %s is not an array of tables" % (lineno, name))
            current = {}
            result[name].append(current)
            seen = set()
            continue
        if s.startswith("["):
            raise ValueError("line %d: only [[array]] tables are supported" % lineno)
        if "=" not in s:
            raise ValueError("line %d: expected key = value" % lineno)
        key, _, value = s.partition("=")
        key = key.strip()
        if not _KEY.match(key):
            raise ValueError("line %d: unsupported key" % lineno)
        if key in seen:
            raise ValueError("line %d: duplicate key %s" % (lineno, key))
        seen.add(key)
        current[key] = _parse_value(value, lineno)
    return result
