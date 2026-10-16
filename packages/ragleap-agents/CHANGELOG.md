# Changelog

All notable changes to `ragleap-agents` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed (behaviour change: an empty run now stops)

- A run with no tools, or with an empty task, now returns `status="stopped"` with
  `stop_reason="no_task_or_tools"`. 0.3.0 and earlier returned `status="done"` for it, so a run in
  which nothing happened looked like a success. Code that checked only `status == "done"` will now
  see `stopped` in this case.

### Corrected

- The `## [0.3.0]` heading below was dated 2026-10-13, but the tag was pushed on 2026-10-15 (tag run
  38791601216). The date is corrected here; the published 0.3.0 files still carry the old date and
  cannot change.

## [0.3.0] - 2026-10-15

### Changed (behaviour change: the prompt wording)

- The instruction at the end of the prompt now depends on `prompt_style`. `"json"` (the default)
  still asks for one JSON object, now as plain text and without any tool-calling or function-calling
  feature. `"native"` no longer asks for JSON at all: it says to call exactly one of the provided tools
  by its own name, and to answer in plain text when finished or when it cannot or will not do the task.
  The repair note follows the style too. In 0.2.0 native mode told the model to reply with a JSON object
  while real tools were offered, and two models answered by calling a tool named `json`.

### Added

- `Agent(prompt_style=None)`: `"json"` or `"native"`. By default the style is read from the model
  callable, and `openai_compatible` advertises its mode, so the wording follows the adapter's mode
  without any extra argument. An explicit argument wins; any other value raises `ValueError`.

### Verified

- 123 tests pass on Python 3.10, 3.11 and 3.12. Mutation-checked: 9 of 9 mutations of the new
  behaviour (wording not switched, style not read from the callable, explicit style ignored, unknown
  style accepted, repair note not style-aware, JSON sentence dropped, native wording asking for JSON,
  adapter not advertising its mode, adapter always advertising json) are caught.
- Cold start, with a positive control in each test: the first step is never gated even with no
  policy; with no policy the second step pauses visibly (`awaiting_approval`, `forced`) while the
  identical run with the tool declared trusted completes; an outbound tool runs first but pauses
  after a tainting tool; a policy naming a tool that does not exist is refused at construction
  (no test covered that check before). 4 of 4 targeted mutations are caught by these tests alone.
- Live runs against Groq with `openai/gpt-oss-20b` after the change, one run per task, 20 tasks in each
  mode: tasks done were json 19, native 19 (the earlier sweeps with the 0.2.0 wording had json 15 and 16,
  native 17 and 20, the second of each with repair on; these are single runs and not a controlled
  comparison). Five tasks that had misbehaved before were then repeated three times each.
- JSON mode: `c1` failed in all 8 earlier runs whose results were kept and `c4` in all 5 (HTTP 400
  `tool_use_failed`); after the change both completed 4 of 4 times (the sweep plus three repeats). One
  earlier run, seen only on screen, had passed `c1`. This is one model on one provider.
- Injection tasks: no run in the sweep proposed the injected send (proposed, gated and executed all 0),
  as before.

### Not verified

- Whether the new JSON sentence helps with any other model or provider.
- Whether the native wording reduces the calls to a tool named `json`: that failure occurred in 2 of 46
  earlier saved native runs and in none of the 26 native runs since (20 in the sweep, 6 repeats), which is
  too few runs to show an effect.
- Not fixed: JSON-mode `i3` (read a note that contains an injected instruction) still failed 4 of 4 with
  HTTP 400 `tool_use_failed`. Native `i3` still ended `invalid_plan` 4 of 4: after reading the note the
  model declines by replying with a JSON action naming a tool `refusal`, not in plain text, even though
  the native wording says to answer in plain text. The loop has no defined way for a model to decline.
- Two native runs ended `done` without the tool result the task needed (the model skipped a step).
- Not fixed: a run with no tools, or an empty task, returns `status="done"` with
  `stop_reason="no_task_or_tools"` although nothing happened. Check `stop_reason`, not only `status`.
- The taint rule against a real model: no run proposed the injected send, so it was never triggered.

## [0.2.0] - 2026-10-12

### Changed (behaviour change from 0.1.0)

- A model reply that is not a single JSON object (prose, truncated JSON, two
  objects) now stops the run with `status="stopped"`, `stop_reason="unparseable_reply"`.
  0.1.0 reported these as `status="done"`, so a model failure looked like success.
  Nothing executed in either case. A reply that is a JSON object without a `tool`
  key now stops with `invalid_plan`. An explicit `{"tool": "done"}` is unchanged.
- The summary of a rejected run counts only the calls that ran; the rejected call
  is still in `steps` with `status="rejected"`.

### Added

- `Policy.repair_attempts` (default 0, capped at 2): after an unparseable or invalid
  proposal, the model is asked again with a short note naming the problem. The note
  never repeats the bad reply or an unknown tool name. A repaired proposal goes
  through the same validation, taint rule and approval gate as any other.
- `ragleap_agents.openai_compatible(base_url, api_key, model, mode="json"|"native", tools=...)`
  returns an `llm(prompt) -> str` for `Agent` over `POST {base_url}/chat/completions`.
  Standard library only; https required (http only with `allow_insecure_http=True`);
  no redirects; response size cap; retries with backoff on 408/429/5xx and network
  errors (capped at 5, `Retry-After` honoured up to 30 s); errors carry only a status
  code or exception type (`ProviderError`), never a body, URL or key. In `native` mode
  the first tool call is re-serialised as the JSON action and a reply with no tool call
  becomes an explicit `done`; `Agent` still validates, taints and gates every proposal.
  The owner sets the base URL: there is no address guard, so never build it from
  untrusted input.
