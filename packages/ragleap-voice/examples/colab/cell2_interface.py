# Colab Cell 2: the interface. Run only after Cell 1, and only after deleting the HF_TOKEN secret and the token.
import os, sys, json, time, wave, uuid, shutil, pathlib, subprocess, threading, queue, glob, ctypes, site, datetime
import numpy as np

from google.colab import userdata
leak = False
try:
    userdata.get("HF_TOKEN"); leak = True
except Exception as e:
    if type(e).__name__ == "TimeoutException":
        print("NOTE: could not check whether the HF_TOKEN secret still exists (tab in the background?). Please make sure it is deleted.")
if leak:
    raise SystemExit("The HF_TOKEN secret is still available to this notebook. Delete it (key icon) and the token on huggingface.co, then rerun this cell. Models that run their own code must not be able to reach it.")
if "tok" in globals():
    raise SystemExit("The token is still in this kernel's memory (variable tok). Restart the session, run Cell 1 again (it now clears it), delete the secret and the token, then run this cell.")

STATE = json.load(open("/content/rv_state.json"))
for d in ("rv_in", "rv_out", "rv_logs", "voices"): pathlib.Path("/content/" + d).mkdir(exist_ok=True)

# ---------- engine workers (one isolated process per TTS engine) ----------
SENT = "@@RV@@ "
class Worker:
    def __init__(self, name, py, script, args=(), env=None):
        self.name, self.py, self.script, self.args, self.env = name, py, script, list(args), env
        self.proc = None; self.q = None
    def alive(self): return self.proc is not None and self.proc.poll() is None
    @staticmethod
    def _reader(proc, q):
        for line in proc.stdout:
            if line.startswith(SENT):
                try: q.put(json.loads(line[len(SENT):]))
                except ValueError: pass
        q.put({"event": "eof"})
    def start(self, timeout=900):
        if self.alive(): return
        self.q = queue.Queue()
        err = open("/content/rv_logs/%s.err" % self.name, "w")
        self.proc = subprocess.Popen([self.py, self.script] + self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=err, text=True, bufsize=1, env=self.env)
        threading.Thread(target=self._reader, args=(self.proc, self.q), daemon=True).start()
        deadline = time.time() + timeout
        while True:
            try: msg = self.q.get(timeout=5)
            except queue.Empty:
                if self.proc.poll() is not None: raise RuntimeError("%s engine exited while starting (log: /content/rv_logs/%s.err)" % (self.name, self.name))
                if time.time() > deadline: self.stop(); raise RuntimeError("%s engine start timed out" % self.name)
                continue
            if msg.get("event") == "ready": return
            if msg.get("event") == "load_error": self.stop(); raise RuntimeError(msg["error"] + "  (log: /content/rv_logs/%s.err)" % self.name)
            if msg.get("event") == "eof": raise RuntimeError("%s engine exited while starting (log: /content/rv_logs/%s.err)" % (self.name, self.name))
    def request(self, payload, timeout=900):
        self.start()
        rid = uuid.uuid4().hex[:8]
        self.proc.stdin.write(json.dumps(dict(payload, id=rid)) + "\n"); self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try: msg = self.q.get(timeout=5)
            except queue.Empty:
                if self.proc.poll() is not None: raise RuntimeError("engine stopped unexpectedly (log: /content/rv_logs/%s.err)" % self.name)
                continue
            if msg.get("event") == "eof": raise RuntimeError("engine stopped unexpectedly (log: /content/rv_logs/%s.err)" % self.name)
            if msg.get("id") == rid:
                if not msg.get("ok"): raise RuntimeError(msg.get("error", "unknown error"))
                return msg
        raise RuntimeError("request timed out")
    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.stdin.write('{"op": "quit"}\n'); self.proc.stdin.flush(); self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
        self.proc = None

