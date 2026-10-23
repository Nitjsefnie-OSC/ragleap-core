"""ragleap-security: small, auditable security primitives for the ragleap libraries.

Standard library only. Not independently audited. See docs/threat-model.md for what is and is not
defended."""
from ragleap_security.audit import GENESIS, AuditError, AuditLog, VerifyResult, verify
from ragleap_security.limits import Deadline, LimitError, bounded_read, check_json_shape, check_size
from ragleap_security.scope import Scope, ScopeError, require_scope
from ragleap_security.secrets import SecretError, SecretStr, from_env, redact

__version__ = "0.1.0"

__all__ = [
    "AuditError", "AuditLog", "Deadline", "GENESIS", "LimitError", "Scope", "ScopeError", "SecretError",
    "SecretStr", "VerifyResult", "__version__", "bounded_read", "check_json_shape", "check_size",
    "from_env", "redact", "require_scope", "verify",
]
