"""The @tool decorator: schema generation, definition errors and call behaviour."""
import logging
from typing import Any, List, Literal, Optional

import pytest

from ragleap_tools import Tool, ToolDefinitionError, ToolError, ToolResult, tool


def test_schema_comes_from_annotations_and_google_docstring():
    @tool
    def lookup_order(order_id: str, include_items: bool = False, limit: int = 10, ratio: float = 0.5) -> dict:
        """Look up an order by id.

        Longer text that continues the summary.

        Args:
            order_id (str): The order id, for example "A-1001".
            include_items: Also return the
                line items.
            limit: Max items.

        Returns:
            A dict.
        """
        return {}

    assert isinstance(lookup_order, Tool)
    assert lookup_order.name == "lookup_order"
    assert lookup_order.description == "Look up an order by id. Longer text that continues the summary."
    p = lookup_order.parameters
    assert p["type"] == "object" and p["required"] == ["order_id"]
    assert p["properties"]["order_id"] == {"type": "string", "description": 'The order id, for example "A-1001".'}
    assert p["properties"]["include_items"] == {"type": "boolean", "description": "Also return the line items.", "default": False}
    assert p["properties"]["limit"] == {"type": "integer", "description": "Max items.", "default": 10}
    assert p["properties"]["ratio"] == {"type": "number", "default": 0.5}


def test_name_and_description_overrides():
    @tool(name="renamed", description="  custom   text ")
    def f(x: int):
        pass

    assert f.name == "renamed" and f.description == "custom text"


def test_both_decorator_forms_work():
    @tool
    def a(x: int):
        """Doc a."""

    @tool()
    def b(x: int):
        """Doc b."""

    assert a.name == "a" and b.name == "b"


def test_misuse_of_the_decorator_is_rejected():
    with pytest.raises(TypeError):
        tool("name")
    with pytest.raises(TypeError):
        tool(metadata=[1])
    with pytest.raises(ToolDefinitionError):
        tool(42)


def _plain(x: int):
    """Doc."""


def test_invalid_or_missing_names_are_rejected():
    with pytest.raises(ToolDefinitionError, match="is not valid"):
        tool(lambda x: x)  # "<lambda>" is not a valid name
    with pytest.raises(ToolDefinitionError, match="is not valid"):
        tool(name="has space")(_plain)
    with pytest.raises(ToolDefinitionError, match="is not valid"):
        tool(name="n" * 65)(_plain)
    with pytest.raises(ToolDefinitionError, match="is not valid"):
        tool(name="")(_plain)
    assert tool(name="n" * 64)(_plain).name == "n" * 64
    assert tool(name="a-b_9")(_plain).name == "a-b_9"


def test_a_description_is_required_and_capped():
    def f(x: int):
        pass

    with pytest.raises(ToolDefinitionError, match="needs a description"):
        tool(f)
    with pytest.raises(ToolDefinitionError, match="longer than"):
        tool(description="d" * 2001)(f)


def test_docstring_with_only_sections_needs_an_explicit_description():
    def f(x: int):
        """Args:
            x: a number.
        """

    with pytest.raises(ToolDefinitionError, match="needs a description"):
        tool(f)
    assert tool(description="ok")(f).parameters["properties"]["x"]["description"] == "a number."


def test_metadata_is_copied_and_kept():
    meta = {"read_only": True}

    @tool(metadata=meta)
    def f(x: int):
        """Doc."""

    meta["read_only"] = False
    assert f.metadata == {"read_only": True}


def test_original_function_is_reachable():
    def f(x: int):
        """Doc."""
        return x

    t = tool(f)
    assert t.handler.__wrapped__ is f


def test_provider_schemas_do_not_carry_metadata():
    @tool(metadata={"secret": 1})
    def f(x: int):
        """Doc."""

    assert "metadata" not in str(f.to_openai_schema()) and "metadata" not in str(f.to_anthropic_schema())


def test_supported_annotations():
    @tool
    def f(
        a: Optional[str] = None,
        b: Literal["x", "y"] = "x",
        c: Literal[1, 2] = 1,
        d: List[int] = None,
        e: list[str] = None,
        f_: dict = None,
        g: Any = None,
        h: list = None,
    ):
        """Doc."""

    props = f.parameters["properties"]
    assert props["a"] == {"type": "string"}
    assert props["b"] == {"type": "string", "enum": ["x", "y"], "default": "x"}
    assert props["c"] == {"type": "integer", "enum": [1, 2], "default": 1}
    assert props["d"] == {"type": "array", "items": {"type": "integer"}}
    assert props["e"] == {"type": "array", "items": {"type": "string"}}
    assert props["f_"] == {"type": "object"}
    assert props["g"] == {}
    assert props["h"] == {"type": "array"}
    assert f.parameters["required"] == []


def test_pep604_optional_syntax():
    @tool
    def f(a: "str | None" = None):
        """Doc."""

    assert f.parameters["properties"]["a"] == {"type": "string"}


