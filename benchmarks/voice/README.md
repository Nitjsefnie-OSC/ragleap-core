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

- Every JSON result file records its normalizer version in `meta.normalizer_version`; files written before this field existed use version `1` (the default normalizer).
- Data: first 20 clips per language from the `test` split of `google/fleurs` (CC-BY-4.0). Audio is downloaded at run time and is not committed.
- Engine: faster-whisper 1.1.1, model `Systran/faster-whisper-large-v3` at revision `edaa852ec7` (MIT), fp16, beam 5, temperature 0, language given.
- Hardware: Tesla T4 (15 GB), Google Colab. Run on 2026-10-11. Harness commit on main: `6d9fbecd0c`.
- Metrics: corpus-level WER and CER (total errors over total reference units), one shared normalizer (`ragleap_voice.bench.metrics`, version `1`: the default, without the number step). CER counts Unicode code points. RTF is time spent divided by audio length (below 1 is faster than real time); the first call is a warm-up and is not timed.

## Limits (read before quoting any number)

- 20 clips per language is 3 to 5 minutes of audio. There are no confidence intervals. Treat the numbers as rough.
- Few systems, one run each. Two open systems are compared on Hindi and Tamil only (next section). Nothing here supports a claim about any commercial service.
- The normalizer used here (version `1`) does not unify digits and spelled-out numbers. Optional number normalization is available as `numbers=True` (English, version `1+numbers-en.1`) and `numbers="tr"` (Turkish cardinal numbers, version `1+numbers-tr.1`); it also maps decimal digits of any script to ASCII. Neither option was used for a number in the tables on this page, and results measured with either option are not comparable with them. The Turkish mode covers cardinal numbers through katrilyon only; ordinals, dates, currency-specific handling, dialect and inflected forms are out of scope. Unsupported language strings raise ValueError rather than falling back to English; no third-party number-word data is used. WER on agglutinative languages such as Tamil is inflated by one wrong suffix. CER is the fairer figure for Indic scripts.
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

## TTS round trip: Indic Parler-TTS, Kokoro-82M, Chatterbox (first measurement)

Intelligibility proxy for text-to-speech: 20 sentences per language (text of FLEURS test sentences, CC-BY-4.0; sentences with digits, and Latin letters inside Indic text, were skipped) are synthesized, transcribed back by a fixed recogniser, and compared with the original text using the same normalizer as above. The recogniser is IndicConformer-600M (RNNT) for Indian languages and Whisper large-v3 (beam 5) for English. Speed is generation time divided by audio length on a Tesla T4 (below 1 means faster than real time). Built-in voices only, no cloning, no emotion prompts.

| System | Language | Round-trip WER (95% interval) | CER | Speed |
|---|---|---|---|---|
| Kokoro-82M | Hindi | 7.9% [4.3, 11.8] | 1.5% | 0.03 |
| Kokoro-82M | English | 1.8% [0.5, 3.4] | 0.8% | 0.03 |
| Indic Parler-TTS | Hindi | 7.7% [4.5, 10.9] | 2.0% | 2.15 |
| Indic Parler-TTS | Tamil | 16.1% [10.4, 22.2] | 4.7% | 2.13 |
| Indic Parler-TTS | Telugu | 11.9% [6.5, 17.4] | 1.1% | 2.14 |
| Indic Parler-TTS | Malayalam | 22.0% [15.3, 28.7] | 4.2% | 2.14 |
| Indic Parler-TTS | Kannada | 16.7% [11.6, 22.0] | 3.1% | 2.14 |
| Indic Parler-TTS | English | 5.8% [2.8, 10.1] | 3.5% | 2.14 |
| Chatterbox Multilingual | Hindi | 18.9% [8.3, 36.6] | 11.4% | 1.21 |
| Chatterbox Multilingual | English | 3.2% [0.8, 6.5] | 2.0% | 1.26 |

Method:

