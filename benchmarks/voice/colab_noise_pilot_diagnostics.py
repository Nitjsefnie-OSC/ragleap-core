"""Diagnostics for colab_noise_pilot.py. Run in the same Colab session, right after it. Two cells joined into one file;
each ran on its own, the joined file has not been run as one piece.

Finding: DeepFilterNet3 returned silent output for the quietest English clips (17 of 30 at or below -55.9 dBFS RMS; 3 to 6 of 30 in Russian),
and Whisper transcribed silence as "Thank you.". With every clip scaled to -23 dBFS before denoising, English clean WER was 6.3% for
DeepFilterNet3 against 5.5% with no denoiser, and 0 outputs were silent. Batch versus single-file calls made no difference (65.2% both).
"""
def lag_corr(a, b, max_lag=4800):
    n = min(len(a), len(b), 80000); a, b = a[:n], b[:n]
    c = np.fft.irfft(np.fft.rfft(a, 2 * n) * np.conj(np.fft.rfft(b, 2 * n)))
    c = np.concatenate([c[-max_lag:], c[:max_lag + 1]]); i = int(np.argmax(c))
    return i - max_lag, float(c[i] / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
print("== input vs DeepFilterNet3 output: duration, volume ratio, best time shift (samples), similarity ==")
for lang in ("en", "es"):
    for k in range(4):
        p0, _ = files[(lang, "clean", "none")][k]; p1, _ = files[(lang, "clean", "dfn3")][k]
        a, _ = sf.read(p0, dtype="float32"); b, _ = sf.read(p1, dtype="float32")
        lag, cc = lag_corr(a, b)
        print("%s clip %d | in %.2f s out %.2f s | rms ratio %.2f | shift %+d | similarity %.2f" % (lang, k, len(a) / 16000, len(b) / 16000, rms(b) / rms(a), lag, cc))
bad = sorted([r for r in rows if r[0] == "en" and r[1] == "clean" and r[2] == "dfn3"], key=lambda r: -r[6] / max(1, r[7]))
print("\nEnglish clean, per-clip WER with DeepFilterNet3 (batched):", [round(100 * r[6] / max(1, r[7])) for r in sorted(bad, key=lambda r: r[3])])
for r in bad[:3]:
    print("\nclip %d\n REF: %s\n HYP: %s" % (r[3], r[4][:110], r[5][:110]))
print("\n== English clean, DeepFilterNet3, one file per call ==")
os.makedirs(base + "/en/clean/dfn3_single", exist_ok=True)
single = []
for k, (p, ref) in enumerate(files[("en", "clean", "none")]):
    out = "%s/en/clean/dfn3_single/%s" % (base, os.path.basename(p))
    denoise_dfn([(p, out)], "/tmp/dfn_one_%d" % k); single.append((out, ref))
pc = []
for p, ref in single:
    hyp = asr(p, "en"); r, h = prep(ref), prep(hyp)
    pc.append((ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)))
print("WER %.1f%% with one file per call (the batched run gave 65.2%%; no denoiser gave 5.5%%)" % (100 * wer(pc)))

def dbfs(x): return 20 * np.log10(rms(x))
print("== silence census: clips whose denoised output is below 5% of the input level (of 30) ==")
print("%-4s %-16s %8s %8s" % ("lang", "condition", "rnnoise", "dfn3"))
for lang in LANGS:
    for cond in COND:
        c = {}
        for den in ("rnnoise", "dfn3"):
            n = 0
            for (pi, _), (po, _) in zip(files[(lang, cond, "none")], files[(lang, cond, den)]):
                a, _ = sf.read(pi, dtype="float32"); b, _ = sf.read(po, dtype="float32"); n += rms(b) < 0.05 * rms(a)
            c[den] = n
        print("%-4s %-16s %8d %8d" % (lang, cond, c["rnnoise"], c["dfn3"]))
print("\n== English clean: input level against DeepFilterNet3 output ratio (sorted by input level) ==")
lv = []
for (pi, _), (po, _) in zip(files[("en", "clean", "none")], files[("en", "clean", "dfn3")]):
    a, _ = sf.read(pi, dtype="float32"); b, _ = sf.read(po, dtype="float32"); lv.append((round(dbfs(a), 1), round(float(np.abs(a).max()), 2), round(rms(b) / rms(a), 2)))
for t in sorted(lv): print("  in %6.1f dBFS  peak %.2f  out/in %.2f" % t)
print("\n== English clean at a fixed input level (-23 dBFS RMS, peak limited), batch of 30 ==")
os.makedirs(base + "/en/clean/lvl_in", exist_ok=True); os.makedirs(base + "/en/clean/lvl_out", exist_ok=True)
sd, refs_lv, in_pairs = [], [], []
for k, (p, ref) in enumerate(files[("en", "clean", "none")]):
    a, _ = sf.read(p, dtype="float32")
    g = min((10 ** (-23 / 20)) / rms(a), 0.95 / float(np.abs(a).max()))
    pin = "%s/en/clean/lvl_in/%02d.wav" % (base, k); sf.write(pin, np.clip(a * g, -1, 1), 16000, subtype="PCM_16")
    sd.append((pin, "%s/en/clean/lvl_out/%02d.wav" % (base, k))); refs_lv.append(ref)
denoise_dfn(sd, "/tmp/dfn_lvl")
def score(paths):
    pc = []
    for p, ref in zip(paths, refs_lv):
        hyp = asr(p, "en"); r, h = prep(ref), prep(hyp)
        pc.append((ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)))
    return wer(pc)
w_none = score([i for i, _ in sd]); w_dfn = score([o for _, o in sd])
silent = sum(rms(sf.read(o, dtype="float32")[0]) < 0.05 * rms(sf.read(i, dtype="float32")[0]) for i, o in sd)
print("no denoiser, level-fixed: WER %.1f%% | DeepFilterNet3, level-fixed: WER %.1f%% | silent outputs: %d/30" % (100 * w_none, 100 * w_dfn, silent))
print("(reference: unscaled no denoiser 5.5%, unscaled DeepFilterNet3 65.2%)")
