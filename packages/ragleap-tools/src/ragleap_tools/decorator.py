"""
ragleap_tools.decorator

@tool turns a plain, type-annotated Python function into a Tool, so writing a
custom tool is a few lines instead of a hand-written JSON Schema:

    from ragleap_tools import tool, ToolError

    @tool
    def lookup_order(order_id: str, include_items: bool = False) -> dict:
        '''Look up an order by id.

        Args:
            order_id: The order id, for example "A-1001".
            include_items: Also return the line items.
        '''
        if order_id not in ORDERS:
            raise ToolError("order not found")
        return ORDERS[order_id]

The schema comes from the annotations and the Google-style docstring. Before
your function runs, the model's arguments are checked against that schema
(missing, unknown and wrongly typed arguments become a failed ToolResult and
the function is not called). Return a ToolResult to control the result
yourself; any other return value becomes ToolResult(success=True, result=...).
Raise ToolError for an expected failure whose message is safe to show the
model. Any other exception becomes "<name> failed (<ExceptionType>)" - only the
type name reaches the model, the detail goes to the "ragleap_tools" logger -
unless expose_errors=True. Supported annotations: str, int, float, bool,
Optional[X] (with a default), Literal[...], list[X], dict, Any. Async
functions are not supported yet.
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable, Dict, Optional

from ragleap_tools._schema import (
    MAX_DESCRIPTION_CHARS,
    NAME_RE,
    ToolDefinitionError,
    build_parameters,
    drop_null_optionals,
    parse_docstring,
    safe_text,
    validate_arguments,
)
from ragleap_tools.base import Tool, ToolError, ToolResult

_LOG = logging.getLogger("ragleap_tools")


def _make_handler(func: Callable[..., Any], tool_name: str, parameters: Dict[str, Any], expose_errors: bool):
    @functools.wraps(func)
    def handler(**kwargs: Any) -> ToolResult:
        args = drop_null_optionals(parameters, kwargs)
        problem = validate_arguments(parameters, args)
        if problem:
            return ToolResult(success=False, error="invalid arguments: " + problem)
        try:
            out = func(**args)
        except ToolError as exc:
            return ToolResult(success=False, error=safe_text(exc) or "%s failed" % tool_name)
        except Exception as exc:  # noqa: BLE001 - a tool must never crash the caller's loop
            _LOG.warning("tool %r raised %s", tool_name, type(exc).__name__, exc_info=True)
            text = "%s failed (%s)" % (tool_name, type(exc).__name__)
            if expose_errors and str(exc):
                text += ": " + safe_text(exc)
            return ToolResult(success=False, error=text)
        if isinstance(out, ToolResult):
            return out
        return ToolResult(success=True, result=out)

    return handler


def tool(
    fn: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    expose_errors: bool = False,
) -> Any:
    """Decorator: @tool or @tool(name=..., description=..., metadata=...,
    expose_errors=...). Returns a Tool (the original function stays reachable
    as tool.handler.__wrapped__)."""
    if isinstance(fn, str):
        raise TypeError("use @tool(name='...'), not @tool('...')")
    if metadata is not None and not isinstance(metadata, dict):
        raise TypeError("metadata must be a dict")

    def build(func: Callable[..., Any]) -> Tool:
        if not callable(func) or isinstance(func, type):
            raise ToolDefinitionError("@tool must decorate a plain function")
        if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
            raise ToolDefinitionError("async functions are not supported yet; wrap the call in a sync function")
        if inspect.isgeneratorfunction(func):
            raise ToolDefinitionError("generator functions are not supported")
        tool_name = name if name is not None else getattr(func, "__name__", "")
        if not isinstance(tool_name, str) or not NAME_RE.match(tool_name):
            raise ToolDefinitionError(
                "tool name %r is not valid (1-64 letters, digits, _ or -); pass name='...'" % (tool_name,)
            )
        summary, param_docs = parse_docstring(inspect.getdoc(func))
        text = description if description is not None else summary
        if not isinstance(text, str) or not text.strip():
            raise ToolDefinitionError("tool '%s' needs a description: add a docstring or pass description='...'" % tool_name)
        text = " ".join(text.split())
        if len(text) > MAX_DESCRIPTION_CHARS:
            raise ToolDefinitionError("tool '%s': the description is longer than %d characters" % (tool_name, MAX_DESCRIPTION_CHARS))
        parameters = build_parameters(func, param_docs)
        return Tool(
            name=tool_name,
            description=text,
            parameters=parameters,
            handler=_make_handler(func, tool_name, parameters, expose_errors),
            metadata=dict(metadata or {}),
        )

    if fn is not None:
        return build(fn)
    return build
