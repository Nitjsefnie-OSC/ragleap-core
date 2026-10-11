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
- One system, one run. There is no comparison with any other engine yet, so these numbers support no better-than or worse-than claim.
- The normalizer does not unify digits and spelled-out numbers, and WER on agglutinative languages such as Tamil is inflated by one wrong suffix. CER is the fairer figure for Indic scripts.
- GPU speed only. CPU speed and time to first partial result are not measured.
- Reference transcripts are used as given by FLEURS and were not re-checked.
- The per-clip raw results (CSV and JSON) are not committed yet. They are produced by the script below and will be added in a later change. Until then the table above comes from the printed run summary.

## Reproduce

Open Google Colab, choose a T4 GPU runtime, paste `colab_whisper_baseline.py` into one cell and run it. It stops if the dataset or model licence differs from the expected one.

## Attribution

FLEURS: Conneau et al., 2022 (CC-BY-4.0). See `packages/ragleap-voice/THIRD_PARTY_NOTICES.md`.
