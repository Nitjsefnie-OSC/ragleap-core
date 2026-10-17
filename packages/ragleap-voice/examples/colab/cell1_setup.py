# Colab Cell 1: setup and downloads. Run on a T4 GPU runtime.
# Order: create a short-lived read token, save it as the Colab secret HF_TOKEN (Notebook access on),
# run this cell, delete the secret and the token, then run Cell 2.
import subprocess, sys, os, json, pathlib, shutil, time

def run(*a, env=None, timeout=None): return subprocess.run(list(a), capture_output=True, text=True, env=env, timeout=timeout)
def need(ok, msg):
    if not ok: raise SystemExit(msg)

need(shutil.which("nvidia-smi"), "No GPU: Runtime > Change runtime type > T4 GPU, press Save, then rerun this cell")
from google.colab import userdata
try: tok = userdata.get("HF_TOKEN")
except Exception: raise SystemExit("Secret fetch failed: keep this tab in the foreground, check the key icon (HF_TOKEN present, Notebook access on), rerun")
need(tok, "HF_TOKEN is empty")

def pip(*pk):
    r = run(sys.executable, "-m", "pip", "install", "-q", *pk)
    need(r.returncode == 0, "pip failed:\n" + r.stderr[-800:])
t0 = time.time()
print("1/5 installing packages...")
pip("uv", "huggingface_hub", "soundfile")
pip("--force-reinstall", "--no-deps", "--no-cache-dir", "git+https://github.com/antonyrag/ragleap-core.git#subdirectory=packages/ragleap-voice")
pip("faster-whisper==1.1.1", "nvidia-cublas-cu12", "nvidia-cudnn-cu12")
pip("transformers==5.18.0", "onnxruntime-gpu==1.31.0", "onnx==1.20.1", "torchaudio")
run("apt-get", "update", "-qq"); run("apt-get", "install", "-y", "-qq", "espeak-ng")   # GPLv3, used by Kokoro's non-English paths: demo use only
if not shutil.which("espeak-ng"): print("WARNING: espeak-ng missing: Kokoro Hindi/Spanish/French/Italian/Portuguese will fail")

print("2/5 pulling Indic Parler-TTS and its tokenizer (hash-checked by ragleap-voice)...")
from ragleap_voice.manifest import load_manifest
by = {e.name: e for e in load_manifest()[0]}
P, T = by["indic-parler-tts"], by["flan-t5-large-tokenizer"]
need(P.revision and T.revision and P.depends_on == ("flan-t5-large-tokenizer",), "installed ragleap-voice lacks the pinned Parler entries")
base_env = {k: v for k, v in os.environ.items() if "TOKEN" not in k.upper()}
RV = "/content/rv_cache"
r = run(sys.executable, "-m", "ragleap_voice", "models", "pull", "indic-parler-tts", "--cache-dir", RV, "--allow-unverified", env=dict(base_env, HF_TOKEN=tok))
print("\n".join(r.stdout.strip().splitlines()[-3:]))
need(r.returncode == 0, "pull failed:\n" + r.stderr[-600:])
r = run(sys.executable, "-m", "ragleap_voice", "models", "verify", "indic-parler-tts", "--cache-dir", RV, env=base_env)
need(r.returncode == 0, "verify failed:\n" + (r.stderr or r.stdout)[-600:])

print("3/5 downloading IndicConformer (pinned revision, MIT)...")
from huggingface_hub import HfApi, snapshot_download
api = HfApi()
def lic(info):
    v = info.card_data.license if info.card_data else None
    return [x.lower() for x in ([v] if isinstance(v, str) else (v or []))]
IC, IC_REV = "ai4bharat/indic-conformer-600m-multilingual", "2a77d305038dfc502fd9464e7d028b90381976cb"
need(lic(api.model_info(IC, revision=IC_REV, token=tok)) == ["mit"], "IndicConformer licence is not MIT: STOP")
ICD = "/content/ic_model"
snapshot_download(IC, revision=IC_REV, token=tok, local_dir=ICD)

print("4/5 creating isolated engine environments (several minutes each)...")
def make_env(name, pkgs, post=None):
    d = "/content/venvs/" + name
    shutil.rmtree(d, ignore_errors=True)
    r = run(sys.executable, "-m", "uv", "venv", "--python", "3.11", d)
    if r.returncode: print("[%s] venv failed: %s" % (name, r.stderr[-300:])); return None
    py = d + "/bin/python"
    r = run(sys.executable, "-m", "uv", "pip", "install", "--python", py, *pkgs)
    if r.returncode: print("[%s] install failed: %s" % (name, r.stderr[-600:])); return None
    if post:
        try: post(py)
        except Exception as e: print("[%s] post-install step failed: %s" % (name, e))
    print("[%s] ready" % name); return py
def kokoro_post(py):
    run(sys.executable, "-m", "uv", "pip", "install", "--python", py, "pip")
    r = run(py, "-m", "spacy", "download", "en_core_web_sm")
    if r.returncode: raise RuntimeError(r.stderr[-300:])
