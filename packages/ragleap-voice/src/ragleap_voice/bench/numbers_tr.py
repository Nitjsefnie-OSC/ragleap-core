"""Turkish cardinal-number word normalization for benchmark text.

The supported forms are standalone cardinal number words from zero through
katrilyon. Ordinals, dates, currency forms, dialect variants, and inflected
forms are intentionally outside this module's scope.
"""

_UNITS = {
    "sıfır": 0,
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "dört": 4,
    "beş": 5,
    "altı": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
}
_TENS = {
    "on": 10,
    "yirmi": 20,
    "otuz": 30,
    "kırk": 40,
    "elli": 50,
    "altmış": 60,
    "yetmiş": 70,
    "seksen": 80,
    "doksan": 90,
}
_SCALES = {
    "bin": 10 ** 3,
    "milyon": 10 ** 6,
    "milyar": 10 ** 9,
    "trilyon": 10 ** 12,
    "katrilyon": 10 ** 15,
}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_SCALES) | {"yüz"}


def numbers_to_digits(words):
    """Replace recognized runs of Turkish cardinal-number words with digits."""
    out, run = [], []
    for word in words:
        if word in _NUMBER_WORDS:
            run.append(word)
        else:
            out.extend(_parse_run(run))
            run = []
            out.append(word)
    out.extend(_parse_run(run))
    return out


def _parse_run(run):
    if not run:
        return []
    # As in the English number step, consecutive unit words represent digits.
    if len(run) > 1 and all(word in _UNITS for word in run):
        return ["".join(str(_UNITS[word]) for word in run)]

    out = []
    total = section = 0
    last_kind = None
    last_scale = None

    def flush():
        nonlocal total, section, last_kind, last_scale
        if total or section or last_kind is not None:
            out.append(str(total + section))
        total = section = 0
        last_kind = last_scale = None

    for word in run:
        if word in _UNITS:
            if last_kind == "unit":
                flush()
            section += _UNITS[word]
            last_kind = "unit"
        elif word in _TENS:
            if last_kind in ("unit", "tens"):
                flush()
            section += _TENS[word]
            last_kind = "tens"
        elif word == "yüz":
            if last_kind == "hundred" or last_kind == "tens" or section >= 100:
                flush()
            section = (section or 1) * 100
            last_kind = "hundred"
        else:
            scale = _SCALES[word]
            if last_scale is not None and scale >= last_scale:
                # Repeated or rising scales start a separate number run.
                if total:
                    out.append(str(total))
                total = 0
                last_scale = None
            total += (section or 1) * scale
            section = 0
            last_scale = scale
            last_kind = None

    flush()
    return out