- Date 2026-10-12, Tesla T4 (15 GB), Google Colab. Model revisions (prefixes): `hexgrad/Kokoro-82M` f3ff357179, `ai4bharat/indic-parler-tts` 660bc53c64, `ResembleAI/chatterbox` 5bb1f6ee58. Kokoro 0.9.4 with misaki 0.9.4, voices `hf_alpha` (Hindi) and `af_heart` (English). Chatterbox: chatterbox-tts 0.1.7, torch 2.6.0+cu124. Parler: parler-tts at GitHub commit d108732cd5, transformers 4.46.1. Kokoro and Parler ran with torch 2.14.1+cu130. Each system ran in its own Python 3.11 environment.
- Parler used one fixed voice description (female speaker, slightly expressive, moderate speed and pitch, very clear recording) for every sentence.
- Parler's repository is gated on Hugging Face (account and accepted conditions). Its numbers come from the printed output of the run; raw per-clip files for the TTS runs are not committed.

What it shows:

- All three systems produced intelligible speech in the languages tested. Kokoro was far faster than real time on the T4; Parler and Chatterbox were slower than real time at default settings with no optimisation.
- Chatterbox's Hindi point estimate is worse than Kokoro's and Parler's, but its interval is wide and overlaps Kokoro's, so 20 sentences do not establish a difference.
- Only Parler covers all five Indian languages tested here.

Limits specific to this measurement:

- Round-trip error includes the recogniser's own errors. The Indian-language recogniser and Parler both come from AI4Bharat and may share training data, which could flatter Parler. Compare systems with each other, not against any absolute number.
- The sentences are easier than real-world text (no digits, no Latin letters in Indic text).
- 20 sentences per language, one run, one voice per system. Differences between languages are partly noise.
- Naturalness, emotion quality and voice similarity were not measured. They need human listeners (naturalness, emotion) and consented reference recordings (voice similarity).
- Speeds are not like-for-like: different libraries, different torch versions (Chatterbox) and no optimisation (Parler is slower than real time at defaults; its documentation describes faster inference modes that were not tested). GPU only; CPU speed and time to first audio were not measured.
- Kokoro's Hindi path uses the GPLv3 espeak-ng package according to its model card; it was installed from the OS package manager for this measurement only.
- `colab_tts_roundtrip.py` was assembled from three cells that were each run successfully. The combined script has not been run end to end as one piece.

## Whisper large-v3 on 12 languages from several regions (pilot)

First non-Indian measurement for the language coverage matrix. Scripts: `colab_pilot12.py` (measurement) and `colab_pilot12_analysis.py` (intervals and diagnostics, same Colab session).

| Language (FLEURS config) | WER (95% interval) | CER (95% interval) |
|---|---|---|
| Spanish (es_419) | 3.0% (1.8 to 4.5) | 1.1% (0.5 to 1.9) |
| Portuguese (pt_br) | 4.2% (2.9 to 5.7) | 1.4% (0.9 to 2.1) |
| Russian (ru_ru) | 4.9% (3.5 to 6.8) | 1.2% (0.7 to 1.7) |
| Turkish (tr_tr) | 5.1% (3.5 to 6.9) | 1.3% (0.8 to 2.0) |
| Indonesian (id_id) | 5.6% (3.8 to 7.5) | 1.8% (1.1 to 2.5) |
| French (fr_fr) | 6.1% (4.4 to 8.1) | 2.1% (1.4 to 3.0) |
| Vietnamese (vi_vn) | 8.8% (6.8 to 10.7) | 3.9% (2.9 to 4.9) |
| Arabic (ar_eg) | 14.0% (10.6 to 17.6) | 3.5% (2.6 to 4.6) |
| Swahili (sw_ke) | 33.5% (29.7 to 37.2) | 7.7% (6.5 to 9.1) |
| Japanese (ja_jp) | 70.6% (61.5 to 79.0): not meaningful, no word spaces | 6.5% (4.9 to 8.3) |
| Yoruba (yo_ng) | 103.8% (99.4 to 108.9) | 48.0% (45.3 to 50.6) |
| Amharic (am_et) | 162.1% (147.0 to 178.7) | 110.1% (103.8 to 117.4) |

