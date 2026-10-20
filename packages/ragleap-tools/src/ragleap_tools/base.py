"""
ragleap_tools.base

Core Tool/ToolResult abstraction every tool implementation in this
package uses. Deliberately minimal - a name, a description, a JSON
Schema for parameters (the OpenAI/Gemini function-calling convention,
so no adapter layer is needed for either provider), and a handler
callable.

v0.5.0 adds ToolError (an expected failure with a message that is safe to
show the model), an optional Tool.metadata dict, and to_anthropic_schema().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


class ToolError(Exception):
    """Raise this inside a tool function for an EXPECTED failure (file not
    found, quota exceeded, bad business input). The decorator and Toolkit turn
    it into ToolResult(success=False, error=<your message>), so write a
    message that is safe to show the model. Any other exception is treated as
    unexpected: only its type name reaches the model and the detail goes to the
    "ragleap_tools" logger."""


@dataclass
class ToolResult:
    """Result of calling a tool's handler.

    success=False + error=<message> on any failure - handlers should
    never raise for expected failure modes (bad input, file not found,
    etc.); they should catch and return a ToolResult so a caller's
    tool-calling loop can feed a clean error back to the LLM instead of
    crashing. Handlers MAY still raise for genuinely unexpected
    programming errors - that's a real bug, not user input to explain
    to the model.
    """

    success: bool
    result: Any = None
    error: Optional[str] = None


@dataclass
class Tool:
    """A single callable tool with an OpenAI/Gemini-compatible schema.

    parameters: a JSON Schema object (the same shape both OpenAI's
    `tools=[{"type": "function", "function": {...}}]` and Gemini's
    `FunctionDeclaration` expect for their own `parameters` field) -
    e.g. {"type": "object", "properties": {...}, "required": [...]}.

    metadata: free-form JSON-able facts about the tool for the caller's own
    policy code (for example {"read_only": True}). It is never sent to a
    model provider and nothing in this package acts on it. Treat metadata that
    came from a remote server as untrusted.

    handler: called with the tool call's arguments as keyword
    arguments (already parsed from whatever JSON the model returned -
    parsing that JSON is the caller's responsibility, not this
    package's). Must return a ToolResult, never raise for expected
    failure modes (see ToolResult's docstring).
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., ToolResult]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_openai_schema(self) -> Dict[str, Any]:
        """Returns the {"type": "function", "function": {...}} shape
        OpenAI's `tools=` parameter expects."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_gemini_schema(self) -> Dict[str, Any]:
        """Returns the shape google-genai's FunctionDeclaration expects
        (name/description/parameters, same JSON Schema convention)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Returns the shape Anthropic's Messages API `tools=` parameter
        expects (name/description/input_schema)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def call(self, /, **kwargs: Any) -> ToolResult:
        """Invokes the handler with the given keyword arguments.

        self is positional-only, so a tool argument literally named
        "self" (a model can choose any argument name) reaches the
        handler instead of raising TypeError."""
        return self.handler(**kwargs)
