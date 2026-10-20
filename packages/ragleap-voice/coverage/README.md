# Language coverage matrix (data)

One row per language and engine, in `stt.csv` and `tts.csv`. Design: `docs/design/coverage-matrix.md`. `ragleap_voice.coverage` checks the files, and the test suite runs that check.

- `tier` 0: no open engine known (no such rows yet). 1: engine exists or the card claims the language, little or no measurement. 2: measured, reproducible by the scripts named in `evidence`. 3: reviewed by a second person (no such rows yet).
- Until the per-clip raw results are committed (`raw_committed` is `no` in every row today), tier 2 means reproducible by script and not independently reviewed.
- Text to speech rows are tier 1 even where a round-trip error is recorded: intelligibility is the only thing measured, and a tier 2 definition for speech output is still open.
- `engine` is a name from `models.toml`, or `candidate:NAME` for a model that is not in the manifest. Candidates are never used by automatic engine selection.
- Error values are percentages. `contamination` is filled when a model may have seen the test data.
- Every public statement about a language should come from a row here, with its tier.
