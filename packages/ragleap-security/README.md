# ragleap-security

Small, auditable security primitives for the ragleap libraries. Standard library only. Alpha. **Not independently audited**: see `docs/threat-model.md` for exactly what is and is not defended.

## What is in 0.1.0

- `Scope`: an immutable tenant scope (tenant, subject, agent, session) with an unambiguous key, `covers`, `narrow` and `require_scope`, so stores can refuse to work without one.
- `AuditLog`: an append-only JSON Lines log with a SHA-256 hash chain and `verify()`. Tamper-evident, not tamper-proof (see the threat model).
- `SecretStr`, `from_env`, `redact`: secrets that do not print themselves, read from the environment by name, and a heuristic redactor for logs.
- `check_size`, `check_json_shape`, `bounded_read`, `Deadline`: hard limits for untrusted input.

```python
from ragleap_security import AuditLog, Scope, SecretStr, from_env, redact

scope = Scope("acme", subject="alice")
log = AuditLog("audit.jsonl")
log.append("login.ok", {"user": "alice", "token": SecretStr("s3cr3t-token")}, scope)
assert log.verify().ok
print(redact("Authorization: Bearer abcdef123456"))
```

## Verifying it yourself

```
pip install -e ".[test]"
pytest
python scripts/mutation_check.py   # breaks one protection at a time; every mutation must be killed
```

## Not in 0.1.0

Encryption, an SSRF-safe HTTP helper, a policy engine, output detectors and a red-team harness are planned (issue #899) and not available yet.
