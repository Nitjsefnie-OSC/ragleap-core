"""Noise, telephone audio and two denoisers in front of Whisper large-v3 (first run). T4 GPU runtime, no token.

Whisper large-v3 is pulled through 'ragleap-voice models pull' (as in colab_pilot12.py). RNNoise v0.2 (BSD-3-Clause per GitHub)
is built from source; DeepFilterNet 0.5.6 (code MIT or Apache-2.0 per its README) runs in an isolated Python 3.11 environment.
FLEURS test clips (CC-BY-4.0): en_us, es_419, ru_ru, first 30 per language; babble is made from clips 30 to 59 of the same language.
Conditions: clean; white noise 10 dB; babble 10 dB; babble 5 dB; telephone (babble 10 dB, then 8 kHz mu-law, back to 16 kHz).
FIRST RUN, NO LEVEL FIX: DeepFilterNet3 produced silent output for the quietest clips (see colab_noise_pilot_diagnostics.py), so its
numbers from this run are an artefact and are not reported. Run colab_noise_pilot_levelfixed.py in the same session afterwards.
"""
import subprocess, sys, os, glob, ctypes, site, json, csv, random, time, unicodedata, hashlib, shlex, importlib.metadata as md
def sh(cmd, timeout=3600):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)
def need(ok, msg):
    if not ok: raise SystemExit(msg)
need(sh("nvidia-smi -L")[0] == 0, "No GPU: Runtime > Change runtime type > T4 GPU, press Save")
rc, o = sh("pip install -q faster-whisper==1.1.1 datasets==3.6.0 soundfile nvidia-cublas-cu12 nvidia-cudnn-cu12 uv"); need(rc == 0, o[-500:])
rc, o = sh("pip install -q --force-reinstall --no-deps --no-cache-dir 'git+https://github.com/ragleap/ragleap-core.git#subdirectory=packages/ragleap-voice'"); need(rc == 0, o[-500:])
libs = []
for r in site.getsitepackages() + [site.getusersitepackages()]:
    libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True)
    libs += sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
loaded = []
for p in libs:
    try: ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL); loaded.append(p.split("/")[-1])
    except OSError: pass
need(any(x.startswith("libcublas.so") for x in loaded), "cuBLAS not loaded")
from huggingface_hub import HfApi
api = HfApi()
def lic(info):
    v = info.card_data.license
    return [x.lower() for x in ([v] if isinstance(v, str) else (v or []))]
need(lic(api.dataset_info("google/fleurs")) == ["cc-by-4.0"], "FLEURS licence is not CC-BY-4.0: STOP")
need(lic(api.model_info("Systran/faster-whisper-large-v3")) == ["mit"], "Whisper licence is not MIT: STOP")
main_sha = sh("git ls-remote https://github.com/ragleap/ragleap-core.git refs/heads/main")[1].split()[0]

# Whisper through ragleap-voice (pinned, hash-checked, tagged lock), as in the pilot
RV = "/content/rv_cache"
rc, o = sh("%s -m ragleap_voice models pull whisper-large-v3 --cache-dir %s --allow-unverified" % (sys.executable, RV)); need(rc == 0, "pull failed:\n" + o[-600:])
from ragleap_voice.manifest import load_manifest
W = {e.name: e for e in load_manifest()[0]}["whisper-large-v3"]
MODEL_DIR = "%s/models/whisper-large-v3/%s" % (RV, W.revision)
from faster_whisper import WhisperModel
model = WhisperModel(MODEL_DIR, device="cuda", compute_type="float16")

# RNNoise v0.2 (BSD-3-Clause per GitHub), built from source
rc, o = sh("apt-get install -y -qq autoconf automake libtool wget > /dev/null 2>&1; cd /content && rm -rf rnnoise && git clone -q https://github.com/xiph/rnnoise.git "
           "&& cd rnnoise && git checkout -q v0.2 && ./autogen.sh > /tmp/rn1.log 2>&1 && ./configure > /tmp/rn2.log 2>&1 && make -j2 > /tmp/rn3.log 2>&1")
need(rc == 0 and os.path.exists("/content/rnnoise/examples/rnnoise_demo"), "RNNoise build failed:\n" + o[-400:])
rn_commit = sh("cd /content/rnnoise && git rev-parse HEAD")[1].strip(); rn_model = open("/content/rnnoise/model_version").read().strip()

# DeepFilterNet 0.5.6 (code MIT or Apache-2.0) in an isolated Python 3.11 environment
V = "/content/venvs/dfn"
rc, o = sh("uv venv -q --python 3.11 %s && uv pip install -q --python %s/bin/python 'numpy<2' torch==2.0.1 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "
           "&& uv pip install -q --python %s/bin/python deepfilternet==0.5.6 'numpy<2'" % (V, V, V)); need(rc == 0, "DeepFilterNet install failed:\n" + o[-500:])