Setup: 60 clips per language (first 60 of the FLEURS `test` split, CC-BY-4.0), run on 2026-10-18 on a Tesla T4. Model: `Systran/faster-whisper-large-v3` at revision `edaa852ec7e145841d8ffdb056a99866b5f0a478` (MIT), pulled with `ragleap-voice models pull` (hash-checked, CTranslate2-tagged lock) and loaded from that folder; faster-whisper 1.1.1, fp16, beam 5, temperature 0, no conditioning on previous text, language given. Harness on main at `d441b746c8`; normalizer version `1` (no number step). Intervals: 2000 bootstrap resamples of clips, seed 1234.

Findings:
- Spanish, Portuguese, Russian, Turkish, Indonesian and French are between 3% and 6% WER. Their intervals overlap, so their order is not reliable.
- Swahili (33.5%) is a real recognition problem.
- Japanese: use CER. WER is not meaningful without word spaces.
- Yoruba: scoring again with diacritics removed from both sides gives WER 87.2% and CER 26.7%. A large part of the character error is missing tone marks and dot-below letters, but the output is still not usable text. The stripped figures still include Whisper's own romanisation (for example "ishe" for "ise"), so they do not separate spelling convention from mishearing.
- Amharic: with our settings 36 of 60 outputs collapsed into a repeated syllable or word. Library defaults gave WER 114.1% and CER 104.7%, and a repetition guard gave WER 102.5% and CER 101.5%. In none of the three settings did the outputs resemble the reference. These variants were diagnostics run on the test set, not tuning, and the pilot numbers above stay the reported result. We did not find a usable Whisper large-v3 setting for Amharic; this is not a statement about every possible setting.

Limits (read before quoting any number):
- Read speech only. No telephone or noisy audio, no accents or code-switching.
- Consecutive clips: speakers and sentences repeat, so the intervals are probably too narrow.
- Arabic uses the Egyptian dialect configuration, while Whisper's `ar` is standard Arabic, so part of that error may be dialect mismatch. Spanish is the Latin American configuration.
- One system. This shows where Whisper large-v3 is weak, not which open model is best for those languages.
- Numbers and digits are not unified (normalizer version 1), which slightly inflates WER where references contain digits.
- The per-clip raw CSV is not committed yet; the tables come from the printed run output.

## Fine-tuned candidates for Swahili, Yoruba and Amharic (first look, possibly contaminated)

Whisper large-v3 was weak or failed in these three languages (pilot above). Two open fine-tunes of Whisper large-v3 were measured on the same 60 FLEURS `test` clips per language. Scripts: `colab_african_candidates_download.py`, `colab_african_candidates_measure.py`, `colab_african_candidates_unicode_check.py`.

| Language | Whisper large-v3 (pilot) | NaijaVox-2.0 | SunflowerASR |
|---|---|---|---|
| Swahili (sw_ke), WER (95% interval) | 33.5% (29.7 to 37.2) | not a candidate | 8.9% (7.0 to 11.0) |
| Swahili, CER | 7.7% | | 2.4% (1.8 to 3.0) |
| Yoruba (yo_ng), WER | 103.8% (99.4 to 108.9) | 46.5% (40.5 to 53.1) | 41.8% (35.6 to 48.6) |
| Yoruba, CER | 48.0% | 16.6% (13.9 to 19.5) | 15.1% (12.5 to 17.9) |
| Yoruba, diacritics removed from both sides, WER / CER | 87.2% / 26.7% | 24.1% / 7.2% | 20.7% / 5.8% |
| Amharic (am_et), WER | 162.1% (147.0 to 178.7) | not a candidate | 28.8% (24.6 to 33.2) |
| Amharic, CER | 110.1% | | 14.0% (10.1 to 18.5) |

