"""Intervals and diagnostics for colab_pilot12.py. Run in the same Colab session, right after it.

Part 1: 95% bootstrap intervals per language from the pilot CSV (2000 resamples of clips, seed 1234).
Part 2: Yoruba re-scored with diacritics stripped from both sides, and three Amharic decoding variants.
Part 2 is diagnostic only: decoding settings are not chosen on the test set, so no variant replaces the pilot numbers.
"""
import csv, glob, random, json, unicodedata, wave, time
import numpy as np
path = sorted(glob.glob("/content/results/whisper-large-v3-pilot12_*.csv"))[-1]
rows = list(csv.DictReader(open(path, encoding="utf-8")))
by = {}
for r in rows: by.setdefault(r["language"], []).append(r)
def rate(rs, e, n):
    d = sum(int(r[n]) for r in rs)
    return sum(int(r[e]) for r in rs) / d if d else float("nan")
rnd = random.Random(1234)
def ci(rs, e, n, B=2000):
    vals = sorted(rate([rs[rnd.randrange(len(rs))] for _ in rs], e, n) for _ in range(B))
    return vals[int(0.025 * B)], vals[int(0.975 * B)]
summary = {}
print("lang  WER (95% CI)            CER (95% CI)            clips")
for lang, rs in sorted(by.items()):
    w, c = rate(rs, "word_errors", "ref_words"), rate(rs, "char_errors", "ref_chars")
    wl, wh = ci(rs, "word_errors", "ref_words"); cl, ch = ci(rs, "char_errors", "ref_chars")
    summary[lang] = dict(wer=w, wer_ci=[wl, wh], cer=c, cer_ci=[cl, ch], clips=len(rs))
    print("%-4s %6.1f%% (%5.1f-%5.1f)   %6.1f%% (%5.1f-%5.1f)   %d" % (lang, 100*w, 100*wl, 100*wh, 100*c, 100*cl, 100*ch, len(rs)))
print("\nrows with an engine error:", sum(1 for r in rows if r["error"]))
json.dump(summary, open("/content/results/pilot12_summary.json", "w"), indent=1)

from ragleap_voice.bench.metrics import normalize
def prep(x, strip=False):
    n = normalize(x)
    n = " ".join(n) if isinstance(n, (list, tuple)) else n
    if strip:
        n = "".join(c for c in unicodedata.normalize("NFD", n) if not unicodedata.combining(c))
    return n
def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]
def score(pairs, strip=False):
    we = wn = ce = cn = 0
    for ref, hyp in pairs:
        r, h = prep(ref, strip), prep(hyp, strip)
        we += ed(r.split(), h.split()); wn += len(r.split())
        ce += ed(list(r), list(h)); cn += len(r)
    return we / wn, ce / cn

yo = [(r["reference"], r["hypothesis"]) for r in by["yo"]]
for strip in (False, True):
    w, c = score(yo, strip)
    print("Yoruba | diacritics stripped: %-5s | WER %.1f%% | CER %.1f%%" % (strip, 100 * w, 100 * c))

def read(p):
    with wave.open(p, "rb") as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype("float32") / 32768.0
am_items = [i for i in items if i.language == "am"]
refs = {r["id"]: r["reference"] for r in by["am"]}
def run_am(name, **kw):
    t0, pairs, loops = time.time(), [], 0
    for it in am_items:
        segs, _ = model.transcribe(read(it.path), language="am", **kw)
        hyp = " ".join(s.text.strip() for s in segs)
        loops += len(set(hyp.split())) < 0.3 * max(1, len(hyp.split())) and len(hyp.split()) > 20
        pairs.append((refs[it.id], hyp))
    w, c = score(pairs)
    print("Amharic | %-34s | WER %6.1f%% | CER %6.1f%% | repetitive outputs: %d/60 | %.0f s" % (name, 100 * w, 100 * c, loops, time.time() - t0))
    return pairs
p0 = run_am("our settings (as in the pilot)", beam_size=5, temperature=0.0, condition_on_previous_text=False)
p1 = run_am("library defaults")
p2 = run_am("ours + repetition guard (diagnostic)", beam_size=5, temperature=0.0, condition_on_previous_text=False,
            repetition_penalty=1.2, no_repeat_ngram_size=3)
