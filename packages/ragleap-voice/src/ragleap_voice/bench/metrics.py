"""WER and CER with one shared text normalizer for every system under test.

Normalization: Unicode NFKC, casefold, apostrophes dropped, other punctuation and
symbols become spaces, whitespace collapsed. Combining marks are KEPT, so Indic
scripts are not damaged. Digits and spelled-out numbers are NOT unified here;
that is a known limitation and must be stated next to any published number.
CER counts Unicode code points (not grapheme clusters) of the normalized text.
"""
import unicodedata

_APOSTROPHES = {"'", "\u2019", "\u02bc"}


def normalize(text):
    text = unicodedata.normalize("NFKC", text or "").casefold()
    out = []
    for ch in text:
        if ch in _APOSTROPHES:
            continue
        cat = unicodedata.category(ch)
        if cat[0] in ("P", "S") or ch.isspace():
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


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


def word_errors(reference, hypothesis):
    """Return (errors, reference_word_count). Raises ValueError on an empty reference."""
    ref = normalize(reference).split()
    if not ref:
        raise ValueError("empty reference after normalization")
    return edit_distance(ref, normalize(hypothesis).split()), len(ref)


def char_errors(reference, hypothesis):
    """Return (errors, reference_char_count). Raises ValueError on an empty reference."""
    ref = normalize(reference)
    if not ref:
        raise ValueError("empty reference after normalization")
    return edit_distance(list(ref), list(normalize(hypothesis))), len(ref)


def wer(reference, hypothesis):
    e, n = word_errors(reference, hypothesis)
    return e / n


def cer(reference, hypothesis):
    e, n = char_errors(reference, hypothesis)
    return e / n
