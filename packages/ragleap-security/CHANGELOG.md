# Changelog

All notable changes to `ragleap-security` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - unreleased

First version (design: #899). Nothing existed before, so there are no behaviour changes.

### Added

- `Scope`, `ScopeError`, `require_scope`: immutable tenant scopes with an unambiguous key.
- `AuditLog`, `verify`, `VerifyResult`, `AuditError`: a hash-chained, append-only JSONL audit log.
- `SecretStr`, `from_env`, `redact`, `SecretError`: secret handling and heuristic redaction.
- `check_size`, `check_json_shape`, `bounded_read`, `Deadline`, `LimitError`: hard input limits.
- `docs/threat-model.md` and `scripts/mutation_check.py` (30 mutations).

### Verified

- 101 tests pass on Python 3.10 (the VPS) and on Python 3.12 (the author's sandbox). All 30 mutations are killed on Python 3.10 and 3.12.
- The CI test job passes on Python 3.10, 3.11 and 3.12 (PR #907).

### Not verified

- Windows, network filesystems.
- Tenant isolation end to end: no store uses `Scope` yet.
- The cross-process and in-process locks under adversarial timing (the race tests are probabilistic).
- No independent security review has been done.
