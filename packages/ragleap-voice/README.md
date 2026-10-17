# ragleap-voice

Open-source (MIT), local-first speech tooling, with Indian languages as a priority.

**Status: pre-alpha. Version 0.0.1 is the model-management layer only. There are no speech engines in this release: you cannot transcribe or synthesize audio with this package yet.**

## What works today

A command line and a small standard-library-only Python core (no runtime dependencies, Python 3.10 or newer) for finding, locking, downloading and verifying speech models safely:

    pip install ragleap-voice
    uv pip install ragleap-voice
    uvx ragleap-voice models list
    ragleap-voice models list
    ragleap-voice models show indic-parler-tts
    ragleap-voice models check

- `models list`, `show` and `check` read a manifest of candidate models with their licences, pinned revisions and status. Every entry is currently `unverified`: a research lead, not an endorsement. None is a default.
- Lock files record the size and SHA-256 of every file at a pinned revision. `models verify` checks a cache folder against them (offline, read-only). `models check` rejects verified or default entries that lack a matching lock, use licences outside the allowlist, or list pickle-capable files (formats that can run code when loaded).
- `models pull NAME` downloads from Hugging Face only: HTTPS, a host allowlist, and the access token (`HF_TOKEN`) is sent only to huggingface.co. Every file is checked against its lock before anything enters the cache, and `--offline` makes no network calls. Entries can declare dependencies, which are pulled first.
- `models lock NAME` is a maintainer tool that builds a lock by downloading and hashing every file.
- Two entries are locked so far: `indic-parler-tts` (a gated Hugging Face model: accept its conditions on the website and set `HF_TOKEN`) and its tokenizer dependency `flan-t5-large-tokenizer`. Both are pinned but have not had a human review, so pulling them needs `--allow-unverified`.

Nothing in the package uses the network unless you run `models pull` or `models lock`.

## Measurements

Reproducible benchmarks with their limits are published at https://github.com/antonyrag/ragleap-core/tree/main/benchmarks/voice. They use small samples of read speech on one GPU. The WER/CER helper can optionally normalize English (`numbers=True`) or Turkish (`numbers="tr"`) cardinal-number words; it is off by default and has not been applied to the published tables. Other language strings raise ValueError rather than falling back to English. In those tests an open Indian-language recogniser (IndicConformer) had clearly lower word error than Whisper large-v3 on Hindi, Tamil, Telugu, Malayalam and Kannada. Naturalness, emotion quality and comparisons with commercial services have not been measured, and this project makes no claim about them.

## Planned, not available

A speech-to-text and text-to-speech API with engines, streaming, voice profiles with a consent record, emotion and style control, a registry of community-trained models, and more languages.

## Licence

MIT. Models are separate downloads with their own licences, listed in the manifest and in https://github.com/antonyrag/ragleap-core/blob/main/packages/ragleap-voice/THIRD_PARTY_NOTICES.md

Source and issues: https://github.com/antonyrag/ragleap-core/tree/main/packages/ragleap-voice
