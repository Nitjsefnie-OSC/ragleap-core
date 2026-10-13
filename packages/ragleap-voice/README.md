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
  new: tested against a local fake server and once end to end against the real service on an ungated
  model, and once on a gated one (Indic Parler-TTS).
  One lock file exists (indic-parler-tts, pinned but not yet reviewed), so `pull` works only for that
  gated model and only with `--allow-unverified` and an HF_TOKEN; every other model is refused.
  Manifest entries can declare `depends_on`: `pull` fetches dependencies first and `verify` checks them; a
  verified entry requires verified dependencies. No entry uses this yet.
- Planned, not available: everything else above (STT and TTS engines, streaming, cloning, emotion control).

No performance or "better than X" claim will be made without a reproducible
benchmark in `benchmarks/voice/`.

Policy: the core package uses the Python standard library only. No paid API is
required or the default. Models are downloaded, never vendored. See `THIRD_PARTY_NOTICES.md`.
