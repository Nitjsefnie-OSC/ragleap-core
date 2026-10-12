"""TTS round-trip measurement: Indic Parler-TTS, Kokoro-82M and Chatterbox Multilingual.

Run in Google Colab (T4 GPU runtime), pasted into one cell, about 60 minutes. Keep the tab in the
foreground at the start: the Hugging Face token is read from Colab Secrets (HF_TOKEN, Notebook
access on) in the first seconds. Prerequisite: a Hugging Face account that has accepted the
conditions on ai4bharat/indic-parler-tts and ai4bharat/indic-conformer-600m-multilingual.
Delete the token afterwards. Each TTS system runs in its own Python 3.11 environment that is
started without any environment variable containing TOKEN.
NOTE: assembled from three cells that were each run successfully; this combined script has not
been run end to end as one piece.
"""
import subprocess, sys, os, re, json, pathlib, glob, ctypes, site, random, time, importlib.metadata as md

N = 20
LANGS = {"hi": "hi_in", "ta": "ta_in", "te": "te_in", "ml": "ml_in", "kn": "kn_in", "en": "en_us"}

def run(*a, **k): return subprocess.run(list(a), capture_output=True, text=True, **k)
def pip(*pk):
    r = run(sys.executable, "-m", "pip", "install", "-q", *pk)
    assert r.returncode == 0, r.stderr[-800:]

from google.colab import userdata
try: tok = userdata.get("HF_TOKEN")
except Exception: raise SystemExit("Secret fetch failed: keep this tab in the foreground, check the key icon (HF_TOKEN present, Notebook access on), rerun")
pip("datasets==3.6.0", "soundfile", "uv", "huggingface_hub")

def smi(q):
    try: return run("nvidia-smi", "--query-gpu=" + q, "--format=csv,noheader,nounits").stdout.strip()
    except FileNotFoundError: return ""
gpu = smi("name,memory.total")
assert gpu, "No GPU: Runtime > Change runtime type > T4 GPU"
main_sha = run("git", "ls-remote", "https://github.com/antonyrag/ragleap-core.git", "refs/heads/main").stdout.split()[0]
parler_sha = run("git", "ls-remote", "https://github.com/huggingface/parler-tts.git", "HEAD").stdout.split()[0]

from huggingface_hub import HfApi, snapshot_download
api = HfApi()
def lic(info):
    v = info.card_data.license if info.card_data else None
    return [x.lower() for x in ([v] if isinstance(v, str) else (v or []))]
assert lic(api.dataset_info("google/fleurs")) == ["cc-by-4.0"], "FLEURS licence changed: STOP"
revs = {}
for repo, want in (("ai4bharat/indic-parler-tts", "apache-2.0"), ("hexgrad/Kokoro-82M", "apache-2.0"), ("ResembleAI/chatterbox", "mit")):
    info = api.model_info(repo, token=tok); assert lic(info) == [want], (repo, lic(info)); revs[repo] = info.sha
print("model revisions:", {k: v[:10] for k, v in revs.items()}, "| parler-tts commit:", parler_sha[:10])

# Prompts: FLEURS test-set SENTENCE TEXT only (no audio). Sentences with digits, or Latin letters in Indic
# text, are skipped because the WER normalizer does not unify numbers or transliterations.
from datasets import load_dataset
def ok_text(t, lang):
    if re.search(r"\d", t): return False
    if lang != "en" and re.search(r"[A-Za-z]", t): return False
    return 6 <= len(t.split()) <= 30
prompts = []
for lang, cfg in LANGS.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True).remove_columns(["audio"])
    seen, k = set(), 0
    for ex in ds:
        t = ex["raw_transcription"].strip()
        if t in seen or not ok_text(t, lang): continue
        seen.add(t); prompts.append({"id": "%s_%02d" % (lang, k), "lang": lang, "text": t}); k += 1
        if k >= N: break
    print(lang, k, "prompts")
