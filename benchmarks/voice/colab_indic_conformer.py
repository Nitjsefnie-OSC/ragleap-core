"""Reproduces the IndicConformer-600M vs Whisper large-v3 comparison in benchmarks/voice/README.md.

Run in Google Colab (T4 GPU runtime), pasted into one cell. Needs network.
Prerequisite: a Hugging Face account that has accepted the conditions on
ai4bharat/indic-conformer-600m-multilingual, and a read token stored in Colab
Secrets as HF_TOKEN with Notebook access on. Delete the token afterwards: the
model's own repo code runs inside this session (trust_remote_code).
"""
import subprocess
import sys
import wave
import importlib.metadata as md

# Rebuilds the test set and the Whisper results if the runtime has none (about 5 minutes)
if "items" not in globals():
    import urllib.request
    src = urllib.request.urlopen(
        "https://raw.githubusercontent.com/ragleap/ragleap-core/main/benchmarks/voice/colab_whisper_baseline.py"
    ).read().decode()
    exec(compile(src, "colab_whisper_baseline.py", "exec"))

r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers==5.18.0",
                    "onnxruntime-gpu==1.31.0", "onnx==1.20.1", "torchaudio"],
                   capture_output=True, text=True)
assert r.returncode == 0, r.stderr[-800:]

from google.colab import userdata
try:
    tok = userdata.get("HF_TOKEN")
except Exception:
    raise SystemExit("Add the secret HF_TOKEN (key icon) and switch Notebook access on, then rerun")

import numpy as np
import torch
import huggingface_hub
from huggingface_hub import HfApi, snapshot_download

MODEL = "ai4bharat/indic-conformer-600m-multilingual"
mi2 = HfApi().model_info(MODEL, token=tok)
lic2 = mi2.card_data.license
assert [x.lower() for x in ([lic2] if isinstance(lic2, str) else lic2)] == ["mit"], "licence is not MIT: STOP"
print("revision:", mi2.sha)

# onnxruntime 1.31 refuses weight files that resolve outside the model folder, and the
# Hugging Face cache stores them as symlinks into blobs/. Use a normal folder of real files.
local = snapshot_download(MODEL, revision=mi2.sha, token=tok, local_dir="/content/ic_model")

from transformers import AutoModel
for k in [k for k in sys.modules if "model_onnx" in k]:
    del sys.modules[k]
_orig = huggingface_hub.snapshot_download
huggingface_hub.snapshot_download = lambda repo_id, *a, **k: local if repo_id == MODEL else _orig(repo_id, *a, **k)
try:
    ic = AutoModel.from_pretrained(MODEL, revision=mi2.sha, trust_remote_code=True, token=tok)
finally:
    huggingface_hub.snapshot_download = _orig

sel = [i for i in items if i.language in ("hi", "ta")]


def make_engine(mode):
    def engine(path, lang):
        with wave.open(path, "rb") as wf:
            assert wf.getframerate() == 16000 and wf.getnchannels() == 1 and wf.getsampwidth() == 2
            audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float32") / 32768.0
        out = ic(torch.from_numpy(audio).unsqueeze(0), lang, mode)
        if isinstance(out, (list, tuple)):
            out = out[0]
        return str(out).strip()
    return engine


results = {}
for mode in ("ctc", "rnnt"):
    eng = make_engine(mode)
    eng(sel[0].path, sel[0].language)  # warm-up, not timed
    rows_m = run_stt(eng, sel)
    meta2 = environment_info(
        gpu=gpu, engine="transformers " + md.version("transformers") + " + onnxruntime-gpu " + md.version("onnxruntime-gpu"),
        model=MODEL, model_revision=mi2.sha, decoding=mode,
        device="unlabeled: chosen by the repo's own code, not verified",
        dataset="google/fleurs test, first 20 per language (hi, ta only)", harness_commit_main=main_sha)
    write_results("/content/results", "indic-conformer-600m-" + mode, rows_m, meta2)
    results[mode] = rows_m
    bad = [x["error"] for x in rows_m if x["error"]]
    if bad:
        print(mode, "failures:", len(bad), "first:", bad[0][:200])


def show(name, rows):
    s = summarize([x for x in rows if x["language"] in ("hi", "ta")])
    for k in ("hi", "ta"):
        print(f"{name:32s} {k}  WER {s[k]['wer']:.3f}  CER {s[k]['cer']:.3f}  RTF {s[k]['rtf']:.3f}  failed {s[k]['failed']}")


print()
show("whisper-large-v3 (fp16, T4)", res)
show("indic-conformer-600m CTC", results["ctc"])
show("indic-conformer-600m RNNT", results["rnnt"])