@pytest.mark.parametrize(
    "build,needle",
    [
        (lambda: tool(_def_optional_no_default), "Optional but has no default"),
        (lambda: tool(_def_union), "union of several types"),
        (lambda: tool(_def_literal_mixed), "Literal values"),
        (lambda: tool(_def_set), "unsupported type annotation"),
        (lambda: tool(_def_missing), "needs a type annotation"),
        (lambda: tool(_def_varargs), "args and .*kwargs"),
        (lambda: tool(_def_varkw), "args and .*kwargs"),
        (lambda: tool(_def_posonly), "positional-only"),
        (lambda: tool(_def_bad_default), "default must be"),
        (lambda: tool(_def_mismatched_default), "does not match"),
        (lambda: tool(_def_nested_optional), "Optional is not supported inside"),
        (lambda: tool(_def_unresolvable), "cannot resolve"),
        (lambda: tool(_def_async), "async functions"),
        (lambda: tool(_def_gen), "generator functions"),
        (lambda: tool(_Cls), "plain function"),
    ],
)
def test_definition_errors(build, needle):
    with pytest.raises(ToolDefinitionError, match=needle):
        build()


def _def_optional_no_default(a: Optional[str]):
    """Doc."""


def _def_union(a: "int | str" = 1):
    """Doc."""


def _def_literal_mixed(a: Literal["x", 1] = "x"):
    """Doc."""


def _def_set(a: set = None):
    """Doc."""


def _def_missing(a):
    """Doc."""


def _def_varargs(*a: int):
    """Doc."""


def _def_varkw(**a: int):
    """Doc."""


def _def_posonly(a: int, /):
    """Doc."""


def _def_bad_default(a: str = ["x"]):
    """Doc."""


def _def_mismatched_default(a: int = "x"):
    """Doc."""


def _def_nested_optional(a: List[Optional[int]] = None):
    """Doc."""


def _def_unresolvable(a: "DoesNotExist" = None):  # noqa: F821
    """Doc."""


async def _def_async(a: int):
    """Doc."""


def _def_gen(a: int):
    """Doc."""
    yield a


class _Cls:
    """Doc."""


# --- calling ---------------------------------------------------------------


def make_counter():
    calls = []

    @tool
    def add(a: int, b: int = 1, note: Optional[str] = None) -> int:
        """Add numbers."""
        calls.append((a, b, note))
        return a + b

    return add, calls


def test_success_wraps_the_return_value():
    add, calls = make_counter()
    r = add.call(a=2, b=3)
    assert r == ToolResult(success=True, result=5, error=None)
    assert calls == [(2, 3, None)]


def test_a_returned_tool_result_passes_through():
    @tool
    def f(x: int):
        """Doc."""
        return ToolResult(success=False, error="custom")

    assert f.call(x=1) == ToolResult(success=False, error="custom")


@pytest.mark.parametrize("kwargs", [{}, {"a": "1"}, {"a": 1, "zzz": 1}, {"a": True}, {"a": 1, "b": "x"}])
def test_invalid_arguments_never_reach_the_function(kwargs):
    add, calls = make_counter()
    r = add.call(**kwargs)
    assert r.success is False and r.error.startswith("invalid arguments: ")
    assert calls == []


def test_null_for_an_optional_argument_means_omitted():
    add, calls = make_counter()
    assert add.call(a=1, b=None, note=None).result == 2
    assert calls == [(1, 1, None)]


def test_null_for_a_required_argument_is_invalid():
    add, calls = make_counter()
    assert add.call(a=None).success is False and calls == []


def test_tool_error_message_reaches_the_model_collapsed():
    @tool
    def f(x: int):
        """Doc."""
        raise ToolError("order   not\nfound")

    assert f.call(x=1) == ToolResult(success=False, error="order not found")


def test_tool_error_with_no_message_uses_a_generic_one():
    @tool
    def f(x: int):
        """Doc."""
        raise ToolError()

    assert f.call(x=1).error == "f failed"


def test_long_tool_error_is_capped():
    @tool
    def f(x: int):
        """Doc."""
        raise ToolError("e" * 10000)

    assert len(f.call(x=1).error) == 500


def test_unexpected_exception_exposes_only_the_type_and_is_logged(caplog):
    @tool
    def f(x: int):
        """Doc."""
        raise KeyError("password=hunter2")

    with caplog.at_level(logging.WARNING, logger="ragleap_tools"):
        r = f.call(x=1)
    assert r == ToolResult(success=False, error="f failed (KeyError)")
    assert "hunter2" not in r.error
    assert any(rec.exc_info and "KeyError" in rec.getMessage() for rec in caplog.records)


def test_expose_errors_includes_the_message():
    @tool(expose_errors=True)
    def f(x: int):
        """Doc."""
        raise ValueError("bad   value")

    assert f.call(x=1).error == "f failed (ValueError): bad value"


def test_keyboard_interrupt_is_not_swallowed():
    @tool
    def f(x: int):
        """Doc."""
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        f.call(x=1)


def test_an_argument_named_self_is_rejected_cleanly_not_with_a_type_error():
    add, calls = make_counter()
    r = add.call(self="x", a=1)
    assert r.success is False and "unknown argument 'self'" in r.error and calls == []