import numpy as np, soundfile as sf
from datasets import load_dataset
from ragleap_voice.bench.metrics import normalize
LANGS = {"en": "en_us", "es": "es_419", "ru": "ru_ru"}
N, NB = 30, 30
clips, pool = {}, {}
for code, cfg in LANGS.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True)
    arr = []
    for i, ex in enumerate(ds):
        if i >= N + NB: break
        assert ex["audio"]["sampling_rate"] == 16000
        arr.append((np.asarray(ex["audio"]["array"], dtype="float32"), ex["transcription"]))
    clips[code], pool[code] = arr[:N], [a for a, _ in arr[N:]]
print({k: len(v) for k, v in clips.items()})

def rms(x): return float(np.sqrt(np.mean(x ** 2)) + 1e-12)
def crop(x, n, rng):
    if len(x) < n: x = np.tile(x, int(np.ceil(n / len(x))))
    s = int(rng.integers(0, len(x) - n + 1)); return x[s:s + n]
def noise_for(kind, n, lang, rng):
    if kind == "white": return rng.standard_normal(n).astype("float32")
    return sum(crop(pool[lang][int(rng.integers(0, len(pool[lang])))], n, rng) / rms(pool[lang][0]) for _ in range(4)).astype("float32")
def mix(sig, noise, snr_db):
    g = rms(sig) / rms(noise) / (10 ** (snr_db / 20))
    return np.clip(sig + noise * g, -1, 1).astype("float32"), 20 * np.log10(rms(sig) / rms(noise * g))
def q(p): return shlex.quote(p)
def ff(args): 
    rc, o = sh("ffmpeg -y -loglevel error " + args); need(rc == 0, "ffmpeg failed: " + o[-300:])

COND = {"clean": None, "white10": ("white", 10, False), "babble10": ("babble", 10, False), "babble5": ("babble", 5, False), "phone_babble10": ("babble", 10, True)}
DEN = ["none", "rnnoise", "dfn3"]
base = "/content/nz"; snr_dev = 0.0
files = {}
for lang in LANGS:
    for cond, spec in COND.items():
        d = "%s/%s/%s/none" % (base, lang, cond); os.makedirs(d, exist_ok=True); files[(lang, cond, "none")] = []
        for i, (a, ref) in enumerate(clips[lang]):
            rng = np.random.default_rng(1234 + i)
            x = a
            if spec:
                x, got = mix(a, noise_for(spec[0], len(a), lang, rng), spec[1]); snr_dev = max(snr_dev, abs(got - spec[1]))
            p = "%s/%s_%02d.wav" % (d, lang, i); sf.write(p, x, 16000, subtype="PCM_16")
            if spec and spec[2]:  # telephone path: 8 kHz mu-law, back to 16 kHz
                ff("-i %s -ar 8000 -ac 1 -c:a pcm_mulaw /tmp/ph8.wav" % q(p)); ff("-i /tmp/ph8.wav -ar 16000 -ac 1 -c:a pcm_s16le %s" % q(p + ".tmp.wav")); os.replace(p + ".tmp.wav", p)
            files[(lang, cond, "none")].append((p, ref))
print("max SNR deviation from target before clipping: %.2f dB" % snr_dev)

def denoise_rnnoise(src_dst):
    for p, out in src_dst:
        ff("-i %s -f s16le -ar 48000 -ac 1 /tmp/rn_in.raw" % q(p))
        rc, o = sh("/content/rnnoise/examples/rnnoise_demo /tmp/rn_in.raw /tmp/rn_out.raw"); need(rc == 0, "rnnoise failed: " + o[-200:])
        ff("-f s16le -ar 48000 -ac 1 -i /tmp/rn_out.raw -ar 16000 -c:a pcm_s16le %s" % q(out))
def denoise_dfn(src_dst, tmp):
    os.makedirs(tmp + "/in", exist_ok=True); os.makedirs(tmp + "/out", exist_ok=True); ins = []
    for k, (p, out) in enumerate(src_dst):
        q48 = "%s/in/%03d.wav" % (tmp, k); ff("-i %s -ar 48000 -ac 1 -c:a pcm_s16le %s" % (q(p), q(q48))); ins.append(q48)
    rc, o = sh("%s/bin/deepFilter -m DeepFilterNet3 %s -o %s/out" % (V, " ".join(q(x) for x in ins), tmp)); need(rc == 0, "deepFilter failed: " + o[-300:])
    for k, (p, out) in enumerate(src_dst):
        ff("-i %s/out/%03d_DeepFilterNet3.wav -ar 16000 -ac 1 -c:a pcm_s16le %s" % (tmp, k, q(out)))
