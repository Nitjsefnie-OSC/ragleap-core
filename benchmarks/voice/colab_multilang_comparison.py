"""Whisper large-v3 vs IndicConformer-600M on five Indian languages (60 FLEURS clips each).

Run in Google Colab (T4 GPU runtime), pasted into one cell. Needs network, about 25 minutes.
Prerequisite: a Hugging Face account that has accepted the conditions on
ai4bharat/indic-conformer-600m-multilingual, and a read token in Colab Secrets as HF_TOKEN
with Notebook access on. Delete the token afterwards: the model's own repo code runs inside
this session (trust_remote_code).
Part 1 measures both systems with bootstrap intervals. Part 2 checks which device
IndicConformer runs on and re-runs Whisper with library-default decoding.
"""
import subprocess, sys, csv, wave, pathlib, glob, ctypes, site, random, importlib.metadata as md

N = 60  # clips per language
LANGS = {"hi": "hi_in", "ta": "ta_in", "te": "te_in", "ml": "ml_in", "kn": "kn_in"}

def run(*a): return subprocess.run(list(a), capture_output=True, text=True)
def pip(*pk):
    r = run(sys.executable, "-m", "pip", "install", "-q", *pk)
    assert r.returncode == 0, r.stderr[-800:]
pip("faster-whisper==1.1.1", "datasets==3.6.0", "soundfile", "nvidia-cublas-cu12", "nvidia-cudnn-cu12",
    "git+https://github.com/ragleap/ragleap-core.git#subdirectory=packages/ragleap-voice")
pip("transformers==5.18.0", "onnxruntime-gpu==1.31.0", "onnx==1.20.1", "torchaudio")

def smi(q):
    try: return run("nvidia-smi", "--query-gpu=" + q, "--format=csv,noheader,nounits").stdout.strip()
    except FileNotFoundError: return ""
gpu = smi("name,memory.total")
assert gpu, "No GPU: Runtime > Change runtime type > T4 GPU"
def used(): return int(smi("memory.used").split()[0])
main_sha = run("git", "ls-remote", "https://github.com/ragleap/ragleap-core.git", "refs/heads/main").stdout.split()[0]

from google.colab import userdata
try: tok = userdata.get("HF_TOKEN")
except Exception: raise SystemExit("Add the secret HF_TOKEN (key icon), Notebook access on, then rerun")

libs = []
for r in site.getsitepackages() + [site.getusersitepackages()]:
    libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True)
    libs += sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
loaded = []
for p in libs:
    try: ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL); loaded.append(p.split("/")[-1])
    except OSError: pass
assert any(x.startswith("libcublas.so") for x in loaded), "cuBLAS not loaded"

import numpy as np, torch, huggingface_hub
from huggingface_hub import HfApi, snapshot_download
api = HfApi()
def lic(info):
    v = info.card_data.license
    return [x.lower() for x in ([v] if isinstance(v, str) else (v or []))]
assert lic(api.dataset_info("google/fleurs")) == ["cc-by-4.0"], "FLEURS licence changed: STOP"
mw = api.model_info("Systran/faster-whisper-large-v3"); assert lic(mw) == ["mit"], "Whisper licence changed: STOP"
IC = "ai4bharat/indic-conformer-600m-multilingual"
mi2 = api.model_info(IC, token=tok); assert lic(mi2) == ["mit"], "IndicConformer licence changed: STOP"
print("IC revision:", mi2.sha, "| Whisper revision:", mw.sha[:10])

