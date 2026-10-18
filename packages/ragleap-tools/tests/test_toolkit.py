"""Toolkit: collection, selection, schema export and safe dispatch."""
import json
import logging

import pytest

import ragleap_tools
from ragleap_tools import STATELESS_TOOLS, Tool, ToolError, ToolResult, Toolkit, default_toolkit, tool


def echo_tool(name="echo", props=None, required=None, record=None):
    def handler(**kw):
        if record is not None:
            record.append(kw)
        return ToolResult(success=True, result=kw)

    return Tool(
        name=name,
        description="d",
        parameters={"type": "object", "properties": props if props is not None else {"x": {"type": "integer"}},
                    "required": required if required is not None else []},
        handler=handler,
    )


def test_add_chains_and_lists_names_in_order():
    kit = Toolkit().add(echo_tool("a")).add(echo_tool("b"))
    assert kit.names() == ["a", "b"] and len(kit) == 2
    assert "a" in kit and "zzz" not in kit and 5 not in kit
    assert [t.name for t in kit] == ["a", "b"]
    assert kit.get("a").name == "a" and kit.get("zzz") is None and kit.get(None) is None
    assert repr(kit) == "Toolkit(a, b)"


def test_duplicate_names_and_non_tools_are_rejected():
    kit = Toolkit([echo_tool("a")])
    with pytest.raises(ValueError, match="duplicate tool name 'a'"):
        kit.add(echo_tool("a"))
    with pytest.raises(TypeError):
        kit.add("not a tool")
    with pytest.raises(ValueError):
        kit.add(echo_tool(""))
    assert kit.names() == ["a"]


def test_select_include_exclude_where():
    kit = Toolkit([echo_tool("a"), echo_tool("b"), echo_tool("c")])
    assert kit.select(include=["c", "a"]).names() == ["a", "c"]
    assert kit.select(exclude=["b"]).names() == ["a", "c"]
    assert kit.select(include=["a", "b"], exclude=["b"]).names() == ["a"]
    assert kit.select(where=lambda t: t.name != "a").names() == ["b", "c"]
    assert kit.names() == ["a", "b", "c"]  # the original is untouched


def test_select_unknown_names_raise_instead_of_silently_dropping():
    kit = Toolkit([echo_tool("a")])
    with pytest.raises(ValueError, match="unknown tool name 'typo'"):
        kit.select(include=["typo"])
    with pytest.raises(ValueError):
        kit.select(exclude=["typo"])
    with pytest.raises(ValueError):
        kit.select(include=[5])


def test_select_keeps_the_argument_size_limit_and_returns_a_new_toolkit():
    kit = Toolkit([echo_tool("a")], max_arguments_chars=50)
    sub = kit.select()
    assert sub is not kit and sub.max_arguments_chars == 50


def test_select_by_metadata():
    ro = Tool(name="r", description="d", parameters={"type": "object", "properties": {}},
              handler=lambda **kw: ToolResult(success=True), metadata={"read_only": True})
    kit = Toolkit([ro, echo_tool("w")])
    assert kit.select(where=lambda t: t.metadata.get("read_only")).names() == ["r"]


def test_schema_exports_have_the_three_provider_shapes():
    kit = Toolkit([echo_tool("a"), echo_tool("b")])
    assert [s["function"]["name"] for s in kit.to_openai_schema()] == ["a", "b"]
    assert [s["name"] for s in kit.to_gemini_schema()] == ["a", "b"]
    assert [s["name"] for s in kit.to_anthropic_schema()] == ["a", "b"]
    assert "input_schema" in kit.to_anthropic_schema()[0]


@pytest.mark.parametrize("bad", [0, -1, True, "5", None, 1.5])
def test_max_arguments_chars_must_be_a_positive_integer(bad):
    with pytest.raises(ValueError):
        Toolkit(max_arguments_chars=bad)


# --- call ------------------------------------------------------------------


