"""Whisper large-v3 on 12 FLEURS languages from several regions (60 clips each).

Run in Google Colab (T4 GPU runtime), pasted into one cell. No token needed: FLEURS and the model are not gated.
The model is pulled through 'ragleap-voice models pull' (pinned revision, hash-checked, tagged lock) and loaded from
that folder. Licence gates stop the run if FLEURS is not CC-BY-4.0 or the model is not MIT.
Run colab_pilot12_analysis.py in the same session afterwards: it reads the variables and the CSV this script leaves.
"""
import csv, ctypes, glob, importlib.metadata as md, pathlib, site, subprocess, sys, wave

def sh(*a): subprocess.run(list(a), check=True)
def out(*a):
    try: return subprocess.run(list(a), capture_output=True, text=True).stdout.strip()
    except FileNotFoundError: return ""

sh(sys.executable, "-m", "pip", "install", "-q", "faster-whisper==1.1.1", "datasets==3.6.0", "soundfile",
   "nvidia-cublas-cu12", "nvidia-cudnn-cu12", "--force-reinstall", "--no-deps", "--no-cache-dir",
   "git+https://github.com/antonyrag/ragleap-core.git#subdirectory=packages/ragleap-voice")
sh(sys.executable, "-m", "pip", "install", "-q", "faster-whisper==1.1.1", "datasets==3.6.0", "soundfile",
   "nvidia-cublas-cu12", "nvidia-cudnn-cu12")
gpu = out("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader")
assert gpu, "No GPU: Runtime > Change runtime type > T4 GPU, press Save"
main_sha = out("git", "ls-remote", "https://github.com/antonyrag/ragleap-core.git", "refs/heads/main").split()[0]

libs = []
for r in site.getsitepackages() + [site.getusersitepackages()]:
    libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True)
    libs += sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
loaded = []
for p in libs:
    try: ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL); loaded.append(p.split("/")[-1])
    except OSError as e: print("could not load", p.split("/")[-1], str(e)[:80])
assert any(x.startswith("libcublas.so") for x in loaded), "cuBLAS not loaded"

from huggingface_hub import HfApi
api = HfApi()
def lic(info):
    v = info.card_data.license
    return [x.lower() for x in ([v] if isinstance(v, str) else (v or []))]
assert lic(api.dataset_info("google/fleurs")) == ["cc-by-4.0"], "FLEURS licence is not CC-BY-4.0: STOP"
assert lic(api.model_info("Systran/faster-whisper-large-v3")) == ["mit"], "Whisper licence is not MIT: STOP"

RV = "/content/rv_cache"
r = subprocess.run([sys.executable, "-m", "ragleap_voice", "models", "pull", "whisper-large-v3",
                    "--cache-dir", RV, "--allow-unverified"], capture_output=True, text=True)
print(r.stdout[-600:]); print(r.stderr[-600:])
assert r.returncode == 0, "pull failed: stop here and send this output"
from ragleap_voice.manifest import load_manifest
W = {e.name: e for e in load_manifest()[0]}["whisper-large-v3"]
MODEL_DIR = "%s/models/whisper-large-v3/%s" % (RV, W.revision)
assert pathlib.Path(MODEL_DIR, "model.bin").is_file(), MODEL_DIR

import numpy as np
from datasets import load_dataset, get_dataset_config_names
from faster_whisper import WhisperModel
model = WhisperModel(MODEL_DIR, device="cuda", compute_type="float16")
supported = set(getattr(model, "supported_languages", []) or [])

N = 60
PILOT = {"es": "es_419", "fr": "fr_fr", "pt": "pt_br", "ru": "ru_ru", "tr": "tr_tr", "ar": "ar_eg",
         "id": "id_id", "vi": "vi_vn", "ja": "ja_jp", "sw": "sw_ke", "yo": "yo_ng", "am": "am_et"}
configs = set(get_dataset_config_names("google/fleurs", trust_remote_code=True))
LANGS = {}
for code, cfg in PILOT.items():
    if cfg not in configs: print("SKIP", code, ": no FLEURS config", cfg)
    elif supported and code not in supported: print("SKIP", code, ": not a Whisper language code")
    else: LANGS[code] = cfg
print("languages:", LANGS)

root = pathlib.Path("/content/fleurs_pilot"); root.mkdir(exist_ok=True)
rows = []
for code, cfg in LANGS.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True)
    for i, ex in enumerate(ds):
        if i >= N: break
        a = ex["audio"]; assert a["sampling_rate"] == 16000
        pcm = (np.clip(a["array"], -1, 1) * 32767).astype("<i2")
        name = "%s_%02d.wav" % (code, i)
        with wave.open(str(root / name), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(pcm.tobytes())
        rows.append(["%s_%02d" % (code, i), name, ex["transcription"], code, "CC-BY-4.0", "google/fleurs test, config " + cfg])
with open(root / "manifest.csv", "w", encoding="utf-8", newline="") as f:
    cw = csv.writer(f); cw.writerow(["id", "path", "reference", "language", "license", "source"]); cw.writerows(rows)

from ragleap_voice.bench import load_manifest as load_items, run_stt, summarize, environment_info, write_results
items, problems = load_items(root / "manifest.csv")
assert not problems, problems

def engine(path, lang):
    with wave.open(path, "rb") as wf:
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float32") / 32768.0
    segs, _ = model.transcribe(audio, language=lang, beam_size=5, temperature=0.0, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)

engine(items[0].path, items[0].language)  # warm-up, not timed
res = run_stt(engine, items)
meta = environment_info(gpu=gpu, engine="faster-whisper " + md.version("faster-whisper"),
    model="Systran/faster-whisper-large-v3", model_revision=W.revision, compute_type="float16", beam_size=5, temperature=0.0,
    model_source="ragleap-voice models pull (hash-checked, tagged lock)", dataset="google/fleurs test, first %d per language" % N,
    harness_commit_main=main_sha, datasets_version=md.version("datasets"), languages=",".join(LANGS))
csvp, jsonp = write_results("/content/results", "whisper-large-v3-pilot12", res, meta)
for k, v in summarize(res).items():
    print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})
print("CSV:", csvp); print(open(csvp, encoding="utf-8").read()[:700])
print("GPU:", gpu, "| model rev:", W.revision[:10], "| harness main:", main_sha[:10])