text_of = {p["id"]: p["text"] for p in prompts}
files = api.list_repo_files("hexgrad/Kokoro-82M")
hv = sorted(f[7:-3] for f in files if f.startswith("voices/h") and f.endswith(".pt"))
assert hv, "no Hindi voice in the Kokoro repo"
ev = "af_heart" if "voices/af_heart.pt" in files else sorted(f[7:-3] for f in files if f.startswith("voices/a"))[0]
json.dump({"items": prompts, "voices": {"kokoro": {"hi": hv[0], "en": ev}}}, open("/content/tts_jobs.json", "w"))

PRE = r'''
import json, os, sys, time, random
import numpy as np, soundfile as sf, torch
import importlib.metadata as md
JOBS = json.load(open("/content/tts_jobs.json"))
dev = "cuda" if torch.cuda.is_available() else "cpu"
def run_jobs(system, langs, load, synth, extra):
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    out = "/content/tts_out/" + system; os.makedirs(out, exist_ok=True)
    items = [j for j in JOBS["items"] if j["lang"] in langs]
    sync = torch.cuda.synchronize if torch.cuda.is_available() else (lambda: None)
    state = load()
    synth(state, items[0])  # warm-up, not timed
    rows = []
    for j in items:
        r = {"id": j["id"], "lang": j["lang"], "gen_s": None, "audio_s": None, "error": ""}
        try:
            sync(); t0 = time.perf_counter()
            audio, sr = synth(state, j)
            sync(); r["gen_s"] = time.perf_counter() - t0
            audio = np.clip(np.asarray(audio, dtype="float32").reshape(-1), -1, 1)
            r["audio_s"] = len(audio) / sr
            sf.write(out + "/" + j["id"] + ".wav", audio, sr, subtype="PCM_16")
        except Exception as e:
            r["error"] = type(e).__name__ + ": " + str(e)[:200]
        rows.append(r)
    meta = {"system": system, "device": dev, "torch": torch.__version__, "python": sys.version.split()[0],
            "gpu": torch.cuda.get_device_name(0) if dev == "cuda" else "none"}
    meta.update(extra())
    json.dump({"meta": meta, "rows": rows}, open(out + "/timing.json", "w"))
    print(system, "done:", sum(1 for r in rows if not r["error"]), "of", len(rows))
'''
W_KOKORO = r'''
from kokoro import KPipeline
V = JOBS["voices"]["kokoro"]
def load():
    return {"en": KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M"), "hi": KPipeline(lang_code="h", repo_id="hexgrad/Kokoro-82M")}
def synth(P, j):
    parts = []
    for _, _, a in P[j["lang"]](j["text"], voice=V[j["lang"]]):
        if a is not None:
            parts.append(a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a))
    return np.concatenate(parts), 24000
run_jobs("kokoro", ("hi", "en"), load, synth, lambda: {"kokoro": md.version("kokoro"), "misaki": md.version("misaki"), "voices": V})
'''
W_CHATTERBOX = r'''
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
def load(): return ChatterboxMultilingualTTS.from_pretrained(device=dev)
def synth(m, j):
    wav = m.generate(j["text"], language_id=j["lang"])
    return wav.squeeze().cpu().numpy(), m.sr
run_jobs("chatterbox", ("hi", "en"), load, synth, lambda: {"chatterbox-tts": md.version("chatterbox-tts")})
'''
PM = "/content/parler_model"
W_PARLER = r'''
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
M = "__PM__"
DESC = "A female speaker delivers a slightly expressive and animated speech with a moderate speed and pitch. The recording is of very high quality, with the speaker's voice sounding clear and very close up."
def load():
    m = ParlerTTSForConditionalGeneration.from_pretrained(M).to(dev)
    return m, AutoTokenizer.from_pretrained(M), AutoTokenizer.from_pretrained(m.config.text_encoder._name_or_path)
def synth(st, j):
    m, tok, dtok = st
    d = dtok(DESC, return_tensors="pt").to(dev); p = tok(j["text"], return_tensors="pt").to(dev)
    g = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask, prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
    return g.cpu().numpy().squeeze(), m.config.sampling_rate
import transformers
run_jobs("parler", ("hi", "ta", "te", "ml", "kn", "en"), load, synth, lambda: {"transformers": transformers.__version__, "description": DESC})
'''.replace("__PM__", PM)

