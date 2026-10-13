# Changelog

All notable changes to `ragleap-voice` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added
- First lock file: `locks/indic-parler-tts.json` (revision 660bc53c64ae, 10 files, 3.5 GiB, safetensors only), built and pulled end to end against the real gated Hugging Face repository. Pinned in `models.toml` but still `unverified` pending human review; the separate `google/flan-t5-large` repository its config loads at run time is not covered.
- Lock files for verified or default entries may not list pickle-capable files (.pt, .pth, .bin, .pkl, .pickle, .ckpt, .joblib, .dill): `models check` fails them, `models pull` refuses verified entries that do and warns for unverified ones, and `models lock` warns when its plan includes such files.
- Fix: `models pull` now sends the Hugging Face token on redirects that stay on huggingface.co (gated repositories answer with another huggingface.co URL), still never to another host and never again once a redirect has left huggingface.co.
- `ragleap-voice models pull NAME` (Hugging Face only: HTTPS, host allowlist, manual redirect validation, token sent only to huggingface.co (never to a CDN), per-file size and SHA-256 checks in a staging directory, disk-space check, offline mode) and `models lock NAME` (maintainer tool). Tested against a local fake server only.
- Lock files (`locks/<model>.json`: path, size and SHA-256 per file) with strict validation, a cache layout, and `ragleap-voice models verify NAME` (offline). `models check` now requires a matching lock for every verified or default entry. No download command yet.
- Model manifest loader (`ragleap_voice.manifest`), a strict TOML subset reader for Python 3.10 (`ragleap_voice._toml`) and a read-only `ragleap-voice models list|show|check` command line. No download command yet.
- Package scaffold, licence allowlist, `models.toml` manifest schema and CI licence test.
- `ragleap_voice.bench`: WER/CER metrics with a shared normalizer, CSV test manifest with licence checks, STT runner that records raw CSV/JSON results with environment metadata.
