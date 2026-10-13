"""Mode-aware prompt wording. Scripted model, no network."""
import pytest
from ragleap_tools import Tool, ToolResult

from ragleap_agents import TRUSTED, Agent, Policy

TOOL = Tool("calc", "Evaluate", {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
            lambda expression: ToolResult(True, "1"))


def first_prompt(advertised=None, **kw):
    seen = []

    def llm(prompt):
        seen.append(prompt)
        return '{"tool": "done"}'
    if advertised:
        llm.prompt_style = advertised
    Agent(llm, [TOOL], Policy(tools={"calc": TRUSTED}), summarize=False, **kw).run("q")
    return seen[0]


def test_json_is_the_default_and_asks_for_json_as_plain_text():
    p = first_prompt()
    assert 'reply exactly {"tool": "done"}' in p and "ONLY one JSON object" in p
    assert "do not use any tool-calling or function-calling feature" in p


def test_native_style_never_asks_for_json_and_says_to_call_tools_directly():
    p = first_prompt("native")
    assert "JSON" not in p and "reply exactly" not in p
    assert "call exactly one of the provided tools by its own name" in p and "answer in plain text" in p


def test_an_explicit_style_beats_the_one_the_model_callable_advertises():
    assert "call exactly one of the provided tools" in first_prompt("json", prompt_style="native")
    assert "ONLY one JSON object" in first_prompt("native", prompt_style="json")


def test_an_unknown_style_is_refused_whether_passed_or_advertised():
    with pytest.raises(ValueError):
        Agent(lambda p: "", [TOOL], prompt_style="xml")

    def llm(p):
        return ""
    llm.prompt_style = "xml"
    with pytest.raises(ValueError):
        Agent(llm, [TOOL])


@pytest.mark.parametrize("style,needle", [("json", "Reply again with ONLY one valid JSON object"),
                                          ("native", "Call one of the provided tools, or answer in plain text")])
def test_the_repair_note_matches_the_style(style, needle):
    seen, replies = [], ["", '{"tool": "done"}']

    def llm(prompt):
        seen.append(prompt)
        return replies.pop(0)
    llm.prompt_style = style
    Agent(llm, [TOOL], Policy(tools={"calc": TRUSTED}, repair_attempts=1), summarize=False).run("q")
    assert needle in seen[1] and needle not in seen[0]
