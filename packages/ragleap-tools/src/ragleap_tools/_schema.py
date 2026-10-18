"""
ragleap_tools._schema

Argument validation and function-to-schema conversion for the tool authoring
helpers (decorator.py and toolkit.py). Standard library only.

validate_arguments() checks a model's tool-call arguments against the small
JSON Schema subset this package's own tools use, BEFORE a handler runs, so a
wrong, missing or extra argument becomes a clean failed ToolResult instead of
a TypeError inside a tool-calling loop. Supported keywords: type, enum,
required, properties, additionalProperties, items, minItems, maxItems,
minLength, maxLength, minimum, maximum. Any other keyword is ignored, so a
handler must still validate what a schema cannot express.
"""

from __future__ import annotations

import inspect
import math
import re
import types
import typing
from typing import Any, Dict, List, Optional, Tuple

MAX_DEPTH = 20
MAX_DESCRIPTION_CHARS = 2000
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECTION_RE = re.compile(r"^(Args|Arguments|Parameters|Returns?|Raises|Yields?|Examples?|Notes?):\s*$")
_PARAM_RE = re.compile(r"^(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$")
_UNION_TYPE = getattr(types, "UnionType", None)


class ToolDefinitionError(ValueError):
    """A function cannot be turned into a tool. Raised when decorating (at
    import time), never when a model calls the tool."""


def clip(value: Any, limit: int = 60) -> str:
    """A short, printable form of a model-supplied value for error text."""
    text = "".join(ch if ch.isprintable() else "?" for ch in str(value)[: limit * 2])
    return text if len(text) <= limit else text[: limit - 3] + "..."


