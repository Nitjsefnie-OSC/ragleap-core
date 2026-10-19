"""Level-fixed rerun of colab_noise_pilot.py: the run reported in benchmarks/voice/README.md. Same Colab session, after the other two files.

Every noisy clip is scaled to -23 dBFS RMS (peak limited to 0.95) before the denoisers, so none, RNNoise and DeepFilterNet3 see identical levels.
"""
import shutil
res_unnorm, rows_unnorm = dict(res), list(rows)
shutil.rmtree("/tmp/dfn_work", ignore_errors=True)
def normalise_inplace(p):
    a, _ = sf.read(p, dtype="float32")
    g = min((10 ** (-23 / 20)) / rms(a), 0.95 / max(float(np.abs(a).max()), 1e-9))
    sf.write(p, np.clip(a * g, -1, 1), 16000, subtype="PCM_16")
for key, items in files.items():
    if key[2] == "none":
        for p, _ in items: normalise_inplace(p)
t0 = time.time()
for lang in LANGS:
    for cond in COND:
        items = files[(lang, cond, "none")]
        for den in ("rnnoise", "dfn3"):
            sd = [(p, files[(lang, cond, den)][k][0]) for k, (p, _) in enumerate(items)]
            denoise_rnnoise(sd) if den == "rnnoise" else denoise_dfn(sd, "/tmp/dfn_work")
    print("re-denoised", lang, "%.0f s" % (time.time() - t0))
sil = 0
for key, items in files.items():
    if key[2] != "none":
        for (pi, _), (po, _) in zip(files[(key[0], key[1], "none")], items):
            sil += rms(sf.read(po, dtype="float32")[0]) < 0.05 * rms(sf.read(pi, dtype="float32")[0])
print("silent denoiser outputs after level fix (of 450 clips per denoiser x 2 denoisers = 900):", sil)
res, rows = {}, []
for (lang, cond, den), items in files.items():
    pc = []
    for k, (p, ref) in enumerate(items):
        hyp = asr(p, lang); r, h = prep(ref), prep(hyp)
        e = (ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)); pc.append(e)
        rows.append([lang, cond, den, k, ref, hyp, *e])
    res[(lang, cond, den)] = pc
    print("scored %s %s %s (%.0f s)" % (lang, cond, den, time.time() - t0))
with open("/content/results/noise_pilot_levelfixed_clips.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n"); w.writerow(["lang", "cond", "den", "clip", "ref", "hyp", "we", "wn", "ce", "cn"]); w.writerows(rows)
print("\nWER %, level-fixed (-23 dBFS), 30 clips per language. delta = denoiser minus none on the same clips [95%% interval]; 'was' = none without the level fix.")
summary = {}
for lang in LANGS:
    print("\n== %s ==" % lang)
    for cond in COND:
        b = res[(lang, cond, "none")]; lo, hi = ci(b)
        line = "%-15s none %5.1f (%4.1f-%4.1f) was %5.1f" % (cond, 100 * wer(b), 100 * lo, 100 * hi, 100 * wer(res_unnorm[(lang, cond, "none")])); summary["%s|%s|none" % (lang, cond)] = wer(b)
        for den in ("rnnoise", "dfn3"):
            pc = res[(lang, cond, den)]; dl, dh = boot(pc, b)
            line += " | %s %5.1f d %+5.1f [%+5.1f, %+5.1f]" % (den, 100 * wer(pc), 100 * (wer(pc) - wer(b)), 100 * dl, 100 * dh); summary["%s|%s|%s" % (lang, cond, den)] = wer(pc)
        print(line)
meta["level_fix"] = "RMS -23 dBFS, peak limit 0.95, applied to every noisy clip before denoising"; meta["silent_outputs_after_fix"] = int(sil)
json.dump(dict(meta=meta, wer=summary, wer_without_level_fix={"%s|%s|%s" % k: wer(v) for k, v in res_unnorm.items()}), open("/content/results/noise_pilot_levelfixed_summary.json", "w"), indent=1)
