# Tool authoring and safe dispatch (ragleap-tools v0.5.0)

## Problem

Two things are hard today for someone using `ragleap-tools` in their own
tool-calling code.

1. **Writing a custom tool** means building a `Tool` by hand: a name, a
   description, a hand-written JSON Schema and a handler that takes keyword
   arguments. Most people just want to write a function.
2. **Dispatching a model's call** is unprotected. The model supplies the tool
   name and the arguments, and `Tool.call(**kwargs)` passes them straight to
   the handler. A missing, extra or mistyped argument raises `TypeError` (or
   something worse) inside the caller's loop, an unknown tool name is a
   `KeyError`, and nothing bounds the size of the argument JSON.

## Design

Standard library only, no new dependency, no change to how the existing 12
tools or the provider tools behave.

- `ragleap_tools/_schema.py` - `validate_arguments(schema, arguments)` checks
  arguments against a small JSON Schema subset (type, enum, required,
  properties, additionalProperties, items, minItems/maxItems,
  minLength/maxLength, minimum/maximum) and returns the first problem as short
  text or `None`. Unknown top-level arguments are rejected whenever the schema
  declares properties, because a handler would raise `TypeError` for them.
  Booleans are not integers or numbers, NaN and infinity are rejected, nesting
  deeper than 20 levels is an error (never a `RecursionError`), and every
  model-supplied name echoed back is clipped and stripped of control
  characters. Also: `drop_null_optionals`, because models often send `null`
  for an optional argument they mean to omit, and the schema generator builds a
  `parameters` object from a function's signature and Google-style docstring.
- `ragleap_tools/decorator.py` - `@tool` (and `@tool(name=, description=,
  metadata=, expose_errors=)`) turns a type-annotated function into a `Tool`.
  The handler validates the arguments first, so the function is never called
  with a bad argument. It returns a `ToolResult` unchanged, wraps any other
  return value in `ToolResult(success=True, result=...)`, turns `ToolError`
  into a failed result carrying its message, and turns any other exception into
  `"<name> failed (<ExceptionType>)"` with the detail going to the
  `ragleap_tools` logger (`expose_errors=True` opts in to the message).
- `ragleap_tools/toolkit.py` - `Toolkit` is a named collection with
  `add`, `select(include, exclude, where)`, the three provider schema exports
  and `call(name, arguments)`. `call` accepts the provider's JSON string or an
  already parsed dict, bounds the JSON text (100,000 characters by default),
  and never raises: unknown tool, invalid or non-object JSON, schema
  mismatch, a `ToolError`, an unexpected exception and a non-`ToolResult`
  return all become a failed `ToolResult`.
- `base.py` - `ToolError`; an optional `Tool.metadata` dict (default empty,
  appended as the last dataclass field so four-argument construction still
  works; never sent to a provider and not acted on by this package); and
  `Tool.to_anthropic_schema()`.
- `default_toolkit()` - a new `Toolkit` of the 12 stateless tools.

Supported annotations: `str`, `int`, `float`, `bool`, `Optional[X]` (with a
default), `Literal[...]` of all str, all int or all bool, `list[X]`, `dict`,
`Any`. Anything else raises `ToolDefinitionError` when the function is
decorated (at import time), not when a model calls it.

## Rejected alternatives

- **A validation library (pydantic or jsonschema).** Both would end the
  zero-dependency property that makes this package easy to adopt and audit.
- **A class-based tool API.** More ceremony for the common case; the function
  is the unit people already write. `Tool` objects can still be built by hand.
- **Guessing unannotated parameters as strings.** Silent guesses produce wrong
  schemas; a missing annotation is a definition error with a clear message.
- **Optional parameters with no default.** Rejected with a message
  ("write x = None"), because the model could not tell whether to send it.
- **Validating inside `Tool.call` for every tool.** That would change the
  behavior of the existing tools. Validation runs in decorated handlers and in
  `Toolkit.call`; calling a built-in tool's own `.call` behaves as before.
- **Auto-labelling the built-in tools with metadata.** The right keys depend
  on how `ragleap-agents` consumes policy; a guessed vocabulary would be wrong
  twice. `Tool.metadata` is the hook; labels can follow once the consumer is
  confirmed.
- **Async functions.** Not supported yet; wrap the call in a sync function.

## Security notes

- The model controls the tool name, every argument name and every value. All
  of it is validated before a handler runs and clipped before it appears in
  an error message.
- Exception text stays out of results by default (only the exception type
  name), matching the package's constant-error principle; `ToolError`
  messages are written by the tool's author and are shown to the model, so
  they must be safe to show. Messages are whitespace-collapsed and capped at
  500 characters.
- The argument JSON is size-limited before parsing, and a JSON nesting bomb
  is caught as an ordinary failure.
- `Tool.metadata` from a remote source (for example an MCP server's tool
  annotations, in `ragleap-integrations`) is untrusted input and must only be
  used to make policy stricter.

## Limitations

- Sync functions only. `Dict` values and nested JSON Schema keywords outside
  the subset (for example `pattern`, `format`, `oneOf`) are not validated;
  the handler must still validate what the schema cannot express.
- Only `Optional[X]` unions are supported, not unions of several types;
  no `Enum`, dataclass or pydantic parameter types.
- `Toolkit.call` bounds the argument JSON but not how long a handler runs or
  how large its result is. A handler that blocks blocks the caller.
- A `Toolkit` is not safe to modify (`add`) from several threads at once.
- The generated schemas use the same shape as the built-in tools plus
  `default` and integer `enum`. No provider has been called with a generated
  schema.

## Verification status

- Verified: 162 new tests (362 in total) pass on Python 3.10 and 3.12; the
  built-in tools are exercised through the toolkit with one valid and one
  invalid call each; 89 deliberate breaks of the new code, all caught by the
  new tests (a ninetieth, a defensive copy with no observable effect, is
  equivalent and was not counted).
- Not verified: that OpenAI, Gemini or Anthropic accept the generated
  schemas in a live tool-calling request; behavior with any real model that
  sends `null` for optional arguments.