CLEAN = {k: v for k, v in os.environ.items() if "TOKEN" not in k.upper()}
WORKERS, HEAVY = {}, ("parler", "chatterbox")
def tts_worker(name):
    py = STATE["envs"].get(name)
    if not py: raise RuntimeError("the %s environment was not installed (see Cell 1 output)" % name)
    if name in HEAVY:
        for other in HEAVY:
            if other != name and other in WORKERS: WORKERS[other].stop()
    if name not in WORKERS:
        env, args = dict(CLEAN), []
        if name == "parler":
            env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HOME="/content/rv_hf_empty")
            args = [STATE["parler_dir"], STATE["tok_dir"]]
        WORKERS[name] = Worker(name, py, STATE["scripts"][name], args, env)
    return WORKERS[name]

# ---------- speech to text (runs in this process) ----------
_stt, _pre = {}, {"done": False}
def preload_cuda():
    if _pre["done"]: return
    libs = []
    for r in site.getsitepackages() + [site.getusersitepackages()]:
        libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True)
        libs += sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
    for p in libs:
        try: ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
        except OSError: pass
    _pre["done"] = True
def load_whisper():
    if "whisper" not in _stt:
        preload_cuda()
        from faster_whisper import WhisperModel
        _stt["whisper"] = WhisperModel("large-v3", device="cuda", compute_type="float16")
    return _stt["whisper"]
def load_ic():
    if "ic" not in _stt:
        preload_cuda()
        import huggingface_hub
        from transformers import AutoModel
        local = STATE["ic_dir"]
        for k in [k for k in sys.modules if "model_onnx" in k]: del sys.modules[k]
        orig = huggingface_hub.snapshot_download
        huggingface_hub.snapshot_download = lambda repo_id, *a, **k: local if repo_id == local else orig(repo_id, *a, **k)
        try: _stt["ic"] = AutoModel.from_pretrained(local, trust_remote_code=True, local_files_only=True)
        finally: huggingface_hub.snapshot_download = orig
    return _stt["ic"]
def to_wav(src, dst, sr, max_s):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", str(sr), "-t", str(max_s), dst], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("cannot decode this audio file: " + r.stderr[-200:])
def read_wav(path):
    with wave.open(path, "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float32") / 32768.0, wf.getframerate()
IC_CODES = {"as", "bn", "brx", "doi", "gu", "hi", "kn", "kok", "ks", "mai", "ml", "mni", "mr", "ne", "or", "pa", "sa", "sat", "sd", "ta", "te", "ur"}
def whisper_transcribe(audio, lang):
    segs, info = load_whisper().transcribe(audio, language=None if lang == "auto" else lang, beam_size=5)
    return " ".join(s.text.strip() for s in segs), info.language, info.language_probability
def ic_transcribe(audio, lang, mode="rnnt"):
    import torch
    m, parts, step = load_ic(), [], 25 * 16000
    for i in range(0, len(audio), step):
        chunk = audio[i:i + step]
        if len(chunk) < 1600: continue
        out = m(torch.from_numpy(chunk).unsqueeze(0), lang, mode)
        parts.append(str(out[0] if isinstance(out, (list, tuple)) else out).strip())
    return " ".join(p for p in parts if p)
def run_stt(audio, engine, lang):
    notes = []
    if engine == "ic" and lang == "auto": raise RuntimeError("IndicConformer needs a language: pick one")
    if engine == "ic" or (engine == "auto" and lang in IC_CODES):
        return ic_transcribe(audio, lang), "IndicConformer-600M (RNNT)", lang, notes
    text, det, prob = whisper_transcribe(audio, lang)
    if lang == "auto":
        notes.append("Whisper detected language: %s (%.0f%% confidence)" % (det, 100 * prob))
        if engine == "auto" and det in IC_CODES and prob >= 0.5:
            notes.append("re-transcribed with IndicConformer for better Indian-language accuracy")
            return ic_transcribe(audio, det), "IndicConformer-600M (RNNT)", det, notes
    return text, "Whisper large-v3", det, notes

# ---------- data tables ----------
PARLER = {"Hindi": ["Rohit", "Divya"], "Tamil": ["Jaya", "Kavitha"], "Telugu": ["Prakash", "Lalitha"], "Malayalam": ["Anjali", "Harish"],
          "Kannada": ["Suresh", "Anu"], "English": ["Thoma", "Mary"], "Bengali": ["Arjun", "Aditi"], "Marathi": ["Sanjay", "Sunita"],
          "Gujarati": ["Yash", "Neha"], "Odia": ["Manas", "Debjani"], "Assamese": ["Amit", "Sita"], "Bodo": ["Bikram", "Maya"],
          "Dogri": ["Karan"], "Manipuri": ["Laishram", "Ranjit"], "Nepali": ["Amrita"], "Sanskrit": ["Aryan"]}
