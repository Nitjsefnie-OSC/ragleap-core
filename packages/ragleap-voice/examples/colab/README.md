# Colab demo (pre-alpha)

A two-cell Google Colab demo of ragleap-voice: speech to text (Whisper large-v3, IndicConformer-600M) and text to speech (Indic Parler-TTS, Kokoro-82M, Chatterbox), with zero-shot voice cloning and a consent record. It is a preview for trying things out, not a product, and nothing here has had a legal review.

## Steps (T4 GPU runtime)

1. Create a short-lived Hugging Face **read** token and save it as the Colab secret `HF_TOKEN` (Notebook access on). Accept the conditions of the gated models first.
2. Run `cell1_setup.py` as one Colab cell (about 10 to 15 minutes; keep the tab in the foreground at the start).
3. Delete the `HF_TOKEN` secret and the token on huggingface.co.
4. Run `cell2_interface.py` as the next cell. It refuses to start while the secret still exists or while the token is still in the kernel's memory.

Why the order matters: IndicConformer ships its own loader code (`trust_remote_code`), which runs inside the notebook. It must not be able to reach a token.

## What is and is not checked

- Indic Parler-TTS and its tokenizer are pulled through `ragleap-voice` and hash-checked against the lock files. Both entries are still marked unverified (no human review yet).
- IndicConformer is downloaded at a pinned revision after a licence check. It is not locked.
- Kokoro and Chatterbox are downloaded by their own libraries at run time and are not hash-checked. Kokoro's non-English paths use GPLv3 espeak-ng.
- Cell 1 installs `ragleap-voice` from the moving `main` branch, not from a fixed commit.
- Measured figures shown in the interface come from `benchmarks/voice/` (read speech, small samples, one GPU). Naturalness, emotion quality and voice similarity are not measured.

Use only your own voice, or a voice you have written permission to clone. Never clone a public figure.