def safe_text(value: Any, limit: int = 500) -> str:
    """Whitespace-collapsed text capped at limit characters."""
    text = " ".join(str(value)[: limit * 4].split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": _is_int,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return a == b


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check(value: Any, schema: Any, path: str, depth: int) -> Optional[str]:
    if depth > MAX_DEPTH:
        return "%s is nested too deeply" % path
    if not isinstance(schema, dict) or not schema:
        return None
    declared = schema.get("type")
    if declared is not None:
        names = declared if isinstance(declared, list) else [declared]
        if not any(isinstance(n, str) and n in _TYPES and _TYPES[n](value) for n in names):
            return "%s must be of type %s" % (path, "/".join(clip(n, 20) for n in names))
    if isinstance(value, float) and not math.isfinite(value):
        return "%s must be a finite number" % path
    enum = schema.get("enum")
    if isinstance(enum, list) and not any(_same(value, o) for o in enum):
        return "%s must be one of the allowed values" % path
    if isinstance(value, str):
        if _num(schema.get("minLength")) and len(value) < schema["minLength"]:
            return "%s is shorter than %d characters" % (path, schema["minLength"])
        if _num(schema.get("maxLength")) and len(value) > schema["maxLength"]:
            return "%s is longer than %d characters" % (path, schema["maxLength"])
    elif _num(value):
        if _num(schema.get("minimum")) and value < schema["minimum"]:
            return "%s is below the minimum %s" % (path, schema["minimum"])
        if _num(schema.get("maximum")) and value > schema["maximum"]:
            return "%s is above the maximum %s" % (path, schema["maximum"])
    elif isinstance(value, list):
        if _num(schema.get("minItems")) and len(value) < schema["minItems"]:
            return "%s has fewer than %d items" % (path, schema["minItems"])
        if _num(schema.get("maxItems")) and len(value) > schema["maxItems"]:
            return "%s has more than %d items" % (path, schema["maxItems"])
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                err = _check(item, items, "%s[%d]" % (path, i), depth + 1)
                if err:
                    return err
    elif isinstance(value, dict):
        return _check_object(value, schema, path, depth, top=False)
    return None


def _check_object(obj: Dict[Any, Any], schema: Dict[str, Any], path: str, depth: int, top: bool) -> Optional[str]:
    required = schema.get("required")
    if isinstance(required, list):
        for name in required:
            if isinstance(name, str) and name not in obj:
                if top:
                    return "missing required argument '%s'" % clip(name)
                return "%s is missing '%s'" % (path, clip(name))
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    extra = schema.get("additionalProperties")
    for key, val in obj.items():
        if not isinstance(key, str):
            return "argument names must be strings"
        child = ("argument '%s'" % clip(key)) if top else "%s.%s" % (path, clip(key))
        if key in props:
            err = _check(val, props[key], child, depth + 1)
        elif extra is False or (top and props and extra is None):
            return "unknown argument '%s'" % clip(key) if top else "%s has an unknown key" % path
        elif isinstance(extra, dict):
            err = _check(val, extra, child, depth + 1)
        else:
            err = None
        if err:
            return err
    return None


def validate_arguments(schema: Any, arguments: Any) -> Optional[str]:
    """Returns None when the arguments satisfy the schema, else a short
    message naming the first problem. Unknown top-level arguments are rejected
    whenever the schema declares properties (a handler would raise TypeError
    for them), unless additionalProperties allows them."""
    if not isinstance(arguments, dict):
        return "arguments must be a JSON object"
    if not isinstance(schema, dict):
        return None
    return _check_object(arguments, schema, "argument", 0, top=True)


def _allows_null(sub: Any) -> bool:
    if not isinstance(sub, dict) or "type" not in sub:
        return True
    declared = sub["type"]
    return declared == "null" or (isinstance(declared, list) and "null" in declared)


def drop_null_optionals(schema: Any, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Models often send null for an optional argument they mean to omit.
    Drops such nulls (only for properties that are not required and whose
    schema does not accept null), so the handler sees its own default."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return arguments
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    return {
        k: v
        for k, v in arguments.items()
        if not (v is None and k in props and k not in required and not _allows_null(props[k]))
    }


# --- function -> JSON Schema ------------------------------------------------


def _annotation_schema(ann: Any, pname: str, nested: bool = False) -> Tuple[Dict[str, Any], bool]:
    """Returns (schema, is_optional) for a type annotation or raises
    ToolDefinitionError."""
    if ann is typing.Any:
        return {}, False
    if ann is bool:
        return {"type": "boolean"}, False
    if ann is str:
        return {"type": "string"}, False
    if ann is int:
        return {"type": "integer"}, False
    if ann is float:
        return {"type": "number"}, False
    origin = typing.get_origin(ann)
    args = typing.get_args(ann)
    if origin is typing.Union or (_UNION_TYPE is not None and origin is _UNION_TYPE):
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1 and len(args) == 2:
            if nested:
                raise ToolDefinitionError("parameter '%s': Optional is not supported inside list or dict types" % pname)
            inner, _ = _annotation_schema(non_none[0], pname, nested)
            return inner, True
        raise ToolDefinitionError(
            "parameter '%s': only Optional[X] unions are supported, not a union of several types" % pname
        )
    if origin is typing.Literal:
        values = list(args)
        kinds = {type(v) for v in values}
        if not values or len(kinds) != 1 or next(iter(kinds)) not in (str, int, bool):
            raise ToolDefinitionError(
                "parameter '%s': Literal values must be non-empty and all str, all int or all bool" % pname
            )
        kind = {str: "string", int: "integer", bool: "boolean"}[next(iter(kinds))]
        return {"type": kind, "enum": values}, False
    if ann is list or origin is list:
        if not args:
            return {"type": "array"}, False
        inner, _ = _annotation_schema(args[0], pname, True)
        return {"type": "array", "items": inner}, False
    if ann is dict or origin is dict:
        return {"type": "object"}, False
    raise ToolDefinitionError(
        "parameter '%s' has an unsupported type annotation %r (supported: str, int, float, bool, "
        "Optional[X], Literal[...], list[X], dict, Any)" % (pname, ann)
    )


def parse_docstring(doc: Optional[str]) -> Tuple[str, Dict[str, str]]:
    """Returns (summary, {param: description}) from a Google-style docstring.
    The summary is everything before the first section header, on one line."""
    if not doc:
        return "", {}
    lines = doc.splitlines()
    i = 0
    summary_lines: List[str] = []
    while i < len(lines) and not _SECTION_RE.match(lines[i].strip()):
        summary_lines.append(lines[i])
        i += 1
    summary = " ".join(" ".join(summary_lines).split())
    params: Dict[str, str] = {}
    while i < len(lines):
        m = _SECTION_RE.match(lines[i].strip())
        if m and m.group(1) in ("Args", "Arguments", "Parameters"):
            i += 1
            base: Optional[int] = None
            current: Optional[str] = None
            while i < len(lines):
                raw = lines[i]
                if not raw.strip():
                    i += 1
                    continue
                indent = len(raw) - len(raw.lstrip())
                if base is None:
                    base = indent
                if indent < base:
                    break
                if indent == base:
                    pm = _PARAM_RE.match(raw.strip())
                    if pm:
                        current = pm.group(1).lstrip("*")
                        params[current] = pm.group(2).strip()
                    else:
                        current = None
                elif current:
                    params[current] += " " + raw.strip()
                i += 1
            continue
        i += 1
    return summary, {k: " ".join(v.split()) for k, v in params.items()}


def build_parameters(fn: Any, param_docs: Dict[str, str]) -> Dict[str, Any]:
    """The JSON Schema "parameters" object for a plain function."""
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception as exc:  # noqa: BLE001 - unresolvable annotation is a definition error
        raise ToolDefinitionError("cannot resolve the type annotations (%s)" % type(exc).__name__) from None
    props: Dict[str, Any] = {}
    required: List[str] = []
    for pname, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ToolDefinitionError("parameter '%s': *args and **kwargs are not supported" % pname)
        if p.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise ToolDefinitionError("parameter '%s' is positional-only; a model passes arguments by name" % pname)
        if pname not in hints:
            raise ToolDefinitionError("parameter '%s' needs a type annotation" % pname)
        schema, optional = _annotation_schema(hints[pname], pname)
        if pname in param_docs and param_docs[pname]:
            schema["description"] = param_docs[pname]
        if p.default is inspect.Parameter.empty:
            if optional:
                raise ToolDefinitionError(
                    "parameter '%s' is Optional but has no default; write %s = None" % (pname, pname)
                )
            required.append(pname)
        else:
            d = p.default
            if d is not None:
                if not isinstance(d, (str, int, float, bool)):
                    raise ToolDefinitionError("parameter '%s': a default must be a str, int, float, bool or None" % pname)
                if _check(d, schema, "default", 0) is not None:
                    raise ToolDefinitionError("parameter '%s': the default does not match its annotation" % pname)
                schema["default"] = d
        props[pname] = schema
    return {"type": "object", "properties": props, "required": required}
