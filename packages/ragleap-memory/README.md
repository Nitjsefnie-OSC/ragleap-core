# ragleap-memory

Durable, tenant-scoped long-term memory for LLM applications. Alpha. **Not independently audited**: see `docs/threat-model.md` for exactly what is and is not defended. Single-tenant use is simply one fixed `Scope`.

## What is in 0.1.0

- `SQLiteStore`: one SQLite file (or memory), FTS5 keyword search, no server. Needs SQLite built with FTS5; the store refuses to start without it.
- Every call takes a `Scope` (from ragleap-security) and is filtered by it inside the SQL. A tenant-wide scope sees its whole tenant; a narrower scope sees only its own subject, agent and session.
- Typed entries (`episode`, `fact`, `summary`) with a trust label (`untrusted`, `model`, `owner`). New entries default to `untrusted`.
- `supersede` for facts that change (history is kept), `forget`, `export`, `erase` (removes the text from the file), `sweep_expired`, and an optional `AuditLog` that records operations without entry text.

```python
from ragleap_memory import SQLiteStore
from ragleap_security import Scope

store = SQLiteStore("memory.db")
alice = Scope("acme", subject="alice")

old = store.add(alice, "Alice prefers email", trust="owner")
new = store.supersede(alice, old.id, "Alice prefers phone calls", trust="owner")

for hit in store.search(alice, "how should we contact alice", k=3, min_trust="model"):
    print(hit.entry.trust, hit.entry.text)
```

The store labels trust but does not decide what to do with retrieved text. A consumer that puts memory into a prompt must treat anything below `owner` as untrusted input.

## Verifying it yourself

```
pip install -e ../ragleap-security -e ".[test]"
pytest
python scripts/mutation_check.py   # breaks one protection at a time; every mutation must be killed
```

## Not in 0.1.0

Embeddings and vector search, consolidation and retention policies, importance-based ranking, Postgres, encryption at rest, a review queue and the ragleap-agents adapter are planned (issue #900). Search quality has not been measured on any benchmark.
