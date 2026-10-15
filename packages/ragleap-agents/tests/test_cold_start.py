"""Cold start: a default or empty configuration must fail closed visibly, never silently, and each gate
has a positive control (the same run with the gate off) so a pause can be traced to the gate.
Scripted model, no network."""
import json

import pytest
from ragleap_tools import Tool, ToolResult

from ragleap_agents import TRUSTED, Agent, Policy, ToolPolicy


def mk(name, log):
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    return Tool(name, "d", schema, lambda x: (log.append((name, x)), ToolResult(True, "r"))[1])


def script(*acts):
    q = [json.dumps(a) for a in acts]
    return lambda prompt: q.pop(0) if q else '{"tool": "done"}'


def call(name, x):
    return {"tool": name, "arguments": {"x": x}}


def test_the_very_first_step_is_never_gated_even_with_no_policy():
    log = []
    r = Agent(script(call("a", "1")), [mk("a", log)], summarize=False).run("t")
    assert (r.status, r.stop_reason, r.pending) == ("done", "done", None) and log == [("a", "1")]


def test_no_policy_pauses_the_second_step_visibly_and_declaring_trusted_is_the_only_difference():
    acts = (call("a", "1"), call("a", "2"), call("a", "3"))
    log1 = []
    r = Agent(script(*acts), [mk("a", log1)], summarize=False).run("t")
    assert r.status == "awaiting_approval" and r.pending["forced"] is True and r.pending["tool"] == "a"
    assert log1 == [("a", "1")] and r.tainted is True  # the pause is a visible status, not a silent stop
    log2 = []  # positive control: identical run, the tool declared trusted
    r2 = Agent(script(*acts), [mk("a", log2)], Policy(max_steps=4, tools={"a": TRUSTED}), summarize=False).run("t")
    assert (r2.status, r2.stop_reason) == ("done", "done") and r2.tainted is False
    assert log2 == [("a", "1"), ("a", "2"), ("a", "3")]


def test_an_outbound_tool_runs_first_but_is_paused_after_a_tainting_tool():
    pol = Policy(tools={"fetch": ToolPolicy(True, False), "send": ToolPolicy(False, True)})
    log = []  # positive control: nothing untrusted was read, so the send is allowed
    r = Agent(script(call("send", "hi")), [mk("fetch", log), mk("send", log)], pol, summarize=False).run("t")
    assert r.status == "done" and log == [("send", "hi")]
    log2 = []  # negative control: the same send after reading untrusted content
    r2 = Agent(script(call("fetch", "u"), call("send", "hi")), [mk("fetch", log2), mk("send", log2)], pol,
               summarize=False).run("t")
    assert r2.status == "awaiting_approval" and r2.pending["forced"] is True and log2 == [("fetch", "u")]


def test_a_policy_naming_a_tool_that_does_not_exist_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown tool"):
        Agent(script(), [mk("calc", [])], Policy(tools={"calcc": TRUSTED}))
    Agent(script(), [mk("calc", [])], Policy(tools={"calc": TRUSTED}))  # positive control: the right name is accepted
