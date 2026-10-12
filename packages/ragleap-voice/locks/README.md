# Model lock files

One JSON file per model, named `<model>.json`, listing every file of that model at the pinned
revision: relative path, size in bytes and SHA-256. The `sha256` field of the model's entry in
`models.toml` is the SHA-256 of the lock's canonical form (sorted keys, compact separators), so
editing a lock without updating the manifest, or the other way round, fails `ragleap-voice models check`.

Format (schema 1):

    {"schema": 1, "model": "NAME", "revision": "PINNED-REVISION", "source_url": "https://...",
     "files": [{"path": "dir/file.bin", "size": 123, "sha256": "<64 lowercase hex>"}]}

Paths are relative POSIX paths without `..`, backslashes or unusual characters. Entries stay
`unverified` until a person has reviewed their lock file. There are no lock files yet.
