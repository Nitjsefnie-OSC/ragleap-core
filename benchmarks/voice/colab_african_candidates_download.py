"""Cell A: download two fine-tuned Whisper large-v3 candidates at pinned revisions. T4 GPU runtime.

Order: accept the conditions of the gated model on its Hugging Face page, create a short-lived Read token, save it as the
Colab secret HF_TOKEN (Notebook access on), run this cell, delete the secret and the token, then run the measure cell.
NaijaVox-2.0 is not gated. SunflowerASR is gated (access mode auto); the Hub reported its current name as
Sunbird/SunflowerASR-51-african-languages. Files are downloaded by huggingface_hub and are NOT hash-checked by ragleap-voice.
"""
import subprocess, sys, os
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub", "datasets==3.6.0", "soundfile", "accelerate"], check=True)
from huggingface_hub import snapshot_download
from google.colab import userdata
try: tok = userdata.get("HF_TOKEN")
except Exception: raise SystemExit("Secret fetch failed: keep this tab in the foreground, check HF_TOKEN (Notebook access on), rerun")
if not tok: raise SystemExit("HF_TOKEN is empty")
CANDS = {"naijavox": ("Axiveri/NaijaVox-2.0", "22b94de94e59419cc9d6e25e6eaeceb1f1c42d00", None),
         "sunflower": ("Sunbird/asr-whisper-51-african-languages", "4583c9dd251c422a4325fb0a0a509a3828097be2", tok)}
for name, (repo, rev, t) in CANDS.items():
    d = snapshot_download(repo, revision=rev, token=t, local_dir="/content/cand_" + name,
                          ignore_patterns=["*.png", "audio_samples/*", "*.wav"])
    files = [(f, os.path.getsize(os.path.join(dp, f))) for dp, _, fs in os.walk(d) for f in fs]
    print(name, rev[:10], "%d files, %.2f GiB" % (len(files), sum(s for _, s in files) / 1024**3))
del tok
print("\nDOWNLOAD DONE. Now delete the HF_TOKEN secret (key icon) and the token on huggingface.co, then run the measure cell.")
