#!/usr/bin/env python3
"""Mutation check for ragleap-memory (repository only, not part of the installed package).

For each mutation below it copies the package to a temp directory, breaks one protection in the
copy, and runs the test suite. A mutation is KILLED if a test fails, SURVIVED if every test still
passes (meaning that protection is not really tested). The real source is never modified.

  python scripts/mutation_check.py

Needs ragleap-security importable (installed, or on PYTHONPATH). Exit code 0 only if the unmodified
suite passes and every mutation is killed. Run from the package directory. A killed mutation shows a
protection is exercised by a test; it does not show the protection is sufficient."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
S = "src/ragleap_memory/sqlite_store.py"

# (name, [(file, old, new), ...]) ; each old string must occur exactly once in its file
MUTATIONS = [
    ("scope clause ignores the tenant", [(S, 'parts, params = [f"{p}tenant = ?"], [scope.tenant]', 'parts, params = ["1 = 1"], []')]),
    ("scope clause ignores narrower parts", [(S, "        if v is not None:\n            parts.append(", "        if False:\n            parts.append(")]),
    ("get checks ids but not the scope", [(S, 'row = db.execute(f"SELECT * FROM memories WHERE id = ? AND {clause}", [entry_id, *params]).fetchone()', 'row = db.execute("SELECT * FROM memories WHERE id = ?", [entry_id]).fetchone()')]),
    ("search drops the scope condition", [(S, 'f" WHERE memories_fts MATCH ? AND {clause}"', 'f" WHERE memories_fts MATCH ? AND 1 = 1"'), (S, "args: list = [match, *params, *kinds, *trusts]", "args: list = [match, *kinds, *trusts]")]),
    ("forget deletes by id only", [(S, 'n = db.execute(f"DELETE FROM memories WHERE id IN ({\',\'.join(\'?\' * len(ids))}) AND {clause}",\n                           [*ids, *params]).rowcount', 'n = db.execute(f"DELETE FROM memories WHERE id IN ({\',\'.join(\'?\' * len(ids))})",\n                           [*ids]).rowcount')]),
    ("erase deletes everything", [(S, 'n = db.execute(f"DELETE FROM memories WHERE {clause}", params).rowcount\n            self._log("memory.erase"', 'n = db.execute("DELETE FROM memories").rowcount\n            self._log("memory.erase"')]),
    ("sweep ignores the scope", [(S, 'n = db.execute(f"DELETE FROM memories WHERE {clause} AND expires_at IS NOT NULL AND expires_at <= ?",\n                           [*params, _iso(self._clock())]).rowcount', 'n = db.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",\n                           [_iso(self._clock())]).rowcount')]),
    ("export ignores the scope", [(S, 'rows = db.execute(f"SELECT * FROM memories WHERE {clause} ORDER BY created_at, id", params).fetchall()', 'rows = db.execute("SELECT * FROM memories ORDER BY created_at, id").fetchall()')]),
    ("count ignores the scope", [(S, 'return self._db.execute(f"SELECT COUNT(*) FROM memories WHERE {clause}", params).fetchone()[0]', 'return self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]')]),
    ("derived_from not checked against the scope", [(S, "            for d in derived:\n                self._visible(db, scope, d)\n", "            for d in derived:\n                pass\n")]),
    ("supersede does not check the scope", [(S, "            old = self._visible(db, scope, old_id)\n", '            old = db.execute("SELECT * FROM memories WHERE id = ?", [old_id]).fetchone()\n            if old is None:\n                raise NotFoundError("no such entry")\n')]),
    ("double supersede allowed", [(S, 'if old["superseded_by"] is not None:', "if False:")]),
    ("default trust raised to owner", [(S, 'source: str = "api", trust: str = "untrusted",\n            importance: float = 0.5', 'source: str = "api", trust: str = "owner",\n            importance: float = 0.5')]),
    ("min_trust ignored", [(S, "trusts = [t for t in TRUSTS if trust_rank(t) >= trust_rank(min_trust)]", "trusts = list(TRUSTS)")]),
    ("expired entries not hidden", [(S, "        if not include_expired:\n            sql +=", "        if False:\n            sql +=")]),
    ("superseded entries not hidden", [(S, "        if not include_superseded:\n            sql +=", "        if False:\n            sql +=")]),
    ("query words not quoted", [(S, """match = " OR ".join('"%s"' % t for t in tokens)""", """match = " OR ".join(tokens)""")]),
    ("query size not limited", [(S, 'check_size(query, 1000, "query")', "pass")]),
    ("result cap removed", [(S, "k = min(k, self.max_results)", "pass")]),
    ("text size not limited", [(S, "check_size(text, self.max_text_bytes, \"text\")", "pass")]),
    ("metadata shape not limited", [(S, "check_json_shape(metadata, max_depth=8, max_nodes=1000)", "pass")]),
    ("audit written after the transaction (not rolled back)", [(S, "        if self._audit is not None:  # inside the transaction: if the audit write fails, the change is rolled back\n            self._audit.append(event, data, scope)", "        pass")]),
    ("secure_delete explicitly off", [(S, 'self._db.execute("PRAGMA secure_delete = ON")', 'self._db.execute("PRAGMA secure_delete = OFF")')]),
    ("erase does not compact", [(S, "            self._log(\"memory.erase\", scope, {\"count\": n})\n        self.compact()", "            self._log(\"memory.erase\", scope, {\"count\": n})")]),
    ("database file not private", [(S, "os.O_WRONLY | os.O_CREAT, 0o600", "os.O_WRONLY | os.O_CREAT, 0o644")]),
    ("newer schema accepted", [(S, "if version > SCHEMA_VERSION:", "if False:")]),
    ("failed write not rolled back", [(S, '                self._db.execute("ROLLBACK")\n                raise', "                raise")]),
]


def run_tests(root: Path) -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=os.pathsep.join(p for p in (str(root / "src"), os.environ.get("PYTHONPATH", "")) if p))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", str(root / "tests")],
                       cwd=root, env=env, capture_output=True, text=True)
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
