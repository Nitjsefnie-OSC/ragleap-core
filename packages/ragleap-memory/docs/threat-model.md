# ragleap-memory 0.1.0: threat model

Status: first version. It covers only what 0.1.0 contains. Anything not listed as defended is not defended. This library has had no independent security review.

## Scope of 0.1.0

`SQLiteStore`: durable memory in one SQLite file (or in memory) with FTS5 keyword search, typed entries with trust labels, supersession, per-scope export and erase, and an optional audit log. It uses `Scope`, `AuditLog` and the limits from ragleap-security 0.1.0. Nothing in `core/` or ragleap-rag uses it yet.

## Threats

| # | Threat | What 0.1.0 does | Backed by | Not defended |
|---|--------|-----------------|-----------|--------------|
| 1 | One tenant reads, changes or deletes another tenant's entries | Every operation requires an exact `Scope`. The scope is applied inside the SQL (tenant plus any narrower subject, agent and session). `derived_from` ids must be visible to the writer's scope. A missing entry and an invisible entry give the same error. | `tests/test_isolation.py`, `tests/test_add_validation.py`, `tests/test_lifecycle.py`; 11 mutations in `scripts/mutation_check.py` | The caller chooses the scope. The store cannot know whether a caller is entitled to it: authentication and mapping users to scopes belong to the application. Anyone who can read the database file or hold the store object bypasses it. A tenant-wide scope sees everything in its tenant by design. |
| 2 | Untrusted or poisoned text is later treated as trustworthy | Every entry carries a trust label (`untrusted`, `model`, `owner`); the default is the lowest; `min_trust` filters searches; derived entries record their sources. | `tests/test_search.py`, `tests/test_add_validation.py`; 2 mutations | Labels are only as honest as whoever writes them: a writer can claim `owner`. The store does not stop a consumer from putting retrieved text into a prompt as instructions. Defending against prompt injection through retrieved memory is the consumer's job (the ragleap-agents integration is planned). No content scanning. |
| 3 | A search query changes the query, or is used to exhaust resources | Queries are reduced to quoted words joined with OR, so operators are plain words; at most 32 words and 1,000 bytes; results are capped (default 50). | `tests/test_search.py`, `tests/test_isolation.py`; 3 mutations | A slow query inside these limits on a very large store. No timing has been measured. |
| 4 | Deleted text stays in the database file | `erase()` deletes, rewrites the full-text index, and checkpoints the journal; `secure_delete` is turned on explicitly. A byte-level test checks the text is gone from the file. | `tests/test_lifecycle.py`; 2 mutations | `forget()` leaves traces in the search index until `compact()` or `erase()` runs (a test pins this). Other SQLite builds, other operating systems, file system journals, SSD wear levelling, backups, snapshots and copies of the file are **not verified**. |
| 5 | A change happens without a record, or half-happens | The optional `AuditLog` is written inside the transaction, so a failing audit write rolls the change back; the log holds ids and counts, never entry text; any error rolls the whole write back. | `tests/test_durability.py`; 2 mutations | The audit log is optional and off by default. Reads (`get`, `search`, `count`) are not audited, only `export`. The log is tamper-evident, not tamper-proof (see the ragleap-security threat model). |
| 6 | Oversized input exhausts memory or disk | Text is capped at 8,192 bytes; metadata at 4,096 bytes, depth 8 and 1,000 values; `derived_from` at 100 ids; `forget` at 1,000 ids. | `tests/test_add_validation.py`; 2 mutations | No cap on the number of entries per tenant or on the file size: a tenant can fill the disk. No rate limiting. |
| 7 | The database file is readable by other local users | The file is created with mode 0600. Checked by hand on Linux, SQLite's `-wal` and `-shm` files were 0600 too; the test checks only the main file. | `tests/test_durability.py`; 1 mutation | A file that already exists keeps its permissions. No encryption at rest (planned with ragleap-security `crypto`, not in 0.1.0). Backups. |
| 8 | A newer schema is opened by older code, or writers collide | A database with a newer schema version is refused; writes run in `BEGIN IMMEDIATE` transactions with WAL; threads share one locked connection. | `tests/test_durability.py` (8 threads, 200 writes); 1 mutation | Several processes writing the same file, network file systems and power-loss durability beyond SQLite's defaults are **not verified**. |
| 9 | An outdated or expired fact is used as if current | Expired and superseded entries are hidden from search unless asked; `supersede` links the new entry to the old one and refuses a second supersession. | `tests/test_search.py`, `tests/test_lifecycle.py`; 3 mutations | The store cannot know a fact is wrong. Two contradicting entries added with `add()` both stay current. |

## Not covered in 0.1.0

Encryption at rest, embeddings and vector search, consolidation, retention and decay beyond expiry, importance-based ranking (importance is stored but does not affect ranking yet), Postgres, a review queue, and the ragleap-agents adapter. Retrieval quality has not been measured on any benchmark.

Languages: search uses SQLite's `unicode61` tokenizer. Whole-word search is tested for Hindi, Tamil, Arabic and Chinese written with spaces. Chinese or Japanese text without spaces is not split into words. Words in Indic scripts are split at combining marks, so partial matches can be loose; precision has not been measured.

## How this document is checked

`python scripts/mutation_check.py` breaks one protection at a time in a temporary copy and requires a test to fail. All 27 listed mutations were killed when this version was written. A killed mutation shows a protection is exercised by a test; it does not show the protection is sufficient.