parler_sha = run("git", "ls-remote", "https://github.com/huggingface/parler-tts.git", "HEAD").stdout.split()[0]
if not parler_sha.startswith("d108732"): print("NOTE: parler-tts upstream moved on since our tests (now %s)" % parler_sha[:10])
ENVS = {
    "kokoro": make_env("kokoro", ["kokoro>=0.9.2", "soundfile"], kokoro_post),
    "chatterbox": make_env("chatterbox", ["chatterbox-tts", "soundfile", "setuptools<81"]),
    "parler": make_env("parler", ["git+https://github.com/huggingface/parler-tts.git@" + parler_sha, "soundfile"]),
}

print("5/5 writing engine workers...")
PRE = r'''
import json, os, sys, time, traceback
import numpy as np, soundfile as sf, torch
SENT = "@@RV@@ "
def emit(obj):
    sys.stdout.write(SENT + json.dumps(obj) + "\n"); sys.stdout.flush()
def serve(load, synth):
    try:
        state = load()
    except Exception as e:
        traceback.print_exc()
        emit({"event": "load_error", "error": type(e).__name__ + ": " + str(e)[:300]}); sys.exit(2)
    emit({"event": "ready", "device": "cuda" if torch.cuda.is_available() else "cpu"})
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        req = json.loads(line)
        if req.get("op") == "quit": break
        try:
            t0 = time.perf_counter()
            audio, sr = synth(state, req)
            audio = np.clip(np.asarray(audio, dtype="float32").reshape(-1), -1, 1)
            sf.write(req["out"], audio, sr, subtype="PCM_16")
            emit({"id": req["id"], "ok": True, "seconds": time.perf_counter() - t0, "audio_s": len(audio) / sr})
        except Exception as e:
            traceback.print_exc()
            emit({"id": req.get("id"), "ok": False, "error": type(e).__name__ + ": " + str(e)[:300]})
'''
BODY = {
"kokoro": r'''
from kokoro import KPipeline
def load(): return {"a": KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")}
def synth(P, r):
    lc = r["lc"]
    if lc not in P: P[lc] = KPipeline(lang_code=lc, repo_id="hexgrad/Kokoro-82M")
    parts = []
    for _, _, a in P[lc](r["text"], voice=r["voice"], speed=float(r.get("speed", 1.0))):
        if a is not None: parts.append(a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a))
    if not parts: raise RuntimeError("no audio produced")
    return np.concatenate(parts), 24000
serve(load, synth)
''',
"chatterbox": r'''
import inspect
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
def load():
    m = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    return m, set(inspect.signature(m.generate).parameters)
def synth(st, r):
    m, params = st
    kw = {"language_id": r["lang"]}
    if r.get("ref"):
        if "audio_prompt_path" not in params: raise RuntimeError("this chatterbox version has no audio_prompt_path")
        kw["audio_prompt_path"] = r["ref"]
    if "exaggeration" in params: kw["exaggeration"] = float(r.get("exaggeration", 0.5))
    if "cfg_weight" in params: kw["cfg_weight"] = float(r.get("cfg_weight", 0.5))
    wav = m.generate(r["text"], **kw)
    return wav.squeeze().cpu().numpy(), m.sr
serve(load, synth)
''',
"parler": r'''
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
pdir, tdir = sys.argv[1], sys.argv[2]
dev = "cuda" if torch.cuda.is_available() else "cpu"
def load():
    m = ParlerTTSForConditionalGeneration.from_pretrained(pdir, local_files_only=True).to(dev)
    return m, AutoTokenizer.from_pretrained(pdir, local_files_only=True), AutoTokenizer.from_pretrained(tdir, local_files_only=True)
def synth(st, r):
    m, ptok, dtok = st
    d = dtok(r["desc"], return_tensors="pt").to(dev); p = ptok(r["text"], return_tensors="pt").to(dev)
    g = m.generate(input_ids=d.input_ids, attention_mask=d.attention_mask, prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
    return g.cpu().numpy().squeeze(), m.config.sampling_rate
serve(load, synth)
''',
}
wd = pathlib.Path("/content/rv_workers"); wd.mkdir(exist_ok=True)
for k, body in BODY.items():
    (wd / ("engine_" + k + ".py")).write_text(PRE + body, encoding="utf-8")
state = {"envs": ENVS, "parler_dir": "%s/models/indic-parler-tts/%s" % (RV, P.revision),
         "tok_dir": "%s/models/flan-t5-large-tokenizer/%s" % (RV, T.revision), "ic_dir": ICD,
         "scripts": {k: str(wd / ("engine_" + k + ".py")) for k in BODY}}
json.dump(state, open("/content/rv_state.json", "w"))
# Drop the token from this kernel's memory: Cell 2 loads code that runs inside this process.
del tok, api
print("\nSETUP DONE in %.1f min. Engines installed: %s" % ((time.time() - t0) / 60, {k: bool(v) for k, v in ENVS.items()}))
print("NEXT: delete the HF_TOKEN secret (key icon) and the token on huggingface.co, then run Cell 2.")