def test_call_with_a_json_string_a_dict_or_nothing():
    rec = []
    kit = Toolkit([echo_tool("echo", record=rec)])
    assert kit.call("echo", '{"x": 1}').result == {"x": 1}
    assert kit.call("echo", {"x": 2}).result == {"x": 2}
    assert kit.call("echo").result == {}
    assert kit.call("echo", "").result == {}
    assert kit.call("echo", "   \n").result == {}
    assert kit.call("echo", None).result == {}
    assert rec == [{"x": 1}, {"x": 2}, {}, {}, {}, {}]


def test_call_does_not_mutate_the_callers_dict():
    kit = Toolkit([echo_tool("echo", props={"x": {"type": "integer"}, "y": {"type": "string"}})])
    args = {"x": 1, "y": None}
    kit.call("echo", args)
    assert args == {"x": 1, "y": None}


@pytest.mark.parametrize("name", ["nope", None, 5, ["echo"], b"echo", ""])
def test_unknown_tool_names_fail_cleanly(name):
    r = Toolkit([echo_tool()]).call(name, {})
    assert r.success is False and r.error.startswith("unknown tool")


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", "5", '"str"', "null", "true"])
def test_bad_json_or_non_object_json_fails_without_reaching_the_handler(raw):
    rec = []
    r = Toolkit([echo_tool(record=rec)]).call("echo", raw)
    assert r.success is False and rec == []
    assert r.error in ("arguments are not valid JSON", "arguments must be a JSON object")


@pytest.mark.parametrize("arguments", [[1], 5, 1.5, True, object()])
def test_arguments_of_the_wrong_python_type_fail(arguments):
    assert Toolkit([echo_tool()]).call("echo", arguments).error == "arguments must be a JSON object"


def test_non_string_argument_names_fail():
    assert Toolkit([echo_tool()]).call("echo", {1: "x"}).error == "argument names must be strings"


def test_oversize_arguments_fail_before_parsing():
    kit = Toolkit([echo_tool()], max_arguments_chars=20)
    r = kit.call("echo", '{"x": ' + "1" * 50 + "}")
    assert r.error == "arguments are too large (max 20 characters)"
    assert kit.call("echo", '{"x": 1}').success is True


def test_a_json_bomb_fails_cleanly():
    kit = Toolkit([echo_tool()])
    r = kit.call("echo", "[" * 90_000)
    assert r.success is False and r.error in ("arguments are not valid JSON", "arguments must be a JSON object")


@pytest.mark.parametrize("raw", ['{"x": "no"}', '{"zzz": 1}', '{"x": 1.5}'])
def test_arguments_failing_the_schema_never_reach_the_handler(raw):
    rec = []
    r = Toolkit([echo_tool(record=rec)]).call("echo", raw)
    assert r.success is False and r.error.startswith("invalid arguments: ") and rec == []


def test_missing_required_arguments_fail():
    rec = []
    kit = Toolkit([echo_tool(required=["x"], record=rec)])
    assert kit.call("echo", {}).error == "invalid arguments: missing required argument 'x'"
    assert rec == []


def test_null_for_an_optional_argument_is_dropped_before_the_handler():
    rec = []
    kit = Toolkit([echo_tool(record=rec)])
    assert kit.call("echo", '{"x": null}').success is True
    assert rec == [{}]


def test_unexpected_handler_exceptions_are_contained_and_type_only(caplog):
    def boom(**kw):
        raise RuntimeError("secret connection string")

    kit = Toolkit([Tool(name="boom", description="d", parameters={"type": "object", "properties": {}}, handler=boom)])
    with caplog.at_level(logging.WARNING, logger="ragleap_tools"):
        r = kit.call("boom", {})
    assert r == ToolResult(success=False, error="boom failed (RuntimeError)")
    assert any(rec.exc_info for rec in caplog.records)


def test_tool_error_from_a_plain_tool_reaches_the_model():
    def refuse(**kw):
        raise ToolError("not allowed")

    kit = Toolkit([Tool(name="t", description="d", parameters={"type": "object", "properties": {}}, handler=refuse)])
    assert kit.call("t", {}).error == "not allowed"


def test_a_handler_returning_the_wrong_type_is_reported():
    kit = Toolkit([Tool(name="t", description="d", parameters={"type": "object", "properties": {}},
                        handler=lambda **kw: {"oops": 1})])
    assert kit.call("t", {}).error == "t returned an invalid result"


