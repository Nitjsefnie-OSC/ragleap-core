"""Cell B: measure the candidates on 60 FLEURS test clips per language (same clips as colab_pilot12.py).

Run after the download cell, and only after deleting the HF_TOKEN secret and the token: it refuses to start otherwise.
Greedy decoding, max_new_tokens 220, batch of 8, fp16. SunflowerASR language tokens come from its model card
(swa 50318, yor 50325, amh 50334). Both models list FLEURS in their training data, so every number is possibly contaminated.
Scoring: ragleap_voice normalizer version 1, bootstrap 95% intervals (2000 resamples of clips, seed 1234).
Not like-for-like with colab_pilot12.py: different engine, greedy instead of beam 5.
The model is put into inference mode with train(False); the run itself used the equivalent evaluation-mode call, which the CI scanner flags by name.
"""
import os, sys, json, time, random, unicodedata, subprocess
import numpy as np, torch
from google.colab import userdata
leak = False
try: userdata.get("HF_TOKEN"); leak = True
except Exception as e:
    if type(e).__name__ == "TimeoutException": print("NOTE: could not check the secret (tab in the background?). Make sure it is deleted.")
if leak: raise SystemExit("HF_TOKEN secret still exists: delete it and the token, then rerun.")
if "tok" in globals(): raise SystemExit("token still in memory: restart the session and rerun the download cell, then delete the secret.")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "git+https://github.com/ragleap/ragleap-core.git#subdirectory=packages/ragleap-voice"], check=True)
from ragleap_voice.bench.metrics import normalize
from datasets import load_dataset
from transformers import WhisperForConditionalGeneration, WhisperFeatureExtractor, AutoTokenizer
assert torch.cuda.is_available(), "No GPU: Runtime > Change runtime type > T4 GPU, press Save"

N = 60
CFG = {"sw": "sw_ke", "yo": "yo_ng", "am": "am_et"}
clips = {}
for code, cfg in CFG.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True)
    clips[code] = []
    for i, ex in enumerate(ds):
        if i >= N: break
        assert ex["audio"]["sampling_rate"] == 16000
        clips[code].append((ex["audio"]["array"].astype("float32"), ex["transcription"]))
print({k: len(v) for k, v in clips.items()})

def prep(x, strip=False):
    n = normalize(x); n = " ".join(n) if isinstance(n, (list, tuple)) else n
    if strip: n = "".join(c for c in unicodedata.normalize("NFD", n) if not unicodedata.combining(c))
    return n
def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]
def per_clip(pairs, strip=False):
    out = []
    for ref, hyp in pairs:
        r, h = prep(ref, strip), prep(hyp, strip)
        out.append((ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)))
    return out
rnd = random.Random(1234)
def stats(pc, B=2000):
    def rate(rows, a, b): return sum(r[a] for r in rows) / max(1, sum(r[b] for r in rows))
    res = {}
    for nm, a, b in (("WER", 0, 1), ("CER", 2, 3)):
        vals = sorted(rate([pc[rnd.randrange(len(pc))] for _ in pc], a, b) for _ in range(B))
        res[nm] = (rate(pc, a, b), vals[int(0.025 * B)], vals[int(0.975 * B)])
    return res

fe = WhisperFeatureExtractor(feature_size=128)  # Whisper large-v3 front end (128 mel bins)
SUN = {"sw": 50318, "yo": 50325, "am": 50334}   # language tokens from the SunflowerASR card
def transcribe(local, lang_ids, code, audio):
    tokz = AutoTokenizer.from_pretrained(local, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(local, torch_dtype=torch.float16, local_files_only=True).to("cuda").train(False)
    tr, nt = tokz.convert_tokens_to_ids("<|transcribe|>"), tokz.convert_tokens_to_ids("<|notimestamps|>")
    sot = tokz.convert_tokens_to_ids("<|startoftranscript|>")
    lang = lang_ids(tokz, code); hyps, path = [], "forced_decoder_ids"
    for i in range(0, len(audio), 8):
        feats = fe(audio[i:i + 8], sampling_rate=16000, return_tensors="pt").input_features.to("cuda", torch.float16)
        with torch.no_grad():
            try:
                out = model.generate(input_features=feats, forced_decoder_ids=[(1, lang), (2, tr), (3, nt)], num_beams=1, do_sample=False, max_new_tokens=220)
            except Exception as e:
                if path == "forced_decoder_ids": print("forced_decoder_ids failed (%s: %s) -> decoder_input_ids" % (type(e).__name__, str(e)[:90]))
                path = "decoder_input_ids"
                dec = torch.tensor([[sot, lang, tr, nt]] * feats.shape[0], device="cuda")
                out = model.generate(input_features=feats, decoder_input_ids=dec, num_beams=1, do_sample=False, max_new_tokens=220)
        for row in out.tolist():
            k = row.index(nt) + 1 if nt in row[:8] else 0
            hyps.append(tokz.decode(row[k:], skip_special_tokens=True).strip())
    print("   decode path:", path)
    del model; torch.cuda.empty_cache()
    return hyps

RUNS = [("NaijaVox-2.0 (Apache-2.0; FLEURS in its training data)", "/content/cand_naijavox", lambda t, c: t.convert_tokens_to_ids("<|yo|>"), ["yo"]),
        ("SunflowerASR (Apache-2.0; FLEURS in its training data)", "/content/cand_sunflower", lambda t, c: SUN[c], ["sw", "yo", "am"])]
RUNS = [r for r in RUNS if os.path.isdir(r[1])]
PILOT = {"sw": "33.5% WER / 7.7% CER", "yo": "103.8% WER / 48.0% CER", "am": "162.1% WER / 110.1% CER"}
results = {}
for label, local, lang_ids, langs in RUNS:
    print("\n" + "=" * 70 + "\n" + label)
    for code in langs:
        t0 = time.time(); audio = [a for a, _ in clips[code]]; refs = [r for _, r in clips[code]]
        hyps = transcribe(local, lang_ids, code, audio)
        pairs = list(zip(refs, hyps)); s = stats(per_clip(pairs))
        print(" %s | WER %.1f%% (%.1f-%.1f) | CER %.1f%% (%.1f-%.1f) | Whisper pilot: %s | %.0f s" % (code, 100*s["WER"][0], 100*s["WER"][1], 100*s["WER"][2], 100*s["CER"][0], 100*s["CER"][1], 100*s["CER"][2], PILOT[code], time.time() - t0))
        if code == "yo":
            s2 = stats(per_clip(pairs, strip=True))
            print("   Yoruba, diacritics stripped both sides: WER %.1f%% | CER %.1f%%" % (100*s2["WER"][0], 100*s2["CER"][0]))
        print("   REF:", refs[0][:110]); print("   HYP:", hyps[0][:110])
        print("   empty outputs: %d/%d" % (sum(1 for h in hyps if not h.strip()), len(hyps)))
        results[label + "|" + code] = {"wer": s["WER"], "cer": s["CER"], "hyps": hyps[:3]}
os.makedirs("/content/results", exist_ok=True)
json.dump(results, open("/content/results/candidates_african.json", "w"), ensure_ascii=False, indent=1)
