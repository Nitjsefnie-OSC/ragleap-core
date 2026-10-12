# ragleap-voice

Open-source (MIT), local-first speech-to-text and text-to-speech, with Indian
languages as a priority.

**Status: pre-alpha, nothing is released.** The items below are planned, not available.

- Planned: STT and TTS engines as optional extras, model manager with pinned hashes,
  streaming, Indic-language quality work, consented voice profiles, emotion control.
- Available now: the licence manifest (`models.toml`), the CI check that enforces the licence
  policy, and a read-only command line: `ragleap-voice models list|show|check|verify|pull|lock`. `pull` downloads from Hugging Face only
  and verifies size and SHA-256 of every file against a lock file before anything enters the cache
  (it also has an offline mode); `lock` is a maintainer tool that builds those lock files. `pull` is
  new and has so far been tested only against a local fake server, never against the real service.
  No lock files exist yet, so `pull` currently refuses every model.
- Planned, not available: everything else above (STT and TTS engines, streaming, cloning, emotion control).

No performance or "better than X" claim will be made without a reproducible
benchmark in `benchmarks/voice/`.

Policy: the core package uses the Python standard library only. No paid API is
required or the default. Models are downloaded, never vendored. See `THIRD_PARTY_NOTICES.md`.
