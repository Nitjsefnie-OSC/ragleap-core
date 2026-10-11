# ragleap-voice

Open-source (MIT), local-first speech-to-text and text-to-speech, with Indian
languages as a priority.

**Status: pre-alpha, nothing is released.** The items below are planned, not available.

- Planned: STT and TTS engines as optional extras, model manager with pinned hashes,
  streaming, Indic-language quality work, consented voice profiles, emotion control.
- Available now: the licence manifest (`models.toml`) and the CI check that enforces
  the licence policy.

No performance or "better than X" claim will be made without a reproducible
benchmark in `benchmarks/voice/`.

Policy: the core package uses the Python standard library only. No paid API is
required or the default. Models are downloaded, never vendored. See `THIRD_PARTY_NOTICES.md`.