def make_env(name, pkgs):
    d = "/content/venvs/" + name
    r = run(sys.executable, "-m", "uv", "venv", "--python", "3.11", d)
    if r.returncode: return None, r.stderr[-600:]
    r = run(sys.executable, "-m", "uv", "pip", "install", "--python", d + "/bin/python", *pkgs)
    return (d + "/bin/python", None) if r.returncode == 0 else (None, r.stderr[-1500:])

clean_env = {k: v for k, v in os.environ.items() if "TOKEN" not in k.upper()}
def stage(name, pkgs, body, post=None):
    t0 = time.time(); print("\n[%s] installing (several minutes)..." % name)
    py, err = make_env(name, pkgs)
    if not py:
        print("[%s] INSTALL FAILED:\n%s" % (name, err)); return False
    if post: post(py)
    p = pathlib.Path("/content/workers"); p.mkdir(exist_ok=True)
    script = p / ("run_" + name + ".py")           # never named after the library it imports
    script.write_text(PRE + body, encoding="utf-8")
    print("[%s] installed in %.0fs, synthesizing..." % (name, time.time() - t0))
    try:
        r = run(py, str(script), timeout=5400, env=clean_env)
    except subprocess.TimeoutExpired:
        print("[%s] TIMED OUT after 90 minutes" % name); return False
    ok = r.returncode == 0
    print("[%s] %s in %.0fs" % (name, "ok" if ok else "FAILED", time.time() - t0))
    tail = r.stdout.strip().splitlines()[-3:] if ok else r.stderr.strip().splitlines()[-12:]
    print("    " + "\n    ".join(tail))
    return ok

def kokoro_post(py):
    run(sys.executable, "-m", "uv", "pip", "install", "--python", py, "pip")
    r = run(py, "-m", "spacy", "download", "en_core_web_sm")
    print("    kokoro spaCy model:", "ok" if r.returncode == 0 else r.stderr[-400:])

run("apt-get", "update", "-qq")
run("apt-get", "install", "-y", "-qq", "espeak-ng")  # GPLv3, used by Kokoro's Hindi path: measurement only
stage("kokoro", ["kokoro>=0.9.2", "soundfile"], W_KOKORO, kokoro_post)
stage("chatterbox", ["chatterbox-tts", "soundfile", "setuptools<81"], W_CHATTERBOX)
# Gated Parler repo: downloaded here with the token, so the TTS environment never sees the token
try:
    snapshot_download("ai4bharat/indic-parler-tts", revision=revs["ai4bharat/indic-parler-tts"], token=tok, local_dir=PM)
    stage("parler", ["git+https://github.com/huggingface/parler-tts.git@" + parler_sha, "soundfile"], W_PARLER)
except Exception as e:
    print("Parler skipped (accept the model conditions with the same HF account):", str(e)[:300])

systems = [s for s in ("kokoro", "chatterbox", "parler") if os.path.exists("/content/tts_out/%s/timing.json" % s)]
assert systems, "no TTS system produced output: read the messages above"
print("\nsystems with output:", systems)

# ---- Judges: IndicConformer (Indian languages) and Whisper large-v3 (English) ----
pip("faster-whisper==1.1.1", "nvidia-cublas-cu12", "nvidia-cudnn-cu12",
    "git+https://github.com/antonyrag/ragleap-core.git#subdirectory=packages/ragleap-voice")
pip("transformers==5.18.0", "onnxruntime-gpu==1.31.0", "onnx==1.20.1", "torchaudio")
libs = []
for r in site.getsitepackages() + [site.getusersitepackages()]:
    libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True)
    libs += sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
loaded = []
for p in libs:
    try: ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL); loaded.append(p.split("/")[-1])
    except OSError: pass
assert any(x.startswith("libcublas.so") for x in loaded), "cuBLAS not loaded"