PARLER_EMOTION_OK = {"Assamese", "Bengali", "Bodo", "Dogri", "Kannada", "Malayalam", "Marathi", "Sanskrit", "Nepali", "Tamil"}
EMOTIONS = {"Neutral": "a calm, neutral tone", "Happy": "a happy, cheerful tone full of energy", "Sad": "a sad, subdued tone",
            "Anger": "an angry, forceful tone", "Fear": "a frightened, trembling tone", "Surprise": "a surprised, excited tone",
            "Disgust": "a disgusted tone", "Command": "a firm, commanding tone", "Narration": "a steady narration style",
            "Conversation": "a natural, conversational tone", "News": "a clear news-reader tone"}
KOKORO_LANGS = [("English (US)", "a"), ("English (UK)", "b"), ("Hindi", "h"), ("Spanish", "e"), ("French", "f"), ("Italian", "i"), ("Portuguese (Brazil)", "p")]
KOKORO_VOICES = {"a": ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael"], "b": ["bf_emma", "bf_isabella", "bm_george", "bm_lewis"],
                 "h": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"], "e": ["ef_dora", "em_alex"], "f": ["ff_siwis"], "i": ["if_sara", "im_nicola"], "p": ["pf_dora", "pm_alex"]}
CHATTERBOX_LANGS = [("English", "en"), ("Hindi", "hi"), ("Arabic", "ar"), ("Danish", "da"), ("German", "de"), ("Greek", "el"), ("Spanish", "es"), ("Finnish", "fi"),
                    ("French", "fr"), ("Hebrew", "he"), ("Italian", "it"), ("Japanese", "ja"), ("Korean", "ko"), ("Malay", "ms"), ("Dutch", "nl"), ("Norwegian", "no"),
                    ("Polish", "pl"), ("Portuguese", "pt"), ("Russian", "ru"), ("Swedish", "sv"), ("Swahili", "sw"), ("Turkish", "tr"), ("Chinese", "zh")]
MEAS_TTS = {("parler", "Hindi"): 7.7, ("parler", "Tamil"): 16.1, ("parler", "Telugu"): 11.9, ("parler", "Malayalam"): 22.0, ("parler", "Kannada"): 16.7,
            ("parler", "English"): 5.8, ("kokoro", "English (US)"): 1.8, ("kokoro", "Hindi"): 7.9, ("chatterbox", "English"): 3.2, ("chatterbox", "Hindi"): 18.9}
ENGINE_NOTE = {"parler": "Files pinned and hash-checked by ragleap-voice (the entry is still marked unverified: no human review yet). Gated model, Apache-2.0 per its card.",
               "kokoro": "Downloaded by the library at run time: not hash-checked by ragleap-voice. Apache-2.0 per its card; its non-English paths use GPLv3 espeak-ng.",
               "chatterbox": "Downloaded by the library at run time: not hash-checked by ragleap-voice. MIT per its card; its output carries Resemble's PerTh watermark."}
DEFAULT_TEXT = {"English": "Hello, this is a short test of the voice.", "English (US)": "Hello, this is a short test of the voice.", "English (UK)": "Hello, this is a short test of the voice.",
                "Hindi": "अरे, तुम आज कैसे हो?", "Tamil": "வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?", "Telugu": "నమస్కారం, మీరు ఎలా ఉన్నారు?",
                "Malayalam": "നമസ്കാരം, സുഖമാണോ?", "Kannada": "ನಮಸ್ಕಾರ, ಹೇಗಿದ್ದೀರಿ?", "Bengali": "নমস্কার, আপনি কেমন আছেন?", "Marathi": "नमस्कार, तुम्ही कसे आहात?",
                "Gujarati": "નમસ્તે, તમે કેમ છો?", "Spanish": "Hola, ¿cómo estás hoy?", "French": "Bonjour, comment allez-vous aujourd'hui ?", "Italian": "Ciao, come stai oggi?",
                "Portuguese (Brazil)": "Olá, como você está hoje?", "Portuguese": "Olá, como você está hoje?", "German": "Hallo, wie geht es Ihnen heute?", "Swahili": "Habari, hujambo leo?"}
STT_LANGS = [("Auto-detect (Whisper decides, then Indian languages are re-run with IndicConformer)", "auto"),
             ("Hindi: measured 10.2% word error", "hi"), ("Tamil: measured 27.5%", "ta"), ("Telugu: measured 21.4%", "te"), ("Malayalam: measured 20.8%", "ml"), ("Kannada: measured 16.5%", "kn"),
             ("English: measured 4.8% (Whisper, 20 clips)", "en"),
             ("Bengali: not measured", "bn"), ("Marathi: not measured", "mr"), ("Gujarati: not measured", "gu"), ("Punjabi: not measured", "pa"), ("Odia: not measured", "or"),
             ("Assamese: not measured", "as"), ("Urdu: not measured", "ur"), ("Nepali: not measured", "ne"), ("Sanskrit: not measured", "sa"),
             ("Spanish: not measured", "es"), ("Portuguese: not measured", "pt"), ("French: not measured", "fr"), ("German: not measured", "de"), ("Italian: not measured", "it"),
             ("Russian: not measured", "ru"), ("Dutch: not measured", "nl"), ("Polish: not measured", "pl"), ("Ukrainian: not measured", "uk"), ("Greek: not measured", "el"), ("Swedish: not measured", "sv"),
             ("Arabic: not measured", "ar"), ("Turkish: not measured", "tr"), ("Hebrew: not measured", "he"), ("Chinese: not measured", "zh"), ("Japanese: not measured", "ja"), ("Korean: not measured", "ko"),
             ("Indonesian: not measured", "id"), ("Vietnamese: not measured", "vi"), ("Thai: not measured", "th"),
             ("Swahili: not measured, low-resource", "sw"), ("Yoruba: not measured, low-resource", "yo"), ("Hausa: not measured, low-resource", "ha"), ("Amharic: not measured, low-resource", "am"),
             ("Afrikaans: not measured", "af"), ("Shona: not measured, low-resource", "sn"), ("Somali: not measured, low-resource", "so"), ("Lingala: not measured, low-resource", "ln"),
             ("Haitian Creole: not measured", "ht")]

# ---------- voices (cloning) ----------
VOICES = {}
def load_voices():
    VOICES.clear()
    for p in sorted(glob.glob("/content/voices/*/consent.json")):
        try:
            rec = json.load(open(p, encoding="utf-8")); ref = os.path.join(os.path.dirname(p), "ref.wav")
            if os.path.isfile(ref): VOICES[rec["voice_id"]] = dict(rec, ref=ref)
        except Exception: pass
load_voices()

# ---------- interface ----------
import ipywidgets as w
from IPython.display import display, Audio, clear_output
try:
    from google.colab import output as _co; _co.enable_custom_widget_manager()
except Exception: pass
STY, LAY = {"description_width": "150px"}, w.Layout(width="640px")
def dd(desc, options, value=None): return w.Dropdown(options=options, value=value, description=desc, style=STY, layout=LAY)
def uploaded_to_file(up):
    v = up.value
    if not v: return None
    if isinstance(v, dict): item = next(iter(v.values())); name, data = item["metadata"]["name"], bytes(item["content"])
    else: item = v[0]; name, data = item["name"], bytes(item["content"])
    if len(data) > 100 * 1024 * 1024: raise RuntimeError("file too large (limit 100 MB)")
    p = "/content/rv_in/upload_%s%s" % (uuid.uuid4().hex[:8], pathlib.Path(name).suffix[:8])
    pathlib.Path(p).write_bytes(data); return p

# --- tab 1: listen ---
stt_up = w.FileUpload(accept="audio/*,video/*", multiple=False, description="Upload audio")
stt_path = w.Text(description="or file path", placeholder="/content/my_audio.mp3 (upload via the folder icon on the left)", style=STY, layout=LAY)
stt_lang = dd("Language", STT_LANGS, "auto")
stt_eng = dd("Engine", [("Auto", "auto"), ("Whisper large-v3", "whisper"), ("IndicConformer-600M (Indian languages)", "ic")], "auto")
stt_btn = w.Button(description="Transcribe", button_style="primary")
stt_out = w.Output()
def on_stt(_):
    with stt_out:
        clear_output()
        try:
            src = stt_path.value.strip() or uploaded_to_file(stt_up)
            if not src: print("Upload an audio file or type its path first."); return
            if not os.path.isfile(src): print("File not found:", src); return
            wav16 = "/content/rv_in/%s.wav" % uuid.uuid4().hex[:8]
            to_wav(src, wav16, 16000, 600)
            audio, _ = read_wav(wav16)
            print("Transcribing %.1f s of audio (first use of an engine loads its model: 1 to 2 minutes)..." % (len(audio) / 16000))
            t0 = time.time()
            text, eng, lang, notes = run_stt(audio, stt_eng.value, stt_lang.value)
            clear_output()
            print(text if text else "(no speech found)")
            print("\n--\nengine: %s | language: %s | took %.1f s" % (eng, lang, time.time() - t0))
            for n in notes: print(n)
            print("Preview quality: see the 'not measured' labels in the language list. Chunks of long audio are cut every 25 s for IndicConformer, which can split a word.")
        except Exception as e:
            print("Error:", type(e).__name__, str(e)[:500])
stt_btn.on_click(on_stt)
tab_listen = w.VBox([w.HTML("<b>Speech to text.</b> Upload a recording (up to 10 minutes are used)."), stt_up, stt_path, stt_lang, stt_eng, stt_btn, stt_out])

# --- tab 2: speak ---
tts_eng = dd("Engine", [("Indic Parler-TTS: Indian languages, style and emotion by description", "parler"), ("Kokoro-82M: very fast, fixed voices", "kokoro"),
                        ("Chatterbox: 23 languages, voice cloning, expressiveness", "chatterbox")], "parler")
tts_lang, tts_voice = dd("Language", [], None), dd("Voice", [], None)
tts_emo = dd("Emotion (Parler)", list(EMOTIONS), "Neutral")
tts_pace = dd("Pace (Parler)", ["slow", "moderate", "fast"], "moderate")
tts_pitch = dd("Pitch (Parler)", ["low", "moderate", "high"], "moderate")
tts_speed = w.FloatSlider(description="Speed (Kokoro)", min=0.7, max=1.3, step=0.05, value=1.0, style=STY, layout=LAY)
tts_exag = w.FloatSlider(description="Expressiveness (Chatterbox)", min=0.25, max=2.0, step=0.05, value=0.5, style=STY, layout=LAY)
tts_cfg = w.FloatSlider(description="Pacing (Chatterbox)", min=0.2, max=1.0, step=0.05, value=0.5, style=STY, layout=LAY)
tts_text = w.Textarea(description="Text", style=STY, layout=w.Layout(width="640px", height="100px"))
tts_note = w.HTML()
tts_btn = w.Button(description="Speak", button_style="primary")
tts_out = w.Output()
_last_default = {"t": None}
def refresh_voices(*_):
    e, lang = tts_eng.value, tts_lang.value
    if lang is None: return
    if e == "parler": opts = PARLER[lang]
    elif e == "kokoro": opts = KOKORO_VOICES[dict(KOKORO_LANGS)[lang]]
    else: opts = [("Built-in default voice", "")] + [("%s (your cloned voice)" % r["display_name"], vid) for vid, r in VOICES.items()]
    tts_voice.options = opts
    if tts_text.value.strip() in ("", _last_default["t"]):
        tts_text.value = DEFAULT_TEXT.get(lang, ""); _last_default["t"] = tts_text.value
    m = MEAS_TTS.get((e, lang))
    tts_note.value = "<small>%s<br>%s</small>" % (("Measured intelligibility on %s: %.1f%% round-trip word error (20 sentences, T4)." % (lang, m)) if m is not None else "Not measured for this language yet.", ENGINE_NOTE[e])
def refresh_engine(*_):
    e = tts_eng.value
    langs = {"parler": list(PARLER), "kokoro": [l for l, _ in KOKORO_LANGS], "chatterbox": [l for l, _ in CHATTERBOX_LANGS]}[e]
    tts_lang.options = langs; tts_lang.value = langs[0]
    for c in (tts_emo, tts_pace, tts_pitch): c.disabled = e != "parler"
    tts_speed.disabled = e != "kokoro"
    for c in (tts_exag, tts_cfg): c.disabled = e != "chatterbox"
    refresh_voices()
tts_eng.observe(refresh_engine, names="value"); tts_lang.observe(refresh_voices, names="value")
def on_tts(_):
    with tts_out:
        clear_output()
        try:
            text = tts_text.value.strip()
            if not text: print("Type some text first."); return
            if len(text) > 600: print("Please keep the text under 600 characters for this demo."); return
            e, lang, voice = tts_eng.value, tts_lang.value, tts_voice.value
            out = "/content/rv_out/synthetic_%s.wav" % uuid.uuid4().hex[:8]
            if e == "parler":
                if tts_emo.value != "Neutral" and lang not in PARLER_EMOTION_OK:
                    print("Note: emotion prompts are officially supported only for %s; for %s the effect may be weak or absent." % (", ".join(sorted(PARLER_EMOTION_OK)), lang))
                desc = "%s speaks in %s with a %s speed and a %s pitch. The recording is very clear audio, very close up, with no background noise." % (voice, EMOTIONS[tts_emo.value], tts_pace.value, tts_pitch.value)
                req = {"text": text, "desc": desc, "out": out}
            elif e == "kokoro":
                req = {"text": text, "lc": dict(KOKORO_LANGS)[lang], "voice": voice, "speed": tts_speed.value, "out": out}
            else:
                req = {"text": text, "lang": dict(CHATTERBOX_LANGS)[lang], "ref": VOICES[voice]["ref"] if voice else None,
                       "exaggeration": tts_exag.value, "cfg_weight": tts_cfg.value, "out": out}
            wk = tts_worker(e)
            if not wk.alive(): print("Starting the %s engine (first use loads models: 1 to 3 minutes)..." % e)
            msg = wk.request(req)
            display(Audio(out))
            print("synthetic speech | engine: %s | generated %.1f s of audio in %.1f s | file: %s" % (e, msg["audio_s"], msg["seconds"], out))
        except Exception as ex:
            print("Error:", type(ex).__name__, str(ex)[:500])
tts_btn.on_click(on_tts)
tab_speak = w.VBox([w.HTML("<b>Text to speech.</b> Everything you generate is synthetic speech."), tts_eng, tts_lang, tts_voice, tts_emo, tts_pace, tts_pitch, tts_speed, tts_exag, tts_cfg, tts_text, tts_note, tts_btn, tts_out])

# --- tab 3: your voice ---
v_up = w.FileUpload(accept="audio/*,video/*", multiple=False, description="Upload sample")
v_path = w.Text(description="or file path", placeholder="/content/my_voice.mp3", style=STY, layout=LAY)
v_name = w.Text(description="Speaker name", style=STY, layout=LAY)
v_purpose = w.Text(description="Purpose", value="Personal test of synthetic speech", style=STY, layout=LAY)
v_consent = w.Checkbox(description="I am the speaker, or I have the speaker's written permission to clone this voice. It is not a public figure's voice, and I will not use the result to deceive anyone.", indent=False, layout=w.Layout(width="95%"))
v_btn = w.Button(description="Create voice from this sample", button_style="primary")
v_list = dd("Your voices", [], None)
v_del = w.Button(description="Delete selected voice and its consent record", button_style="danger")
v_out = w.Output()
def refresh_voice_list():
    v_list.options = [("%s (%s)" % (r["display_name"], vid), vid) for vid, r in VOICES.items()]
    refresh_voices()
def on_create(_):
    with v_out:
        clear_output()
        try:
            if not v_consent.value: print("Please confirm the consent statement first."); return
            if not v_name.value.strip(): print("Please enter the speaker's name."); return
            src = v_path.value.strip() or uploaded_to_file(v_up)
            if not src or not os.path.isfile(src): print("Upload a sample or give a valid file path first."); return
            vid = "v" + uuid.uuid4().hex[:8]; d = "/content/voices/" + vid; pathlib.Path(d).mkdir(parents=True)
            to_wav(src, d + "/ref.wav", 24000, 20)
            audio, sr = read_wav(d + "/ref.wav")
            if len(audio) / sr < 3: shutil.rmtree(d); print("The sample is too short: use at least 3 seconds of clean speech (5 to 20 s is best)."); return
            rec = {"voice_id": vid, "display_name": v_name.value.strip(), "purpose": v_purpose.value.strip(),
                   "scope": "Synthetic speech inside this Colab session only",
                   "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "statement": v_consent.description, "source_file": pathlib.Path(src).name,
                   "revocation": "Use the delete button; it removes the reference audio and this record"}
            json.dump(rec, open(d + "/consent.json", "w", encoding="utf-8"), indent=2)
            load_voices(); refresh_voice_list(); v_list.value = vid
            print("Voice created (%.1f s of reference audio). Choose Chatterbox on the Speak tab and select it under Voice." % (len(audio) / sr))
        except Exception as e:
            print("Error:", type(e).__name__, str(e)[:400])
def on_delete(_):
    with v_out:
        clear_output()
        vid = v_list.value
        if not vid: print("No voice selected."); return
        shutil.rmtree("/content/voices/" + vid, ignore_errors=True)
        load_voices(); refresh_voice_list(); print("Deleted voice", vid, "(reference audio and consent record).")
v_btn.on_click(on_create); v_del.on_click(on_delete)
tab_voice = w.VBox([w.HTML("<b>Your voice.</b> Zero-shot cloning: Chatterbox imitates a short sample (no training). Only the speaker's own voice, or with written permission. Never public figures. Files stay inside this Colab session."),
                    v_up, v_path, v_name, v_purpose, v_consent, v_btn, v_list, v_del, v_out])

# --- tab 4: about ---
tab_about = w.HTML("""<b>What this is:</b> a pre-alpha preview of ragleap-voice, not a finished product.<br><br>
<b>Measured so far</b> (read speech, small samples, one T4 GPU): IndicConformer beats Whisper large-v3 on Hindi, Tamil, Telugu, Malayalam and Kannada; Whisper is good on English.
Text-to-speech intelligibility was measured by transcribing the output back. <b>Not measured:</b> naturalness, emotion quality, voice similarity, accents, slang and code-switching, noisy or phone audio, and almost every language other than the six above.<br><br>
<b>Emotion:</b> Parler uses named emotions in the description (official in 10 Indian languages); Chatterbox has an intensity slider only. Whether this reaches ElevenLabs-level expressiveness is unproven.<br>
<b>Cloning:</b> zero-shot only. Fine-tuning on a user's recordings is not implemented.<br>
<b>Safety:</b> consent record for every cloned voice; no public link; synthetic outputs are named synthetic_*.wav; Chatterbox adds a watermark.<br>
<b>Licences:</b> see the note under each engine. Kokoro's non-English paths use GPLv3 espeak-ng (isolated, demo only). Nothing here has had a legal review.""")

free_btn = w.Button(description="Free GPU memory (stop all engines)")
free_out = w.Output()
def on_free(_):
    with free_out:
        clear_output()
        for wk in list(WORKERS.values()): wk.stop()
        WORKERS.clear(); _stt.clear()
        try:
            import torch, gc; gc.collect(); torch.cuda.empty_cache()
        except Exception: pass
        print("Stopped all engines and unloaded the speech-to-text models.")
free_btn.on_click(on_free)

tabs = w.Tab(children=[tab_listen, tab_speak, tab_voice, tab_about])
for i, t in enumerate(["Listen (speech to text)", "Speak (text to speech)", "Your voice", "About and limits"]): tabs.set_title(i, t)
refresh_engine(); refresh_voice_list()
display(tabs, free_btn, free_out)
