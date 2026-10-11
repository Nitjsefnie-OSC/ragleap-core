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

- The RTF column in this 20-clip table is not comparable across systems, and the device was not checked in this run. A later run (next section) measured that IndicConformer used the GPU. Read accuracy first.
- 20 clips per language, one run, no confidence intervals.
- Whether either model saw FLEURS-like data in training has not been checked.
- Two open models only. Nothing here compares against a commercial service.
- The remote loader code has not been independently audited, and the model is gated, so it is not eligible as a default model (see `packages/ragleap-voice/models.toml`).

## Five Indian languages, 60 clips each (Whisper large-v3 vs IndicConformer-600M)

Third measurement: the first 60 FLEURS test clips for each of Hindi, Tamil, Telugu, Malayalam and Kannada (300 clips), same normalizer and same packages as above. Intervals are 95% bootstrap intervals over clips (2000 resamples). Whisper was run with temperature 0, beam 5 and no context carry-over; IndicConformer with CTC and RNNT decoding.

| Language | System | WER (95% interval) | CER (95% interval) | RTF |
|---|---|---|---|---|
| Hindi | Whisper large-v3 | 26.8% [24.3, 29.4] | 8.6% [7.4, 10.0] | 0.219 |
| Hindi | IndicConformer CTC | 10.6% [8.4, 13.0] | 3.5% [2.4, 4.9] | 0.010 |
| Hindi | IndicConformer RNNT | 10.2% [7.9, 12.9] | 3.6% [2.4, 5.2] | 0.029 |
| Tamil | Whisper large-v3 | 49.3% [44.5, 54.3] | 13.1% [10.7, 16.4] | 0.196 |
| Tamil | IndicConformer CTC | 29.0% [24.1, 34.5] | 11.2% [7.6, 16.3] | 0.007 |
| Tamil | IndicConformer RNNT | 27.5% [23.0, 32.6] | 10.9% [7.2, 16.1] | 0.029 |
| Telugu | Whisper large-v3 | 73.9% [69.7, 77.9] | 33.1% [27.3, 38.6] | 0.351 |
| Telugu | IndicConformer CTC | 21.8% [16.8, 27.3] | 7.1% [4.6, 10.8] | 0.009 |
| Telugu | IndicConformer RNNT | 21.4% [16.4, 26.9] | 7.0% [4.5, 10.6] | 0.032 |
| Malayalam | Whisper large-v3 | 111.4% [107.4, 115.9] | 88.9% [86.1, 91.3] | 0.267 |
| Malayalam | IndicConformer CTC | 21.8% [18.0, 25.8] | 5.9% [4.2, 7.8] | 0.007 |
| Malayalam | IndicConformer RNNT | 20.8% [17.2, 24.5] | 5.7% [4.1, 7.6] | 0.029 |
| Kannada | Whisper large-v3 | 67.2% [62.9, 71.2] | 24.9% [20.3, 29.8] | 0.289 |
| Kannada | IndicConformer CTC | 16.1% [12.9, 19.4] | 4.0% [2.6, 5.7] | 0.007 |
| Kannada | IndicConformer RNNT | 16.5% [13.0, 19.8] | 3.9% [2.4, 5.6] | 0.029 |

Paired difference in word error rate (Whisper minus IndicConformer RNNT, 95% bootstrap interval over clips): Hindi [14.2, 18.9], Tamil [16.8, 26.8], Telugu [45.1, 58.8], Malayalam [84.9, 96.4], Kannada [46.1, 54.9] percentage points. No interval includes zero.

Whisper with library-default decoding (temperature fallback and context carry-over on), run on Telugu, Malayalam and Kannada to check that the settings above did not handicap it:

| Language | WER | CER | RTF |
|---|---|---|---|
| Telugu | 73.9% | 33.1% | 0.347 |
| Malayalam | 113.6% | 89.5% | 0.357 |
| Kannada | 67.5% | 25.3% | 0.296 |

What it shows:

- On this sample IndicConformer-600M is clearly more accurate than Whisper large-v3 in all five languages. The Whisper decoding settings made no material difference (within 2.2 points of WER).
- Whisper's Malayalam word error rate above 100% means it produced many wrong or extra words. In one inspected clip it wrote Telugu-script text for Malayalam audio even though the language was set to Malayalam. That is one clip, not a general finding.
- CTC and RNNT decoding are within about two points of each other in every language. In Tamil, character error rates overlap between all three systems.

Device and speed: GPU memory grew by 3,564 MiB when IndicConformer loaded and ran its first call, so it used the GPU (a memory heuristic, not a profiler). Both systems ran on the same Tesla T4, but the model sizes (about 1.5B parameters against about 0.6B) and runtimes (CTranslate2 fp16 against ONNX Runtime) differ, so RTF is indicative, not a like-for-like speed comparison.

Limits specific to this measurement:

- The 60 clips per language are the first consecutive clips of the test split, so speakers and sentences repeat. The bootstrap treats clips as independent, so the intervals are probably too narrow.
- FLEURS is read speech. Phone calls, noise and spontaneous speech may behave very differently. Whether either model saw FLEURS-like data in training has not been checked.
- Two open models only. Nothing here compares against a commercial service.
- IndicConformer has no English. The model is gated and loads its own repo code, which has not been independently audited, so it is not eligible as a default model.

## Reproduce

Open Google Colab, choose a T4 GPU runtime, paste `colab_whisper_baseline.py` into one cell and run it. It stops if the dataset or model licence differs from the expected one.

For the IndicConformer comparison, first accept the model conditions on Hugging Face and store a read token in Colab Secrets as `HF_TOKEN`, then paste `colab_indic_conformer.py` into one cell. It rebuilds the test set and Whisper results itself if the runtime has none. Delete the token afterwards.

For the five-language comparison, use the same Hugging Face token setup and paste `colab_multilang_comparison.py` into one cell (about 25 minutes). It is self-contained and also runs the device check and the default-decoding Whisper check.

## Attribution

FLEURS: Conneau et al., 2022 (CC-BY-4.0). See `packages/ragleap-voice/THIRD_PARTY_NOTICES.md`.
