"""Tests for ragleap_agents.delegate: the building blocks of sub-agents (design: #827).
Pure validation and policy computation; nothing here runs a model or a network call."""
import pytest
from ragleap_tools import Tool, ToolResult

from ragleap_agents import MAX_DEPTH_CEILING, TRUSTED, Agent, Budget, Policy, ToolPolicy, delegate_policy
from ragleap_agents.delegate import check_max_depth

READ = ToolPolicy(taints=True, outbound=False)
SEND = ToolPolicy(taints=False, outbound=True)


def _tool(name):
    return Tool(name, "d", {"type": "object", "properties": {}}, lambda: ToolResult(True, "x"))


def _llm(prompt):
    return '{"tool": "done"}'


def _agent(**declared):
    """An agent with one tool per keyword; the value is the ToolPolicy declared for it (None = undeclared)."""
    return Agent(_llm, [_tool(n) for n in declared], Policy(tools={n: p for n, p in declared.items() if p is not None}))


def test_a_child_with_only_trusted_tools_does_not_taint_the_parent():
    pol = delegate_policy({"calc": _agent(calc=TRUSTED)})
    assert (pol.taints, pol.outbound, pol.requires_approval) == (False, False, False)


def test_a_child_with_a_tainting_tool_taints_the_parent():
    pol = delegate_policy({"reader": _agent(fetch=READ, calc=TRUSTED)})
    assert pol.taints is True and pol.outbound is False


def test_one_tainting_child_among_trusted_ones_is_enough():
    assert delegate_policy({"a": _agent(calc=TRUSTED), "b": _agent(fetch=READ)}).taints is True


def test_the_delegate_policy_is_never_outbound():
    assert delegate_policy({"actor": _agent(send=SEND)}, allow_outbound=True).outbound is False


def test_a_nested_delegate_tool_counts_by_its_declared_policy():
    assert delegate_policy({"mid": _agent(sub=READ)}).taints is True
    assert delegate_policy({"mid": _agent(sub=TRUSTED)}).taints is False


def test_an_undeclared_child_tool_is_refused():
    with pytest.raises(ValueError, match="no declared policy"):
        delegate_policy({"c": _agent(fetch=None)})


def test_an_outbound_child_tool_needs_allow_outbound():
    children = {"c": _agent(send=SEND)}
    with pytest.raises(ValueError, match="allow_outbound"):
        delegate_policy(children)
    assert delegate_policy(children, allow_outbound=True).outbound is False


def test_a_child_tool_that_needs_approval_is_allowed_at_construction():
    pol = delegate_policy({"c": _agent(fetch=ToolPolicy(True, False, requires_approval=True))})
    assert pol.taints is True


@pytest.mark.parametrize("bad", [{}, None, [], "x", {"c": "not an agent"}])
def test_bad_children_are_refused(bad):
    with pytest.raises(ValueError):
        delegate_policy(bad)


def test_a_bad_child_name_is_refused():
    with pytest.raises(ValueError, match="invalid child name"):
        delegate_policy({"bad name": _agent(calc=TRUSTED)})


def test_allow_outbound_must_be_a_bool():
    with pytest.raises(ValueError):
        delegate_policy({"c": _agent(calc=TRUSTED)}, allow_outbound="yes")


def test_budget_defaults_and_validation():
    b = Budget()
    assert (b.max_delegations, b.max_child_steps) == (4, 16)
    for bad in (0, -1, True, 2.5, "3", None):
        with pytest.raises(ValueError):
            Budget(max_delegations=bad)
        with pytest.raises(ValueError):
            Budget(max_child_steps=bad)
    with pytest.raises(Exception):
        b.max_delegations = 9  # frozen


def test_the_depth_ceiling_is_three():
    assert MAX_DEPTH_CEILING == 3


@pytest.mark.parametrize("ok", [1, 2, 3])
def test_max_depth_accepts_one_up_to_the_ceiling(ok):
    assert check_max_depth(ok) == ok


@pytest.mark.parametrize("bad", [0, 4, -1, True, 2.0, "2", None])
def test_max_depth_refuses_anything_else(bad):
    with pytest.raises(ValueError):
        check_max_depth(bad)
