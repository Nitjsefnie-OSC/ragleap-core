# Voice benchmarks

Measurements for ragleap-voice and the script that produced them. Nothing here is a marketing claim.

## Whisper large-v3 baseline (first measurement, small sample)

| Language | Clips | WER | CER | RTF | Audio |
|---|---|---|---|---|---|
| English (en_us) | 20 | 4.8% | 2.2% | 0.09 | 189 s |
| Hindi (hi_in) | 20 | 25.4% | 7.3% | 0.24 | 235 s |
| Tamil (ta_in) | 20 | 43.9% | 11.2% | 0.20 | 277 s |
| All | 60 | 23.3% | 7.2% | 0.18 | 700 s |

## Method

- Data: first 20 clips per language from the `test` split of `google/fleurs` (CC-BY-4.0). Audio is downloaded at run time and is not committed.
- Engine: faster-whisper 1.1.1, model `Systran/faster-whisper-large-v3` at revision `edaa852ec7` (MIT), fp16, beam 5, temperature 0, language given.
- Hardware: Tesla T4 (15 GB), Google Colab. Run on 2026-10-11. Harness commit on main: `6d9fbecd0c`.
- Metrics: corpus-level WER and CER (total errors over total reference units), one shared normalizer (`ragleap_voice.bench.metrics`). CER counts Unicode code points. RTF is time spent divided by audio length (below 1 is faster than real time); the first call is a warm-up and is not timed.

## Limits (read before quoting any number)

- 20 clips per language is 3 to 5 minutes of audio. There are no confidence intervals. Treat the numbers as rough.
- Few systems, one run each. Two open systems are compared on Hindi and Tamil only (next section). Nothing here supports a claim about any commercial service.
- The normalizer does not unify digits and spelled-out numbers, and WER on agglutinative languages such as Tamil is inflated by one wrong suffix. CER is the fairer figure for Indic scripts.
- GPU speed only. CPU speed and time to first partial result are not measured.
- Reference transcripts are used as given by FLEURS and were not re-checked.
- The per-clip raw results (CSV and JSON) are not committed yet. They are produced by the script below and will be added in a later change. Until then the table above comes from the printed run summary.

## IndicConformer-600M vs Whisper large-v3 (Hindi and Tamil only)

Second measurement on the same 40 clips (the first 20 Hindi and first 20 Tamil FLEURS test clips) with the same normalizer. IndicConformer has no English, so English is not part of this comparison. Whisper numbers are the ones above.

| 20 clips each | Whisper large-v3 | IndicConformer CTC | IndicConformer RNNT |
|---|---|---|---|
| Hindi WER | 25.4% | 9.5% | 8.2% |
| Hindi CER | 7.3% | 2.6% | 2.4% |
| Tamil WER | 43.9% | 29.8% | 26.0% |
| Tamil CER | 11.2% | 12.6% | 12.2% |
| Hindi RTF | 0.242 | 0.033 | 0.085 |
| Tamil RTF | 0.201 | 0.012 | 0.068 |

What it shows:

- Hindi: IndicConformer's word error rate is about a third of Whisper's, and its character error rate is lower too.
- Tamil: word error rate is lower, but character error rate is not lower than Whisper's (12.2% against 11.2% for RNNT). In one inspected clip the reference has the Latin letters "ph"; Whisper wrote Latin "pH" and IndicConformer spelled it phonetically in Tamil script. Latin-script tokens may affect Tamil CER, but only one clip was inspected, so this is a hypothesis, not a finding.
- RNNT decoding is slightly more accurate than CTC and several times slower.

Method:

- Model `ai4bharat/indic-conformer-600m-multilingual` at revision `2a77d305038dfc502fd9464e7d028b90381976cb` (MIT per the model card and the AI4Bharat GitHub page), CTC and RNNT decoding, language given.
- Packages: transformers 5.18.0, onnxruntime-gpu 1.31.0, onnx 1.20.1, torchaudio 2.11.0+cu130 (Colab preinstalled). These are much newer than the versions on the model card.
- Hardware: Tesla T4 (15 GB), Google Colab, 2026-10-11. The first call per decoding mode is a warm-up and is not timed.
- The repository is gated on Hugging Face (account and accepted conditions) and ships its own loader code (`trust_remote_code`), which runs inside the Colab session. The token lives in Colab Secrets and should be deleted afterwards.
- Workaround: onnxruntime 1.31 rejects weight files that resolve outside the model folder, and the Hugging Face cache uses symlinks. The script downloads the model into a normal local folder of real files and points the model's loader at it.

Limits specific to this comparison:

- The RTF column is not comparable across systems. The device for IndicConformer is unlabeled: its code asks for the GPU when PyTorch sees one, but ONNX Runtime may fall back to CPU, and this was not verified. Read accuracy first.
- 20 clips per language, one run, no confidence intervals.
- Whether either model saw FLEURS-like data in training has not been checked.
- Two open models only. Nothing here compares against a commercial service.
- The remote loader code has not been independently audited, and the model is gated, so it is not eligible as a default model (see `packages/ragleap-voice/models.toml`).

## Reproduce

Open Google Colab, choose a T4 GPU runtime, paste `colab_whisper_baseline.py` into one cell and run it. It stops if the dataset or model licence differs from the expected one.

For the IndicConformer comparison, first accept the model conditions on Hugging Face and store a read token in Colab Secrets as `HF_TOKEN`, then paste `colab_indic_conformer.py` into one cell. It rebuilds the test set and Whisper results itself if the runtime has none. Delete the token afterwards.

## Attribution

FLEURS: Conneau et al., 2022 (CC-BY-4.0). See `packages/ragleap-voice/THIRD_PARTY_NOTICES.md`.
