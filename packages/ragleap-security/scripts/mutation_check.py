#!/usr/bin/env python3
"""Mutation check for ragleap-security (repository only, not part of the installed package).

For each mutation below it copies the package to a temp directory, breaks one protection in the
copy, and runs the test suite. A mutation is KILLED if a test fails, SURVIVED if every test still
passes (meaning that protection is not really tested). The real source is never modified.

  python scripts/mutation_check.py

Exit code 0 only if the unmodified suite passes and every mutation is killed. Run from the package
directory. Not covered, by design: the cross-process and in-process locks (their race tests are
probabilistic, so a surviving mutant there would prove nothing either way)."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
S, A, K, L = "src/ragleap_security/scope.py", "src/ragleap_security/audit.py", "src/ragleap_security/secrets.py", "src/ragleap_security/limits.py"

# (name, [(file, old, new), ...]) ; each old string must occur exactly once in its file
MUTATIONS = [
    ("scope: key separator removed", [(S, 'return "/".join(f"{f}=', 'return "".join(f"{f}=')]),
    ("scope: '/' allowed in parts", [(S, "[A-Za-z0-9_.:@-]{0,127}", "[A-Za-z0-9_.:@/-]{0,127}")]),
    ("scope: covers ignores tenant", [(S, "if self.tenant != other.tenant:", "if False:")]),
    ("scope: covers accepts subclasses", [(S, "if type(other) is not Scope:", "if not isinstance(other, Scope):")]),
    ("scope: require_scope accepts subclasses", [(S, "if type(value) is not Scope:", "if not isinstance(value, Scope):")]),
    ("scope: narrow may overwrite a set part", [(S, "if values[name] is not None and values[name] != value:", "if False:")]),
    ("scope: parse accepts a key without tenant", [(S, 'if "tenant" not in values:', "if False:")]),
    ("audit: record hash not checked", [(A, 'if not isinstance(rec["hash"], str) or not hmac.compare_digest(rec["hash"], _digest(body)):', 'if not isinstance(rec["hash"], str):')]),
    ("audit: sequence and chain link not checked", [(A, 'if rec["seq"] != count + 1 or isinstance(rec["seq"], bool):', "if False:"), (A, 'if rec["prev"] != prev:', "if False:")]),
    ("audit: anchor count not checked", [(A, "if expected_count is not None and expected_count != count:", "if False:")]),
    ("audit: anchor hash not checked", [(A, "if expected_last_hash is not None and not hmac.compare_digest(expected_last_hash, prev):", "if False:")]),
    ("audit: append after an incomplete record", [(A, 'if not tail.endswith(b"\\n"):', "if False:")]),
    ("audit: record size cap removed", [(A, "if len(line) > MAX_RECORD_BYTES:", "if False:")]),
    ("audit: SecretStr written in clear", [(A, 'return "[REDACTED]"', "return o.reveal()")]),
    ("audit: log file made world-readable", [(A, "os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600", "os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644")]),
    ("secrets: str() reveals the value", [(K, 'def __str__(self) -> str:\n        return "**********"', "def __str__(self) -> str:\n        return self._v")]),
    ("secrets: format() reveals the value", [(K, 'def __format__(self, spec: str) -> str:\n        return "**********"', "def __format__(self, spec: str) -> str:\n        return self._v")]),
    ("secrets: pickling allowed", [(K, 'raise TypeError("SecretStr cannot be pickled")', "return (SecretStr, (self._v,))")]),
    ("secrets: exact-value redaction off", [(K, "if isinstance(v, str) and len(v) >= MIN_REDACT_LEN:", "if False:")]),
    ("secrets: short values redacted", [(K, "len(v) >= MIN_REDACT_LEN", "len(v) >= 1")]),
    ("secrets: sk- keys not redacted", [(K, '(re.compile(r"\\bsk-[A-Za-z0-9_-]{16,200}"), MASK),', "")]),
    ("secrets: AWS keys not redacted", [(K, '(re.compile(r"\\bAKIA[0-9A-Z]{16}\\b"), MASK),', "")]),
    ("secrets: private keys not redacted", [(K, '.{0,8000}?-----END', ".{0,0}?-----END")]),
    ("secrets: redact length cap removed", [(K, "if len(text) > max_chars:", "if False:")]),
    ("limits: size boundary off by one", [(L, "if n > max_bytes:", "if n >= max_bytes:")]),
    ("limits: size counted in characters", [(L, 'n = len(data.encode("utf-8", "surrogatepass"))', "n = len(data)")]),
    ("limits: bounded_read cannot see excess", [(L, "fp.read(max_bytes + 1)", "fp.read(max_bytes)")]),
    ("limits: depth not checked", [(L, "if depth > max_depth:", "if False:")]),
    ("limits: node count not checked", [(L, "if nodes > max_nodes:", "if False:")]),
    ("limits: deadline never expires at the boundary", [(L, "return self._clock() >= self._end", "return self._clock() > self._end")]),
]


def run_tests(root: Path) -> bool:
    env = {"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", str(root / "tests")],
                       cwd=root, env={**env, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
    return r.returncode == 0


def main() -> int:
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        shutil.copytree(PKG, base, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "scripts"))
        if not run_tests(base):
            print("The unmodified test suite fails; fix that first.")
            return 2
        print("baseline: tests pass")
        for i, (name, edits) in enumerate(MUTATIONS):
            work = Path(tmp) / f"m{i}"
            shutil.copytree(base, work)
            for rel, old, new in edits:
                p = work / rel
                text = p.read_text()
                if text.count(old) != 1:
                    print(f"ERROR  {name}: anchor not found exactly once in {rel}")
                    return 2
                p.write_text(text.replace(old, new))
            killed = not run_tests(work)
            print(("KILLED   " if killed else "SURVIVED ") + name)
            if not killed:
                survivors.append(name)
            shutil.rmtree(work)
    print(f"\n{len(MUTATIONS) - len(survivors)} of {len(MUTATIONS)} mutations killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
