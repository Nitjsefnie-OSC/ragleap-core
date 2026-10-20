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
(10 files, safetensors only) and `flan-t5-large-tokenizer.json` (5 tokenizer files of the text encoder it
loads at run time; its dependency). Both are pinned but not yet reviewed. `whisper-large-v3.json` (7 files, `model.bin` tagged `ctranslate2`) was built on Colab; its `model.bin` size and SHA-256 equal the Hugging Face listing, the six small files rest on our own download only. The entry stays unverified.

A lock for a verified or default entry must not list pickle-capable files (`.pt`, `.pth`, `.bin`,
`.pkl`, `.pickle`, `.ckpt`, `.joblib`, `.dill`): loading them can execute code. Exclude them when
locking, or keep the entry unverified. `ragleap-voice models check` enforces this.

One justified exception: a file entry may carry `"format": "ctranslate2"` when it is a `.bin` file
(the CTranslate2 weights of Whisper). The tag is part of the lock, so the lock digest in `models.toml`
covers it. It is honoured only for that suffix, and `models verify` and `models pull` also check the
file's header, in addition to size and SHA-256. Any other format needs a code change. Residual risk: the
header check does not prove the rest of the file is well formed, and CTranslate2 reads the file with native
code. The hash pins what was reviewed; it does not make the file trustworthy.
Write the tag with `ragleap-voice models lock NAME ... --format model.bin=ctranslate2`. A tagged file is downloaded
to a temporary folder (free disk space for the whole file is needed) so its header is checked before the tag is written.

A manifest entry can list other entries in `depends_on`. Each dependency has its own lock file and its own cache
folder. `pull` fetches dependencies first and refuses to start if any lock is missing; a verified or default
entry may only depend on verified entries.