Models (downloaded with `huggingface_hub` at these revisions; **not** hash-checked by ragleap-voice, no lock exists yet):
- `Axiveri/NaijaVox-2.0` at `22b94de94e59419cc9d6e25e6eaeceb1f1c42d00`: Apache-2.0 per its card, Yoruba, Hausa, Igbo, Pidgin and Nigerian English, single safetensors file, no code files.
- `Sunbird/asr-whisper-51-african-languages` (the Hub now reports `Sunbird/SunflowerASR-51-african-languages`) at `4583c9dd251c422a4325fb0a0a509a3828097be2`: Apache-2.0 per its card, 51 African languages, gated (access mode auto), single safetensors file, no code files. Language tokens come from its card: `swa` 50318, `yor` 50325, `amh` 50334.

Read these first:
- **Possibly contaminated.** Both cards list google/fleurs among their training data (NaijaVox: the yo_ng, ha_ng and ig_ng configurations; SunflowerASR: FLEURS among its sources). Which splits they used is not stated. We scored on FLEURS test clips, so these numbers show that a large gap exists, not how well the models do on unseen audio. A clean test set is still needed (issue #758).
- **Licences are not cleared.** Apache-2.0 is the licence of the weights as stated on the card. Both cards say the training datasets keep their own licences, and we have not reviewed them. Neither model is in `models.toml`, and neither belongs in the default path until a person has reviewed the training-data licences.
- **Not like-for-like with the Whisper pilot.** Different engine (`transformers` instead of faster-whisper), greedy decoding instead of beam 5, fp16, batch of 8, `max_new_tokens` 220. Decoding settings were fixed before scoring. The `transformers` version was not recorded in this run.
- **Unexplained gap to a model card.** The NaijaVox card reports 22.3% WER on 50 FLEURS Yoruba test clips ("strict WER, no normalization"). We measure 46.5% with diacritics counted and 24.1% without them. We checked Unicode composition (references 0/60 and outputs 3/60 not in NFC; NFC on both sides changed WER by under 0.1 points), so that is not the cause. We do not know which clips, scorer or decoding the card used.
- **Yoruba.** About half of the word error comes from tone marks and dot-below letters. Both models produce real Yoruba text, which Whisper large-v3 did not.
- **Amharic.** SunflowerASR output resembles the reference where Whisper large-v3 produced repeated syllables.
- Same limits as the other sections: read speech only, consecutive clips (speakers and sentences repeat, so the intervals are probably too narrow), 60 clips, one GPU (Tesla T4), normalizer version 1 (no number step), per-clip raw results not committed.

## Reproduce

Open Google Colab, choose a T4 GPU runtime, paste `colab_whisper_baseline.py` into one cell and run it. It stops if the dataset or model licence differs from the expected one.

For the IndicConformer comparison, first accept the model conditions on Hugging Face and store a read token in Colab Secrets as `HF_TOKEN`, then paste `colab_indic_conformer.py` into one cell. It rebuilds the test set and Whisper results itself if the runtime has none. Delete the token afterwards.

For the five-language comparison, use the same Hugging Face token setup and paste `colab_multilang_comparison.py` into one cell (about 25 minutes). It is self-contained and also runs the device check and the default-decoding Whisper check.

For the TTS round trip, accept the conditions on `ai4bharat/indic-parler-tts` and `ai4bharat/indic-conformer-600m-multilingual` with the same Hugging Face account, store the token as `HF_TOKEN`, keep the Colab tab in the foreground at the start, and paste `colab_tts_roundtrip.py` into one cell (about 60 minutes; not yet run as one piece).

## Attribution

FLEURS: Conneau et al., 2022 (CC-BY-4.0). See `packages/ragleap-voice/THIRD_PARTY_NOTICES.md`.
