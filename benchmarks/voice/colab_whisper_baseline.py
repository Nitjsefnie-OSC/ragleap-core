"""Reproduces the Whisper large-v3 baseline described in benchmarks/voice/README.md.

Run in Google Colab with a T4 GPU runtime, pasted into one cell. Needs network.
Results are written to /content/results. The licence gates stop the run if FLEURS
is not CC-BY-4.0 or the model is not MIT.
"""
import csv
import ctypes
import glob
import importlib.metadata as md
import pathlib
import site
import subprocess
import sys
import wave


def sh(*a):
    subprocess.run(list(a), check=True)


def out(*a):
    try:
        return subprocess.run(list(a), capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        return ""


sh(sys.executable, "-m", "pip", "install", "-q", "faster-whisper==1.1.1", "datasets==3.6.0", "soundfile",
   "nvidia-cublas-cu12", "nvidia-cudnn-cu12",
   "git+https://github.com/antonyrag/ragleap-core.git#subdirectory=packages/ragleap-voice")

gpu = out("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader")
assert gpu, "No GPU: Runtime > Change runtime type > T4 GPU"
main_sha = out("git", "ls-remote", "https://github.com/antonyrag/ragleap-core.git", "refs/heads/main").split()[0]

# Colab images may lack the CUDA 12 libraries CTranslate2 needs: preload the pip ones.
libs = []
for r in site.getsitepackages() + [site.getusersitepackages()]:
    libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True)
    libs += sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
loaded = []
for p in libs:
    try:
        ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
        loaded.append(p.split("/")[-1])
    except OSError as e:
        print("could not load", p.split("/")[-1], "-", str(e)[:80])
assert any(x.startswith("libcublas.so") for x in loaded), "cuBLAS not loaded"

from huggingface_hub import HfApi  # noqa: E402
api = HfApi()


def lic(info):
    v = info.card_data.license
    return [x.lower() for x in ([v] if isinstance(v, str) else (v or []))]


assert lic(api.dataset_info("google/fleurs")) == ["cc-by-4.0"], "FLEURS licence is not CC-BY-4.0: STOP"
mi = api.model_info("Systran/faster-whisper-large-v3")
assert lic(mi) == ["mit"], "Model licence is not MIT: STOP"

import numpy as np  # noqa: E402
from datasets import load_dataset  # noqa: E402

LANGS = {"en": "en_us", "hi": "hi_in", "ta": "ta_in"}
N = 20
root = pathlib.Path("/content/fleurs20")
root.mkdir(exist_ok=True)
rows = []
for code, cfg in LANGS.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True)
    for i, ex in enumerate(ds):
        if i >= N:
            break
        a = ex["audio"]
        assert a["sampling_rate"] == 16000
        pcm = (np.clip(a["array"], -1, 1) * 32767).astype("<i2")
        name = f"{code}_{i:02d}.wav"
        with wave.open(str(root / name), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm.tobytes())
        rows.append([f"{code}_{i:02d}", name, ex["transcription"], code, "CC-BY-4.0",
                     "google/fleurs test, config " + cfg])
with open(root / "manifest.csv", "w", encoding="utf-8", newline="") as f:
    cw = csv.writer(f)
    cw.writerow(["id", "path", "reference", "language", "license", "source"])
    cw.writerows(rows)

from ragleap_voice.bench import load_manifest, run_stt, summarize, environment_info, write_results  # noqa: E402
items, problems = load_manifest(root / "manifest.csv")
assert not problems, problems

from faster_whisper import WhisperModel  # noqa: E402
model = WhisperModel("large-v3", device="cuda", compute_type="float16")


def engine(path, lang):
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1 and wf.getsampwidth() == 2
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float32") / 32768.0
    segs, _ = model.transcribe(audio, language=lang, beam_size=5, temperature=0.0,
                               condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)


engine(items[0].path, items[0].language)  # warm-up, not timed
res = run_stt(engine, items)

meta = environment_info(
    gpu=gpu, engine="faster-whisper " + md.version("faster-whisper"),
    model="Systran/faster-whisper-large-v3", model_revision=mi.sha, compute_type="float16",
    beam_size=5, temperature=0.0, audio_input="numpy float32 from 16 kHz WAV (no av decode)",
    cuda_libs="pip nvidia-cublas-cu12 " + md.version("nvidia-cublas-cu12")
              + ", nvidia-cudnn-cu12 " + md.version("nvidia-cudnn-cu12"),
    dataset="google/fleurs test, first 20 per language",
    harness_commit_main=main_sha, datasets_version=md.version("datasets"))
csvp, jsonp = write_results("/content/results", "whisper-large-v3-ct2-fp16", res, meta)

for k, v in summarize(res).items():
    print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})
print("GPU:", gpu, "| model rev:", mi.sha[:10], "| harness main:", main_sha[:10])
