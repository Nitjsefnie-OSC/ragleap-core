"""v0.5.0 additions to Tool: metadata, to_anthropic_schema, ToolError."""
from ragleap_tools import Tool, ToolError, ToolResult


def make(**kw):
    return Tool(name="t", description="d", parameters={"type": "object", "properties": {}},
                handler=lambda **k: ToolResult(success=True), **kw)


def test_four_positional_arguments_still_construct_a_tool():
    t = Tool("t", "d", {"type": "object"}, lambda **k: ToolResult(success=True))
    assert t.metadata == {}


def test_metadata_defaults_to_an_independent_dict():
    a, b = make(), make()
    a.metadata["k"] = 1
    assert b.metadata == {}


def test_metadata_is_stored_as_given():
    assert make(metadata={"read_only": True}).metadata == {"read_only": True}


def test_anthropic_schema_shape():
    t = make()
    assert t.to_anthropic_schema() == {"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}


def test_metadata_never_appears_in_provider_schemas():
    t = make(metadata={"internal": "x"})
    for schema in (t.to_openai_schema(), t.to_gemini_schema(), t.to_anthropic_schema()):
        assert "internal" not in str(schema)


def test_tool_error_is_an_exception_with_its_message():
    assert issubclass(ToolError, Exception)
    assert str(ToolError("x")) == "x"
