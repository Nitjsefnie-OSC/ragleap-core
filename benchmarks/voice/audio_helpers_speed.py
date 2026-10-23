"""Speed of standard-library audio helpers on 20 ms frames (prototype for docs/design/audio-helpers.md, not package code).

Pure Python 3.10+, no third-party imports. Prints the machine, the load average, a correctness check, and microseconds per frame.
Where the audioop module still exists (Python 3.12 and older) it is timed too, for reference. Run it niced on a quiet machine:
    nice -n 19 python3 benchmarks/voice/audio_helpers_speed.py
The resampler is a naive 31-tap windowed-sinc filter with zero history at frame edges: it is here to time a plain approach, and its
audio quality is not tested by this script.
"""
import array, math, os, platform, random, sys, time
from operator import mul

BIAS = 0x84
def _dec(u):
    u = ~u & 0xFF
    s = (((u & 0x0F) << 3) + BIAS) << ((u >> 4) & 7)
    s -= BIAS
    return -s if u & 0x80 else s
def _enc(s):
    sign = 0x80 if s < 0 else 0
    if s < 0: s = -s
    if s > 32635: s = 32635
    s += BIAS
    e = s.bit_length() - 8
    return ~(sign | (e << 4) | ((s >> (e + 3)) & 0x0F)) & 0xFF
DEC = [_dec(u) for u in range(256)]
ENC = bytes(_enc(i - 32768) for i in range(65536))

def make_taps(L=31, fc=0.225):
    m = L // 2; t = []
    for n in range(L):
        k = n - m
        h = 2 * fc if k == 0 else math.sin(2 * math.pi * fc * k) / (math.pi * k)
        t.append(h * (0.54 - 0.46 * math.cos(2 * math.pi * n / (L - 1))))
    s = sum(t); return [x / s for x in t]
TAPS = make_taps(); TAPS2 = [2 * x for x in TAPS]; L = len(TAPS)

def ulaw_decode(frame): return array.array("h", [DEC[b] for b in frame])
def ulaw_encode(samples): return bytes([ENC[s + 32768] for s in samples])
def rms(samples): return math.sqrt(sum(map(mul, samples, samples)) / len(samples))
def gain(samples, g): return array.array("h", [max(-32768, min(32767, int(x * g))) for x in samples])
def down2(x):
    pad = L // 2; xp = [0] * pad + list(x) + [0] * pad
    return array.array("h", [max(-32768, min(32767, int(sum(map(mul, TAPS, xp[i:i + L]))))) for i in range(0, len(x), 2)])
def up2(x):
    pad = L // 2; u = [0] * (2 * len(x)); u[::2] = x; xp = [0] * pad + u + [0] * pad
    return array.array("h", [max(-32768, min(32767, int(sum(map(mul, TAPS2, xp[i:i + L]))))) for i in range(len(u))])

def bench(fn, arg, reps=150, rounds=3):
    best = 1e9
    for _ in range(rounds):
        t0 = time.perf_counter()
        for _ in range(reps): fn(arg)
        best = min(best, (time.perf_counter() - t0) / reps)
    return best * 1e6

print("python", sys.version.split()[0], "|", platform.machine(), "| cpus", os.cpu_count(), "| load average (1, 5, 15 min):", ["%.2f" % x for x in os.getloadavg()])
bad = [u for u in range(256) if ENC[DEC[u] + 32768] != u]
print("check: DEC[0x00]=%d DEC[0x80]=%d DEC[0xFF]=%d | round-trip mismatches over 256 codes: %s (only 0x7F, the other zero, is expected)" % (DEC[0], DEC[0x80], DEC[0xFF], [hex(u) for u in bad]))
try:
    import audioop
    ref = True
    same_dec = audioop.ulaw2lin(bytes(range(256)), 2) == array.array("h", DEC).tobytes()
    enc_ref = audioop.lin2ulaw(array.array("h", range(-32768, 32768)).tobytes(), 2)
    print("check vs audioop: decode identical for all 256 codes: %s | encode differs on %d of 65536 samples" % (same_dec, sum(1 for a, b in zip(enc_ref, ENC) if a != b)))
except ImportError:
    ref = False; print("audioop: not available on this Python (removed in 3.13)")

rnd = random.Random(1234)
f8 = bytes(rnd.randrange(256) for _ in range(160))
p8 = ulaw_decode(f8)
p16 = array.array("h", [int(6000 * math.sin(2 * math.pi * 440 * i / 16000) + rnd.gauss(0, 300)) for i in range(320)])
rows = [("mu-law decode, 160 samples", ulaw_decode, f8, (lambda f: audioop.ulaw2lin(f, 2)) if ref else None),
        ("mu-law encode, 160 samples", ulaw_encode, p8, (lambda s: audioop.lin2ulaw(array.array("h", s).tobytes(), 2)) if ref else None),
        ("rms, 160 samples", rms, p8, (lambda s: audioop.rms(array.array("h", s).tobytes(), 2)) if ref else None),
        ("gain, 160 samples", lambda s: gain(s, 0.7), p8, (lambda s: audioop.mul(array.array("h", s).tobytes(), 2, 0.7)) if ref else None),
        ("resample 16 to 8 kHz, 320 in", down2, p16, (lambda s: audioop.ratecv(array.array("h", s).tobytes(), 2, 1, 16000, 8000, None)) if ref else None),
        ("resample 8 to 16 kHz, 160 in", up2, p8, (lambda s: audioop.ratecv(array.array("h", s).tobytes(), 2, 1, 8000, 16000, None)) if ref else None)]
print("\n%-32s %14s %14s" % ("one 20 ms frame", "pure Python us", "audioop us"))
t = {}
for name, fn, arg, rf in rows:
    t[name] = bench(fn, arg); r = bench(rf, arg) if rf else None
    print("%-32s %14.1f %14s" % (name, t[name], ("%.1f" % r) if r is not None else "n/a"))
inb = t["mu-law decode, 160 samples"] + t["resample 8 to 16 kHz, 160 in"] + t["rms, 160 samples"] + t["gain, 160 samples"]
outb = t["resample 16 to 8 kHz, 320 in"] + t["mu-law encode, 160 samples"]
print("\ninbound chain (decode, resample up, rms, gain): %.0f us per 20 ms frame" % inb)
print("outbound chain (resample down, encode):       %.0f us per 20 ms frame" % outb)
print("one call, both directions: %.0f us of CPU per 20000 us of audio = %.1f%% of one core" % (inb + outb, 100 * (inb + outb) / 20000))
print("upper bound of simultaneous calls on one core with nothing else running: %.0f" % (20000 / (inb + outb)))
