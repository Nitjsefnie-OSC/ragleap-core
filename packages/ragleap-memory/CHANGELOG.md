# Changelog

All notable changes to `ragleap-memory` are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - unreleased

First version (design: #900). It replaces an untracked prototype that was never committed, so there are no behaviour changes.

### Added

- `SQLiteStore`: durable memory in one SQLite file with FTS5 keyword search.
- `add`, `get`, `search`, `supersede`, `forget`, `export`, `erase`, `sweep_expired`, `compact`, `count`, all scoped by a ragleap-security `Scope` inside the SQL.
- Typed entries (`episode`, `fact`, `summary`) with trust labels (`untrusted` by default), expiry, and links to the entries they were derived from.
- Optional audit log (ids and counts only, written inside the transaction).
- `docs/threat-model.md` and `scripts/mutation_check.py` (27 mutations).

### Verified

- 89 tests pass on Python 3.10 (the VPS, SQLite 3.37.2) and on Python 3.12 (the author's sandbox). All 27 mutations are killed on Python 3.12.
- After `erase()`, a byte-level search of the database file and its journal finds no trace of the deleted text (tested on the two SQLite builds above).

### Not verified

- Python 3.11 and CI (the CI job is added with this package).
- Windows, network file systems, several processes writing one file, and power-loss durability.
- Retrieval quality: no benchmark has been run. Multilingual precision is unmeasured (whole-word search is tested for a few scripts).
- It depends on ragleap-security 0.1.0, which is merged but not yet published to PyPI, so this package cannot be installed from PyPI until that is released.
- No independent security review has been done.
