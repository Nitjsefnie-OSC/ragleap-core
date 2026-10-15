"""WER and CER with one shared text normalizer for every system under test.

Normalization: Unicode NFKC, casefold, apostrophes dropped, other punctuation and
symbols become spaces, whitespace collapsed. Combining marks are KEPT, so Indic
scripts are not damaged. CER counts Unicode code points (not grapheme clusters)
of the normalized text.

By default digits and spelled-out numbers are NOT unified (normalizer version
"1", the one every published number so far was measured with); that is a known
limitation and must be stated next to any published number. Pass numbers=True
for the optional number step (version "1+numbers-en.1"), and record
normalizer_version(numbers) next to any number measured with it:

- English number words become digits: a run of single digits is read digit by
  digit ("four seven two nine" -> "4729"), anything else as cardinal numbers
  ("one hundred twenty" -> "120"); a word that cannot continue the number starts
  a new one ("three fifteen" -> "3 15", which is what "3:15" becomes).
- A thousands separator between digits is dropped ("1,200" -> "1200").
- Decimal digits of any script become ASCII digits (Devanagari, Tamil, ...).

Not covered: decimals ("three point five"), ordinals ("first", "1st"), "oh" for
zero, years read in pairs ("nineteen eighty" -> "19 80", not "1980"), currency
symbols ("$120" stays "120", without "dollars"), and spelled-out numbers in any
language but English. Every "one" becomes "1", on both sides alike.
"""
import re
import unicodedata

NORMALIZER_VERSION = "1"
NUMBERS_VERSION = "numbers-en.1"

_APOSTROPHES = {"'", "\u2019", "\u02bc"}

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine".split())}
_TEENS = {w: i + 10 for i, w in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9}
_NUMBER_WORDS = set(_UNITS) | set(_TEENS) | set(_TENS) | set(_SCALES) | {"hundred"}
_THOUSANDS_SEPARATOR = re.compile(r"(?<=\d)[,\u066c](?=\d{3}(?!\d))")


def normalizer_version(numbers=False):
    """The version string to record next to any number measured with these settings."""
    return NORMALIZER_VERSION + ("+" + NUMBERS_VERSION if numbers else "")


def normalize(text, numbers=False):
    text = unicodedata.normalize("NFKC", text or "").casefold()
    if numbers:
        text = _THOUSANDS_SEPARATOR.sub("", text)
    out = []
    for ch in text:
        if ch in _APOSTROPHES:
            continue
        cat = unicodedata.category(ch)
        if cat[0] in ("P", "S") or ch.isspace():
            out.append(" ")
        elif numbers and cat == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    words = "".join(out).split()
    if numbers:
        words = _numbers_to_digits(words)
    return " ".join(words)


def _numbers_to_digits(words):
    """Replace every run of English number words with digits."""
    out, run = [], []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w in _NUMBER_WORDS:
            run.append(w)
        elif (w == "and" and run and run[-1] in ("hundred", *_SCALES)
              and (nxt in _UNITS or nxt in _TEENS or nxt in _TENS)):
            continue  # "one hundred and twenty"
        else:
            out.extend(_parse_run(run))
            run = []
            out.append(w)
    out.extend(_parse_run(run))
    return out


def _parse_run(run):
    if not run:
        return []
    if len(run) > 1 and all(w in _UNITS for w in run):
        return ["".join(str(_UNITS[w]) for w in run)]  # read digit by digit
    numbers = []
    total = current = 0
    last = None          # kind of the previous word in the current number
    last_scale = None    # the scale most recently applied to the current number

    def flush():
        nonlocal total, current, last, last_scale
        if last is not None:
            numbers.append(str(total + current))
        total = current = 0
        last = last_scale = None

    for w in run:
        if w in _UNITS or w in _TEENS or w in _TENS:
            kind = "unit" if w in _UNITS else "teen" if w in _TEENS else "tens"
            value = _UNITS.get(w, _TEENS.get(w, _TENS.get(w)))
            if last in ("unit", "teen") or (last == "tens" and kind != "unit"):
                flush()
            current += value
        elif w == "hundred":
            if last == "hundred":
                flush()
            elif current >= 100:  # "one hundred one hundred": the last "one" starts the next number
                carry = current % 100
                current -= carry
                flush()
                current, last = carry, "unit"
            kind = "hundred"
            current = (current or 1) * 100
        else:
            scale = _SCALES[w]
            if last_scale is not None and scale >= last_scale:
                carry = current  # "one thousand one thousand": the last "one" starts the next number
                current = 0
                flush()
                current = carry
            kind = "scale"
            total += (current or 1) * scale
            current = 0
            last_scale = scale
        last = kind
    flush()
    return numbers


def edit_distance(ref, hyp):
    """Levenshtein distance between two sequences."""
    if not ref:
        return len(hyp)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if r == h else 1))
        prev = cur
    return prev[-1]


def word_errors(reference, hypothesis, numbers=False):
    """Return (errors, reference_word_count). Raises ValueError on an empty reference."""
    ref = normalize(reference, numbers).split()
    if not ref:
        raise ValueError("empty reference after normalization")
    return edit_distance(ref, normalize(hypothesis, numbers).split()), len(ref)


def char_errors(reference, hypothesis, numbers=False):
    """Return (errors, reference_char_count). Raises ValueError on an empty reference."""
    ref = normalize(reference, numbers)
    if not ref:
        raise ValueError("empty reference after normalization")
    return edit_distance(list(ref), list(normalize(hypothesis, numbers))), len(ref)


def wer(reference, hypothesis, numbers=False):
    e, n = word_errors(reference, hypothesis, numbers)
    return e / n


def cer(reference, hypothesis, numbers=False):
    e, n = char_errors(reference, hypothesis, numbers)
    return e / n
