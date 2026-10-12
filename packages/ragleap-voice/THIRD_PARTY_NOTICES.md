# Third-party notices

Every model, dependency or borrowed file that ships or is downloaded by default
must be listed here with its licence and attribution. CC-BY entries must appear
here by model name (enforced by tests/test_licences.py).

Nothing below is shipped in the package or enabled by default. These entries cover
third-party material used only for benchmarking.

## Test data (benchmarks only)
- FLEURS (`google/fleurs` on Hugging Face), CC-BY-4.0. Conneau et al., "FLEURS: Few-shot
  Learning Evaluation of Universal Representations of Speech", 2022 (arXiv:2205.12446).
  Audio is downloaded at run time and not committed.

## Models and packages used for measurement (downloaded at run time, not vendored)
- Whisper large-v3 (OpenAI) converted by Systran (`Systran/faster-whisper-large-v3`),
  MIT per the model card (checked by the benchmark script at run time).
- faster-whisper 1.1.1: licence to be confirmed before it becomes a package dependency.
- IndicConformer-600M-Multi (AI4Bharat), MIT per the model card and the AI4Bharat GitHub page.
  Gated on Hugging Face and loaded with the repo's own code (`trust_remote_code`); revision
  pinned in `models.toml`. Training-data licences not reviewed.
- transformers, onnxruntime-gpu, onnx, torchaudio: used only inside Colab for measurement;
  licences to be confirmed before any of them becomes a package dependency.
- Indic Parler-TTS (AI4Bharat and Hugging Face), Apache-2.0 per the model card. Gated on Hugging Face
  (account and accepted conditions). Used through the parler-tts library from GitHub at a pinned commit
  (library licence to be confirmed). Training-data licences not reviewed.
- Kokoro-82M (hexgrad), Apache-2.0 per the model card. The card lists CC BY audio among the v1.0 training
  data and has its own attribution section: attribution entries are required before shipping it. Its Hindi
  path (and other non-English paths) uses espeak-ng (GPLv3), installed from the OS package manager for
  measurement only and neither shipped nor imported by this package.
- Chatterbox Multilingual (Resemble AI), MIT per the model card. Outputs carry Resemble's PerTh watermark,
  and the loader initialised the watermarker unconditionally in the version measured. Training-data and
  dependency licences not reviewed.
