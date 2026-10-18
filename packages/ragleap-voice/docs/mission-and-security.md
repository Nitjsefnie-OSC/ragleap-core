# ragleap-voice: mission, vision and security model (draft)

Status: draft for the maintainer's review. Evidence tags: [verified] seen in code, tests or CI; [plan] intention, not built;
[unverified] believed but not checked. Nothing here is a promise of fitness for any purpose. ragleap-voice is pre-alpha.

## 1. Mission

The best open, local, multilingual voice stack for business agents, covering Indian, Asian, African, European,
North American and South American languages as far as open models allow. MIT code, only allowlisted model licences in the
default path, no paid API in the default path, emotion control and consented custom voices. [plan]

Motto (proposal, the maintainer decides): "Open, local, verified speech for everyone."

## 2. Principles

1. Independent: no paid cloud service in the default path, no single provider required. [plan for engines; verified for the model manager]
2. Open: MIT code; every model's licence recorded and checked at its source. [verified for the manifest rules]
3. Private by default: inference runs on the user's machine; nothing is sent anywhere. [plan: no engines exist in 0.0.1]
4. Honest: no claim without a reproducible benchmark; negative results are published. [verified policy in benchmarks/voice/README.md]
5. Free to run locally. Hosting for other people costs money, and we say so. 

## 3. Who it is for

| Audience | What they need | State today |
|---|---|---|
| Organisations with tight budgets | no per-minute fees, runs on their own hardware | [plan] engines are not in a release yet |
| Banks, public sector, private research institutes | no data leaving the site, offline operation, reviewable supply chain, audit evidence | model downloads are verified [verified]; offline loading is a design [plan]; no security review has happened |
| Security teams | known threats, signed and reproducible releases, SBOM, a disclosure process | partly, see section 5 |
| Contributors with GPUs | a safe way to train and share models and voices | [plan] registry and consent store are designs |

ragleap-voice is not ready for regulated or confidential production use. A pilot would run on the organisation's own
machines, offline, under its own security and legal review.

## 4. Threat model (what we try to prevent)

| Threat | Mitigation | State |
|---|---|---|
| Tampered or swapped model files | pinned revision, size and SHA-256 per file, staging directory, verify before install | [verified] |
| Code execution through model files (pickle) | verified entries may not list pickle-capable files; one closed exception (CTranslate2 .bin) with a header check | [verified] |
| Malicious downloads or redirects | HTTPS only, host allowlist, manual redirect validation, URLs never printed | [verified] |
| Token leakage | token sent only to huggingface.co, never after a redirect left it, never printed; tests use no secret-looking literals | [verified] |
| Non-allowlisted or restrictive licences | manifest validation in CI | [verified] |
| Model-supplied code at load time (trust_remote_code) | engines that need it run in an isolated worker with no token and no network | [plan]; the Colab demo does this by hand |
| Silent fallback to a hosted service that receives audio | no fallback; cloud adapters only when named, never chosen by auto | [plan] |
| Personal data in logs | no audio, transcripts or phone numbers logged by default | [plan]; the older core voice channel does not meet this |
| Cloning someone's voice without consent | consent record, deletion path, no public figures | [verified in the Colab demo only]; the real consent store is a design (#763) |
| Unverified library code (for example parler-tts from GitHub) | pin a commit and lock it | [plan]; a gap today |

Not covered: a compromised Hugging Face account that publishes a bad revision before we pin it (a pinned hash only proves
we got what we reviewed, not that it is trustworthy); a parser bug in a native library reading a model file; side channels.

## 5. Enterprise checklist

| Item | State |
|---|---|
| MIT licence file, third-party notices | [verified] |
| Zero runtime dependencies in 0.0.1 | [verified] |
| PyPI trusted publishing (no stored password), tag-only releases | [verified] |
| CodeQL, dependency and image scanning, secret scan in CI | [verified for the repository] |
| Private vulnerability reporting (SECURITY.md) | [verified at repository level] |
| CODEOWNERS on workflows, models.toml, locks, download code | [verified] visibility only |
| SBOM for ragleap-voice | [plan]; the repository's SBOM job covers another package only |
| Signed releases and provenance attestations | [unverified] not set up |
| Reproducible builds | [plan] |
| Air-gapped install guide, tested by someone outside the project | [plan] |
| Independent security review before any "enterprise" wording | [plan] |
| Legal review (DPDP, training-data licences, the always-on watermark of one engine, GPL espeak-ng isolation) | [plan] |
| Latency and accuracy on telephone and noisy audio | [plan] not measured |

## 6. What we may say today

Allowed: "open, local, MIT; no paid API in the default path; models are licence-checked, pinned and hash-verified before use;
pre-alpha." Not allowed until evidence exists: "bank-ready", "enterprise-grade", "secure", "private" without the
scope of the claim, "better than" any named service, or a language list that is not the coverage matrix.
