# ragleap-security 0.1.0: threat model

Status: first version. It covers only what 0.1.0 contains. Anything not listed as defended is not defended. This library has had no independent security review.

## Scope of 0.1.0

Four modules: `scope` (tenant scopes), `audit` (hash-chained log), `secrets` (secret wrapper and redaction), `limits` (input limits). Standard library only. No store uses these yet; ragleap-memory (#900) is the first planned consumer.

## Threats

| # | Threat | What 0.1.0 does | Backed by | Not defended |
|---|--------|-----------------|-----------|--------------|
| 1 | One tenant reads or writes another tenant's data because a scope is missing, forged or ambiguous | `Scope` is immutable and validated; `key` is unambiguous; `covers` and `require_scope` accept only an exact `Scope` (no strings, dicts or subclasses) | `tests/test_scope.py`; 7 mutations in `scripts/mutation_check.py` | A store that never calls `require_scope`, or never filters by scope, is not protected. No store exists yet, so tenant isolation as a whole is **not verified**. |
| 2 | A secret is printed, logged, pickled or serialized by accident | `SecretStr` masks `str`, `repr`, `format` and f-strings, refuses pickle and JSON, is unhashable, compares in constant time; `from_env` reads by variable name and its errors never contain values; `redact` removes known values and common credential formats | `tests/test_secrets.py`; 9 mutations | Code that calls `reveal()` and logs the result. A secret in a format `redact` does not know (it is a heuristic with false negatives). Secrets in process memory, swap or core dumps. Other processes of the same user reading the environment. |
| 3 | Someone edits, deletes, reorders or inserts a record in the audit log | `verify()` detects it through sequence numbers, chain links and SHA-256 hashes; appends fail closed on a corrupt or incomplete log; the log file is created with mode 0600 (the lock file too, which is not mutation-checked) | `tests/test_audit.py`; 6 mutations | Cutting records off the END of the log is not detected unless you keep the last hash or count outside the log and pass it as an anchor. Someone who can rewrite the whole file and recompute every hash is not detected (the tests pin both limitations). Deleting the file. A trusted writer that records false events. Timestamps are not trusted. |
| 4 | A forged or malformed audit record (log injection) | Event names are restricted; records are single-line canonical JSON with ASCII escaping; size is capped at 65,536 bytes; `SecretStr` values are written as `[REDACTED]` | `tests/test_audit.py`; 2 mutations | Secrets that are not wrapped in `SecretStr` are written as given. Callers must not put secrets in audit data. |
| 5 | Hostile input exhausts memory or CPU | `check_size`, `check_json_shape` (iterative, so no recursion crash), `bounded_read`, cooperative `Deadline`; `redact` has a length cap and was timed on four hostile inputs | `tests/test_limits.py`, `tests/test_secrets.py`; 6 mutations | Limits only apply where a caller invokes them. `Deadline` does not interrupt running code. |
| 6 | Concurrent writers corrupt the audit chain | An in-process lock and, on POSIX, a file lock | Thread test (8 threads, 200 records) and process test (4 processes, 80 records) | Not mutation-checked (race tests are probabilistic). Windows multi-process, network filesystems and Python versions other than those tested are **not verified**. |

## Not covered in 0.1.0

Encryption at rest, an SSRF-safe HTTP helper, a policy engine, secret and PII detection for outputs, a red-team harness, prompt-injection defences (the taint rule lives in ragleap-agents), supply-chain controls, and independent review. These are planned in #899 and are not claimed here.

## How this document is checked

`python scripts/mutation_check.py` breaks one protection at a time in a temporary copy and requires a test to fail. All 30 listed mutations were killed when this version was written. A killed mutation shows the protection is exercised by a test; it does not show the protection is sufficient.