# Test set: first N test clips per language, 16 kHz mono WAV
from datasets import load_dataset
root = pathlib.Path("/content/fleurs_multi"); root.mkdir(exist_ok=True)
rows = []
for code, cfg in LANGS.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True)
    for i, ex in enumerate(ds):
        if i >= N: break
        a = ex["audio"]; assert a["sampling_rate"] == 16000
        name = f"{code}_{i:03d}.wav"
        with wave.open(str(root / name), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes((np.clip(a["array"], -1, 1) * 32767).astype("<i2").tobytes())
        rows.append([f"{code}_{i:03d}", name, ex["transcription"], code, "CC-BY-4.0", "google/fleurs test, config " + cfg])
with open(root / "manifest.csv", "w", encoding="utf-8", newline="") as f:
    cw = csv.writer(f); cw.writerow(["id", "path", "reference", "language", "license", "source"]); cw.writerows(rows)
from ragleap_voice.bench import load_manifest, run_stt, summarize, environment_info, write_results
items, problems = load_manifest(root / "manifest.csv"); assert not problems, problems
print("clips:", len(items))

def load_wav(path):
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1 and wf.getsampwidth() == 2
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float32") / 32768.0

# System 1: Whisper large-v3
from faster_whisper import WhisperModel
wm = WhisperModel("large-v3", device="cuda", compute_type="float16")
def whisper_engine(path, lang):
    segs, _ = wm.transcribe(load_wav(path), language=lang, beam_size=5, temperature=0.0, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)
whisper_engine(items[0].path, items[0].language)
res_w = run_stt(whisper_engine, items)
print("whisper done")

# System 2: IndicConformer (real files in a normal folder: onnxruntime 1.31 rejects Hugging Face cache symlinks)
local = snapshot_download(IC, revision=mi2.sha, token=tok, local_dir="/content/ic_model")
from transformers import AutoModel
for k in [k for k in sys.modules if "model_onnx" in k]: del sys.modules[k]
_orig = huggingface_hub.snapshot_download
huggingface_hub.snapshot_download = lambda repo_id, *a, **k: local if repo_id == IC else _orig(repo_id, *a, **k)
try: ic = AutoModel.from_pretrained(IC, revision=mi2.sha, trust_remote_code=True, token=tok)
finally: huggingface_hub.snapshot_download = _orig
def ic_engine_for(mode):
    def eng(path, lang):
        out = ic(torch.from_numpy(load_wav(path)).unsqueeze(0), lang, mode)
        return str(out[0] if isinstance(out, (list, tuple)) else out).strip()
    return eng
ic_engine_for("ctc")(items[0].path, items[0].language)  # warm-up
res_c = run_stt(ic_engine_for("ctc"), items)
res_r = run_stt(ic_engine_for("rnnt"), items)

for name, rr in (("whisper-large-v3", res_w), ("indic-conformer-ctc", res_c), ("indic-conformer-rnnt", res_r)):
    meta = environment_info(gpu=gpu, system=name, whisper_revision=mw.sha, ic_revision=mi2.sha,
        transformers=md.version("transformers"), onnxruntime_gpu=md.version("onnxruntime-gpu"),
        faster_whisper=md.version("faster-whisper"), dataset="google/fleurs test, first %d per language" % N,
        harness_commit_main=main_sha)
    write_results("/content/results", name, rr, meta)

# Statistics: 95% bootstrap intervals over clips; paired difference between systems
SYS = {"whisper": res_w, "ic_ctc": res_c, "ic_rnnt": res_r}
def pairs(rr, ek, nk): return {r["id"]: (r[ek], r[nk]) for r in rr if not r["error"]}
P = {s: (pairs(rr, "word_errors", "ref_words"), pairs(rr, "char_errors", "ref_chars")) for s, rr in SYS.items()}
def ci(vals, B=2000, seed=0):
    rnd = random.Random(seed); n = len(vals); out = []
    for _ in range(B):
        smp = [vals[rnd.randrange(n)] for _ in range(n)]
        out.append(sum(e for e, _ in smp) / sum(m for _, m in smp))
    out.sort(); return out[int(0.025 * B)], out[int(0.975 * B)]
def ci_diff(va, vb, B=2000, seed=1):
    rnd = random.Random(seed); n = len(va); out = []
    for _ in range(B):
        idx = [rnd.randrange(n) for _ in range(n)]
        out.append(sum(va[i][0] for i in idx) / sum(va[i][1] for i in idx) - sum(vb[i][0] for i in idx) / sum(vb[i][1] for i in idx))
    out.sort(); return out[int(0.025 * B)], out[int(0.975 * B)]
def pc(x): return "%5.1f%%" % (100 * x)

print()
for lang in LANGS:
    ids = [i.id for i in items if i.language == lang]
    ok = [x for x in ids if all(x in P[s][0] and x in P[s][1] for s in SYS)]
    print("== %s: %d of %d clips usable in all systems" % (lang, len(ok), len(ids)))
    wv = {}
    for s in SYS:
        w = [P[s][0][x] for x in ok]; c = [P[s][1][x] for x in ok]; wv[s] = w
        wl, wh = ci(w); cl, ch = ci(c)
        rtf = summarize(SYS[s])[lang]["rtf"]
        print("  %-8s WER %s [%s,%s]  CER %s [%s,%s]  RTF %.3f" % (s, pc(sum(e for e, _ in w) / sum(m for _, m in w)), pc(wl), pc(wh),
              pc(sum(e for e, _ in c) / sum(m for _, m in c)), pc(cl), pc(ch), rtf))
    for s in ("ic_ctc", "ic_rnnt"):
        lo, hi = ci_diff(wv["whisper"], wv[s])
        print("  WER whisper minus %-8s: [%s,%s]  %s" % (s, pc(lo), pc(hi), "interval excludes 0" if (lo > 0 or hi < 0) else "includes 0: no clear difference"))

# Part 2: device check for IndicConformer, and Whisper with library-default decoding
import gc, time
del ic; gc.collect(); torch.cuda.empty_cache(); time.sleep(3)
before = used()
for k in [k for k in sys.modules if "model_onnx" in k]: del sys.modules[k]
_o = huggingface_hub.snapshot_download
huggingface_hub.snapshot_download = lambda repo_id, *a, **k: local if repo_id == IC else _o(repo_id, *a, **k)
try: ic = AutoModel.from_pretrained(IC, revision=mi2.sha, trust_remote_code=True, token=tok)
finally: huggingface_hub.snapshot_download = _o
ic_engine_for("ctc")(items[0].path, items[0].language)
after = used()
print("\nGPU memory before load: %d MiB, after load + first call: %d MiB, change: %+d MiB" % (before, after, after - before))
print("-> IndicConformer ran on:", "GPU" if after - before > 500 else "CPU")

def whisper_default(path, lang):
    segs, _ = wm.transcribe(load_wav(path), language=lang, beam_size=5)
    return " ".join(s.text.strip() for s in segs)
sub = [i for i in items if i.language in ("te", "ml", "kn")]
res_w2 = run_stt(whisper_default, sub)
s2 = summarize(res_w2)
for k in ("te", "ml", "kn"):
    print("whisper DEFAULT decoding  %s  WER %.3f  CER %.3f  RTF %.3f  failed %d" % (k, s2[k]["wer"], s2[k]["cer"], s2[k]["rtf"], s2[k]["failed"]))