import numpy as np, torch, torchaudio, soundfile as sf, huggingface_hub
IC = "ai4bharat/indic-conformer-600m-multilingual"
mi2 = api.model_info(IC, token=tok); assert lic(mi2) == ["mit"], "IndicConformer licence changed: STOP"
mw = api.model_info("Systran/faster-whisper-large-v3"); assert lic(mw) == ["mit"], "Whisper licence changed: STOP"
from faster_whisper import WhisperModel
wm = WhisperModel("large-v3", device="cuda", compute_type="float16")
local = snapshot_download(IC, revision=mi2.sha, token=tok, local_dir="/content/ic_model")
from transformers import AutoModel
for k in [k for k in sys.modules if "model_onnx" in k]: del sys.modules[k]
_orig = huggingface_hub.snapshot_download
huggingface_hub.snapshot_download = lambda repo_id, *a, **k: local if repo_id == IC else _orig(repo_id, *a, **k)
try: ic = AutoModel.from_pretrained(IC, revision=mi2.sha, trust_remote_code=True, token=tok)
finally: huggingface_hub.snapshot_download = _orig

def to16k(path):
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    x = torch.from_numpy(x.mean(axis=1))
    if sr != 16000: x = torchaudio.functional.resample(x, sr, 16000)
    return x.numpy().astype("float32")
def judge(path, lang):
    a = to16k(path)
    if lang == "en":
        segs, _ = wm.transcribe(a, language="en", beam_size=5)
        return " ".join(s.text.strip() for s in segs)
    out = ic(torch.from_numpy(a).unsqueeze(0), lang, "rnnt")
    return str(out[0] if isinstance(out, (list, tuple)) else out).strip()

from ragleap_voice.bench import TestItem, run_stt, environment_info, write_results
allrows = {}
for s in systems:
    tj = json.load(open("/content/tts_out/%s/timing.json" % s))
    its = [TestItem(r["id"], "/content/tts_out/%s/%s.wav" % (s, r["id"]), text_of[r["id"]], r["lang"], "CC-BY-4.0",
                    "FLEURS sentence text, synthesized by " + s) for r in tj["rows"] if not r["error"] and r["id"] in text_of]
    rows = run_stt(judge, its)
    allrows[s] = (rows, tj)
    print(s, "worker meta:", {k: v for k, v in tj["meta"].items() if k != "description"})
    write_results("/content/results", "tts-roundtrip-" + s, rows,
        environment_info(gpu=gpu, judge_indic="indic-conformer-600m RNNT", judge_en="whisper-large-v3 beam5",
                         ic_revision=mi2.sha, whisper_revision=mw.sha, tts_meta=json.dumps(tj["meta"]),
                         tts_revisions=json.dumps(revs), parler_tts_commit=parler_sha, harness_commit_main=main_sha))

def ci(vals, B=2000, seed=0):
    rnd = random.Random(seed); n = len(vals); out = []
    for _ in range(B):
        smp = [vals[rnd.randrange(n)] for _ in range(n)]
        out.append(sum(e for e, _ in smp) / sum(m for _, m in smp))
    out.sort(); return out[int(0.025 * B)], out[int(0.975 * B)]
def pc(x): return "%5.1f%%" % (100 * x)

print("\nround-trip results (text -> TTS audio -> judge ASR -> compare with the original text)")
for s in systems:
    rows, tj = allrows[s]
    for lang in LANGS:
        trows = [r for r in tj["rows"] if r["lang"] == lang]
        if not trows: continue
        ok = [r for r in rows if r["language"] == lang and not r["error"]]
        tts_err = sum(1 for r in trows if r["error"])
        asr_err = sum(1 for r in rows if r["language"] == lang and r["error"])
        if not ok:
            print("  %-10s %s  no usable clips (tts errors %d, judge errors %d)" % (s, lang, tts_err, asr_err)); continue
        w = [(r["word_errors"], r["ref_words"]) for r in ok]; c = [(r["char_errors"], r["ref_chars"]) for r in ok]
        wl, wh = ci(w)
        good = [r for r in trows if not r["error"]]
        gen = sum(r["gen_s"] for r in good); aud = sum(r["audio_s"] for r in good)
        print("  %-10s %s  WER %s [%s,%s]  CER %s  gen-RTF %.2f  mean-audio %.1fs  tts-errors %d  judge-errors %d  n=%d" % (
            s, lang, pc(sum(e for e, _ in w) / sum(m for _, m in w)), pc(wl), pc(wh),
            pc(sum(e for e, _ in c) / sum(m for _, m in c)), gen / aud, aud / len(good), tts_err, asr_err, len(ok)))
print("\nGPU:", gpu)
