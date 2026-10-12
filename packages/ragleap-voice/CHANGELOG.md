# Changelog

All notable changes to `ragleap-voice` are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added
- `ragleap-voice models pull NAME` (Hugging Face only: HTTPS, host allowlist, manual redirect validation, token sent only on the first request, per-file size and SHA-256 checks in a staging directory, disk-space check, offline mode) and `models lock NAME` (maintainer tool). Tested against a local fake server only.
- Lock files (`locks/<model>.json`: path, size and SHA-256 per file) with strict validation, a cache layout, and `ragleap-voice models verify NAME` (offline). `models check` now requires a matching lock for every verified or default entry. No download command yet.
- Model manifest loader (`ragleap_voice.manifest`), a strict TOML subset reader for Python 3.10 (`ragleap_voice._toml`) and a read-only `ragleap-voice models list|show|check` command line. No download command yet.
- Package scaffold, licence allowlist, `models.toml` manifest schema and CI licence test.
- `ragleap_voice.bench`: WER/CER metrics with a shared normalizer, CSV test manifest with licence checks, STT runner that records raw CSV/JSON results with environment metadata.
