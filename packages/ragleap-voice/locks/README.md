# Model lock files

One JSON file per model, named `<model>.json`, listing every file of that model at the pinned
revision: relative path, size in bytes and SHA-256. The `sha256` field of the model's entry in
`models.toml` is the SHA-256 of the lock's canonical form (sorted keys, compact separators), so
editing a lock without updating the manifest, or the other way round, fails `ragleap-voice models check`.

Format (schema 1):

    {"schema": 1, "model": "NAME", "revision": "PINNED-REVISION", "source_url": "https://...",
     "files": [{"path": "dir/file.bin", "size": 123, "sha256": "<64 lowercase hex>"}]}

Paths are relative POSIX paths without `..`, backslashes or unusual characters. Entries stay
`unverified` until a person has reviewed their lock file. Current lock files: `indic-parler-tts.json`
(10 files, safetensors only; pinned but not yet reviewed, and it does not cover the separate
`google/flan-t5-large` repository that the model's config loads at run time).

A lock for a verified or default entry must not list pickle-capable files (`.pt`, `.pth`, `.bin`,
`.pkl`, `.pickle`, `.ckpt`, `.joblib`, `.dill`): loading them can execute code. Exclude them when
locking, or keep the entry unverified. `ragleap-voice models check` enforces this.