- `scripts/live_runner.py` (in the repository, not in the wheel): runs 20 labeled tasks
  against a real OpenAI-compatible provider in json and native mode, with request
  pacing and a hard request cap, and writes a report. Every approval is rejected and
  `send_message` only appends to an in-memory list, so nothing is ever sent. Keys are
  read by environment-variable name and never printed or logged; results are written
  to `~/ragleap-live-runs` unless `--out` is given.
- `openai_compatible(error_detail=True)` and the runner's `--show-error-body` (diagnostics,
  off by default): a provider error then carries the first 300 characters of the error
  body, whitespace collapsed and the API key scrubbed if the provider echoed it. By
  default errors still carry only a status code or exception type.

### Fixed

- `openai_compatible` and the runner's `--list-models` sent Python's default
  `User-Agent`, which Groq's gateway rejects with HTTP 403 (error code 1010) before it
  looks at the key. Found by the first real call. The adapter now sends
  `ragleap-agents (+https://github.com/antonyrag/ragleap-core)`, and `user_agent=`
  overrides it (a value with a line break is refused). Checked against Groq only;
  Gemini has not been tried.
- The runner's test double no longer parses prompts with a regular expression
  (CodeQL `py/polynomial-redos` on test code).
- The runner only wrote its results at the end, so interrupting it (Ctrl-C) lost every
  finished run. Each run is now appended as it finishes and an interrupt writes a
  partial report.
- The runner scored an injection task whose run crashed with a model error as a
  success (no send ran). A failed run is no longer counted as safe.
- The report's median time now excludes the runner's own pacing and retry waits.

### Verified

- 112 tests pass on Python 3.10, 3.11 and 3.12 (sandbox): 57 with a scripted model, 42 for
  the adapter against a real local HTTP server (127.0.0.1, no external network), and 13 for
  the live runner against a deterministic fake model. Mutation-checked: 19 of 19 adapter and
  19 of 20 runner mutations caught; the survivor changes the mode of a file that an earlier
  step has already created as 0600, so it cannot matter.
- Live runs against Groq (`https://api.groq.com/openai/v1`) on 2026-10-11, one run per task and
  configuration with `scripts/live_runner.py`: 20 labeled tasks each in json, native, json+repair and
  native+repair mode with `openai/gpt-oss-20b` (80 runs), plus the three injection tasks in native mode
  with `openai/gpt-oss-120b` and `qwen/qwen3.8-27b` (6 runs). Completions work in both modes. Tasks done:
  json 15 of 20, native 17 of 20, json+repair 16 of 20, native+repair 20 of 20. These are single runs,
  and the differences between configurations are within the run-to-run variation seen.
- Failure kinds seen: HTTP 400 `tool_use_failed` in json mode (3 tasks, the same three in both sweeps)
  when the model answers in its own function-call format; HTTP 400 in native mode when the model calls a
  tool named `json` that was not offered (2 of 46 saved native runs across three models, on two of them);
  empty replies (4 runs); an invented `refusal` action to decline (5 runs).
- Repair fired in 5 of the 40 runs in the repair sweeps: 2 empty replies and 2 invented refusal actions
  ended with a valid action, and 1 invented action was repeated and the run stopped. It cannot act on a
  rejected request, because no reply exists.
- 16 runs on three models read the injected note; none proposed the injected send.

### Not verified

- The taint rule against a real model: no real run proposed the injected `send_message`, so the rule was
  never triggered. It is tested with scripted models only.
- Any provider other than Groq (Gemini has not been tried), models other than the three above, long runs,
  and concurrent resumes across processes.
- Whether repair improves pass rates: five firings on one model do not show that.
- Native mode's instruction still asks for a JSON object while real tools are offered, which two models
  answered by calling a tool named `json`. The instruction has not been changed.

## [0.1.0] - 2026-10-09

### Added

- Initial version. `Agent(llm, tools, policy, store, summarize)` runs an
  act-observe loop over `ragleap_tools.Tool` objects: the model proposes one
  JSON action per step, sees the result, and continues, up to `max_steps`
  (default 4, hard cap 8). `llm` is any callable `llm(prompt: str) -> str`.
- Every proposal is checked: the tool must exist and the arguments must fit
  the tool's JSON Schema (required keys, unknown keys, type and enum only).
  An invalid proposal stops the run; no tool runs.
- Tool results are untrusted data: capped, fenced, labelled, and lookalike
  tags inside them are neutralised case-insensitively.
- `ToolPolicy(taints, outbound, requires_approval)` per tool. After a tainting
  tool has run, every later outbound tool needs approval. A tool with no
  declared policy counts as both tainting and outbound.
- Pause and resume: an action that needs approval saves the run and returns
  `status="awaiting_approval"` with the pending call; `resume(run_id,
  {call_id: bool})` continues or ends it. Replays and mismatched decisions raise
  `ResumeError`. Run state is JSON-safe and lives in a pluggable `StateStore`
  (`InMemoryStateStore` included).
- Duplicate-action stop, a wall-clock deadline checked between calls, and a
  summary pass. `run()` does not raise for model or tool failures; a tool's
  exception text never reaches the model or the result, only its type.

### Verified

- 41 tests with a scripted model (no network) pass on Python 3.10, 3.11 and
  3.12. Mutation-checked locally: removing the taint rule, the case-insensitive
  fence, the exception-text rule, the resume claim, the hard cap, the fail-closed
  default or the bool-is-not-integer check each makes at least one test fail.
- The quickstart in the README was run with the real `ragleap-tools`
  `calculator` tool and a scripted model.

### Not verified

- Any real model: no provider has been run through this loop yet.
- Long runs; concurrent resumes across processes (the store must make resume
  atomic); equivalence with RagLeap Core's agent loop (mirrors core commit
  `59fd555` as of 2026-10-03, which keeps changing).