def test_the_handlers_own_result_object_is_returned_unchanged():
    result = ToolResult(success=True, result=[1])
    kit = Toolkit([Tool(name="t", description="d", parameters={"type": "object", "properties": {}},
                        handler=lambda **kw: result)])
    assert kit.call("t", {}) is result


def test_an_argument_named_self_reaches_a_schema_free_tool():
    rec = []
    kit = Toolkit([echo_tool("t", props={}, record=rec)])
    assert kit.call("t", '{"self": 1}').success is True and rec == [{"self": 1}]


def test_decorated_tools_work_through_the_toolkit():
    @tool
    def greet(name: str, shout: bool = False) -> str:
        """Greet someone."""
        return name.upper() if shout else name

    kit = Toolkit([greet])
    assert kit.call("greet", '{"name": "ann", "shout": true}').result == "ANN"
    assert kit.call("greet", '{"name": 1}').success is False


# --- the built-in tools through the toolkit ----------------------------------

VALID = {
    "calculator": {"expression": "2 + 3"},
    "get_current_datetime": {},
    "add_to_date": {"iso_datetime": "2026-01-01T00:00:00", "days": 1},
    "date_difference": {"iso_datetime_a": "2026-01-01T00:00:00", "iso_datetime_b": "2026-01-02T00:00:00"},
    "convert_length": {"value": 1, "from_unit": "km", "to_unit": "m"},
    "convert_weight": {"value": 1, "from_unit": "kg", "to_unit": "g"},
    "convert_temperature": {"value": 0, "from_unit": "c", "to_unit": "f"},
    "parse_json": {"text": '{"a": 1}'},
    "parse_csv": {"text": "a,b\n1,2"},
    "regex_extract": {"text": "a1b22", "pattern": r"\d+"},
    "word_count": {"text": "a b c"},
    "text_case_transform": {"text": "abc", "mode": "upper"},
}
INVALID = {
    "calculator": {},
    "get_current_datetime": {"tz_offset_hours": "x"},
    "add_to_date": {"iso_datetime": 5},
    "date_difference": {"iso_datetime_a": "2026-01-01T00:00:00"},
    "convert_length": {"value": 1, "from_unit": "parsec", "to_unit": "m"},
    "convert_weight": {"value": "1", "from_unit": "kg", "to_unit": "g"},
    "convert_temperature": {"value": 0, "from_unit": "c"},
    "parse_json": {"text": 1},
    "parse_csv": {"text": "a", "has_header": "yes"},
    "regex_extract": {"text": "a"},
    "word_count": {"text": "a", "extra": 1},
    "text_case_transform": {"text": "abc", "mode": "snake"},
}


def test_every_builtin_tool_has_a_sample_call():
    assert set(VALID) == {t.name for t in STATELESS_TOOLS} == set(INVALID)


@pytest.mark.parametrize("name", sorted(VALID))
def test_builtin_tools_accept_valid_calls_through_the_toolkit(name):
    r = default_toolkit().call(name, json.dumps(VALID[name]))
    assert r.success is True, r.error


@pytest.mark.parametrize("name", sorted(INVALID))
def test_builtin_tools_reject_invalid_calls_without_raising(name):
    r = default_toolkit().call(name, INVALID[name])
    assert r.success is False and r.error


def test_null_optional_arguments_work_for_builtin_tools():
    assert default_toolkit().call("get_current_datetime", {"tz_offset_hours": None}).success is True
    assert default_toolkit().call("parse_csv", {"text": "a,b\n1,2", "has_header": None}).success is True


def test_default_toolkit_is_a_fresh_copy_of_the_stateless_tools():
    a, b = default_toolkit(), default_toolkit()
    assert a is not b and len(a) == 12 and a.names() == [t.name for t in STATELESS_TOOLS]
    a.add(echo_tool("extra"))
    assert len(default_toolkit()) == 12 and len(STATELESS_TOOLS) == 12


def test_the_new_names_are_exported():
    for n in ("tool", "Toolkit", "ToolError", "ToolDefinitionError", "default_toolkit", "validate_arguments"):
        assert n in ragleap_tools.__all__ and hasattr(ragleap_tools, n)
