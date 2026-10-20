"""ragleap_agents.delegate - the building blocks of sub-agents (design: issue #827).

A child agent runs to completion inside one tool call of its parent, so its answer
reaches the parent as an ordinary, untrusted, fenced observation. This module holds
the parts that are pure validation and policy computation:

- delegate_policy(children): checks the children and returns the ToolPolicy to declare
  for the delegate tool in the parent's Policy. Everything fails closed: a child tool
  with no declared policy raises, an outbound child tool raises unless allow_outbound=True
  is passed explicitly, and the delegate tool is never outbound itself.
- Budget: how much delegation one run may use.
- check_max_depth: depth is 1 to MAX_DEPTH_CEILING.

A child cannot ask a human for approval (see the design issue), so a child tool that
would need approval is never run on a child's behalf.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ragleap_agents.agent import _NAME_RE, Agent, ToolPolicy

MAX_DEPTH_CEILING = 3


def _positive_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{what} must be an integer of at least 1")
    return value


@dataclass(frozen=True)
class Budget:
    """What one run may spend on delegation: how many delegate calls, and how many
    steps all its children may take together."""

    max_delegations: int = 4
    max_child_steps: int = 16

    def __post_init__(self) -> None:
        _positive_int(self.max_delegations, "max_delegations")
        _positive_int(self.max_child_steps, "max_child_steps")


def check_max_depth(max_depth: Any) -> int:
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= MAX_DEPTH_CEILING:
        raise ValueError(f"max_depth must be an integer from 1 to {MAX_DEPTH_CEILING}")
    return max_depth


def delegate_policy(children: Dict[str, Agent], *, allow_outbound: bool = False) -> ToolPolicy:
    """Validate the children and return the ToolPolicy to declare for their delegate tool.

    taints is True if any child tool can taint (a nested delegate tool counts by the policy
    declared for it in the child's Policy). outbound is always False: delegating is not itself
    an action on the outside world. Raises ValueError for anything unsafe or unclear."""
    if not isinstance(allow_outbound, bool):
        raise ValueError("allow_outbound must be True or False")
    if not isinstance(children, dict) or not children:
        raise ValueError("children must be a non-empty dict of name -> Agent")
    taints = False
    for name, child in children.items():
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(f"invalid child name {str(name)[:50]!r}: use 1-64 of A-Z a-z 0-9 _ . -")
        if not isinstance(child, Agent):
            raise ValueError(f"child {name!r} must be an Agent")
        for tool_name in child.tools:
            if tool_name not in child.policy.tools:
                raise ValueError(
                    f"child {name!r}: tool {tool_name!r} has no declared policy "
                    "(an undeclared tool is both tainting and outbound); declare it in the child's Policy")
            declared = child.policy.tools[tool_name]
            if declared.outbound and not allow_outbound:
                raise ValueError(
                    f"child {name!r}: tool {tool_name!r} is outbound; pass allow_outbound=True to allow it "
                    "(a child cannot ask for approval, so it stops instead of running it after a taint)")
            taints = taints or declared.taints
    return ToolPolicy(taints=taints, outbound=False, requires_approval=False)
