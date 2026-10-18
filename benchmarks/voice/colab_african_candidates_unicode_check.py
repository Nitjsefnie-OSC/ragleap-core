"""Unicode check for the Yoruba scores. Run in the same session as colab_african_candidates_measure.py.

Tests whether the Yoruba error comes from composed versus decomposed accent marks. Result (2026-10-18): it does not.
References were 0/60 not in NFC; outputs 3/60 (NaijaVox) and 0/60 (SunflowerASR); NFC on both sides changed the WER by under 0.1 points.
"""
import unicodedata
def prep_nfc(x, strip=False): return unicodedata.normalize("NFC", prep(x, strip))
def per_clip_nfc(pairs, strip=False):
    out = []
    for ref, hyp in pairs:
        r, h = prep_nfc(ref, strip), prep_nfc(hyp, strip)
        out.append((ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)))
    return out
refs_yo = [r for _, r in clips["yo"]]; audio_yo = [a for a, _ in clips["yo"]]
print("references not already in NFC: %d/60" % sum(unicodedata.normalize("NFC", r) != r for r in refs_yo))
for label, local, lang_ids, langs in RUNS:
    if "yo" not in langs: continue
    hyps = transcribe(local, lang_ids, "yo", audio_yo)
    pairs = list(zip(refs_yo, hyps))
    print(label[:22], "| outputs not in NFC: %d/60" % sum(unicodedata.normalize("NFC", h) != h for h in hyps))
    for nm, fn, strip in (("as scored before", per_clip, False), ("NFC both sides", per_clip_nfc, False), ("NFC + stripped", per_clip_nfc, True)):
        s = stats(fn(pairs, strip))
        print("   %-18s WER %.1f%% (%.1f-%.1f) | CER %.1f%% (%.1f-%.1f)" % (nm, 100*s["WER"][0], 100*s["WER"][1], 100*s["WER"][2], 100*s["CER"][0], 100*s["CER"][1], 100*s["CER"][2]))