t0 = time.time()
for lang in LANGS:
    for cond in COND:
        items = files[(lang, cond, "none")]
        for den in ("rnnoise", "dfn3"):
            d = "%s/%s/%s/%s" % (base, lang, cond, den); os.makedirs(d, exist_ok=True)
            sd = [(p, "%s/%s" % (d, os.path.basename(p))) for p, _ in items]
            denoise_rnnoise(sd) if den == "rnnoise" else denoise_dfn(sd, "/tmp/dfn_work")
            files[(lang, cond, den)] = [(o, ref) for (_, o), (_, ref) in zip(sd, items)]
    print("denoised", lang, "%.0f s" % (time.time() - t0))
ck = sorted(glob.glob("/root/.cache/DeepFilterNet/DeepFilterNet3/checkpoints/*"))
ck_sha = {os.path.basename(c): hashlib.sha256(open(c, "rb").read()).hexdigest() for c in ck}
print("DeepFilterNet3 checkpoint sha256:", ck_sha)

def prep(x):
    n = normalize(x); return " ".join(n) if isinstance(n, (list, tuple)) else n
def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]
def asr(p, lang):
    audio, sr = sf.read(p, dtype="float32"); assert sr == 16000
    segs, _ = model.transcribe(audio, language=lang, beam_size=5, temperature=0.0, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)
res, rows = {}, []
t0 = time.time()
for (lang, cond, den), items in files.items():
    pc = []
    for k, (p, ref) in enumerate(items):
        hyp = asr(p, lang); r, h = prep(ref), prep(hyp)
        e = (ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)); pc.append(e)
        rows.append([lang, cond, den, k, ref, hyp, *e])
    res[(lang, cond, den)] = pc
    print("scored %s %s %s  (%.0f s)" % (lang, cond, den, time.time() - t0))
os.makedirs("/content/results", exist_ok=True)
with open("/content/results/noise_pilot_clips.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n"); w.writerow(["lang", "cond", "den", "clip", "ref", "hyp", "we", "wn", "ce", "cn"]); w.writerows(rows)

rnd = random.Random(1234)
def wer(pc, idx=None):
    idx = idx if idx is not None else range(len(pc))
    return sum(pc[i][0] for i in idx) / max(1, sum(pc[i][1] for i in idx))
def boot(pcs, pcn, B=2000):
    n = len(pcs); ds = []
    for _ in range(B):
        idx = [rnd.randrange(n) for _ in range(n)]; ds.append(wer(pcs, idx) - wer(pcn, idx))
    ds.sort(); return ds[int(0.025 * B)], ds[int(0.975 * B)]
def ci(pc, B=2000):
    n = len(pc); v = sorted(wer(pc, [rnd.randrange(n) for _ in range(n)]) for _ in range(B)); return v[int(0.025 * B)], v[int(0.975 * B)]
print("\nWER %, 30 clips per language. 'delta' = denoiser minus no denoiser on the same clips, with a 95% interval (negative = better).")
summary = {}
for lang in LANGS:
    print("\n== %s ==" % lang)
    for cond in COND:
        base_pc = res[(lang, cond, "none")]; lo, hi = ci(base_pc)
        line = "%-15s none %5.1f (%4.1f-%4.1f)" % (cond, 100 * wer(base_pc), 100 * lo, 100 * hi); summary["%s|%s|none" % (lang, cond)] = wer(base_pc)
        for den in ("rnnoise", "dfn3"):
            pc = res[(lang, cond, den)]; dl, dh = boot(pc, base_pc)
            line += " | %s %5.1f  delta %+5.1f [%+5.1f, %+5.1f]" % (den, 100 * wer(pc), 100 * (wer(pc) - wer(base_pc)), 100 * dl, 100 * dh)
            summary["%s|%s|%s" % (lang, cond, den)] = wer(pc)
        print(line)
meta = dict(gpu=sh("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader")[1].strip(), faster_whisper=md.version("faster-whisper"), whisper_revision=W.revision,
            rnnoise_commit=rn_commit, rnnoise_model_version=rn_model, deepfilternet=sh("uv pip list --python %s/bin/python 2>/dev/null | grep -i -E 'deepfilter|torch'" % V)[1].strip().replace("\n", "; "),
            dfn3_checkpoint_sha256=ck_sha, max_snr_deviation_db=snr_dev, harness_main=main_sha, normalizer_version="1")
json.dump(dict(meta=meta, wer=summary), open("/content/results/noise_pilot_summary.json", "w"), indent=1)
print("\nMETA:", json.dumps(meta, indent=1))
