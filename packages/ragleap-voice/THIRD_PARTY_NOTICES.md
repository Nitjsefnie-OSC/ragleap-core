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
