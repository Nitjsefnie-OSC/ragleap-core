"""Language coverage matrix: load and check coverage/*.csv (standard library only).

One row per (language, engine). See docs/design/coverage-matrix.md. A row without evidence cannot have a tier above 1.
Engines that are not in models.toml are written as 'candidate:NAME' and are never used by engine selection.
"""
import csv
import pathlib
import re

COLUMNS = ("language", "engine", "tier", "metric", "value", "ci_low", "ci_high", "test_set", "n_clips",
           "normalizer_version", "raw_committed", "evidence", "contamination", "weights_licence", "notes", "champion")
_LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class CoverageError(Exception):
    """A coverage file is unreadable or has the wrong columns."""


def load_rows(path):
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise CoverageError("%s: columns must be exactly %s" % (pathlib.Path(path).name, ", ".join(COLUMNS)))
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise CoverageError("cannot read %s: %s" % (path, exc))


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def check_rows(rows, known_engines, repo_root=None):
    """Return a list of problems (empty means the rows follow the rules). repo_root enables the evidence-path check."""
    problems, seen = [], set()
    for i, r in enumerate(rows, start=2):
        label = "row %d (%s, %s)" % (i, r.get("language"), r.get("engine"))
        lang, engine = r.get("language", ""), r.get("engine", "")
        if not _LANG.match(lang):
            problems.append(label + ": bad language tag")
        if not (engine in known_engines or (engine.startswith("candidate:") and len(engine) > len("candidate:"))):
            problems.append(label + ": engine is not in models.toml and has no candidate: prefix")
        if (lang, engine) in seen:
            problems.append(label + ": duplicate language and engine")
        seen.add((lang, engine))
        tier = r.get("tier", "")
        if tier not in ("0", "1", "2", "3"):
            problems.append(label + ": tier must be 0, 1, 2 or 3")
            continue
        if r.get("raw_committed") not in ("yes", "no"):
            problems.append(label + ": raw_committed must be yes or no")
        value, lo, hi = _number(r.get("value")), _number(r.get("ci_low")), _number(r.get("ci_high"))
        if r.get("value") and value is None:
            problems.append(label + ": value is not a number")
        if lo is not None and hi is not None and value is not None and not lo <= value <= hi:
            problems.append(label + ": value is outside its interval")
        if int(tier) >= 2:
            for col in ("metric", "test_set", "evidence"):
                if not r.get(col):
                    problems.append("%s: tier %s needs %s" % (label, tier, col))
            if value is None:
                problems.append(label + ": tier %s needs a numeric value" % tier)
            if not (r.get("n_clips") or "").isdigit() or int(r["n_clips"]) <= 0:
                problems.append(label + ": tier %s needs n_clips" % tier)
        if repo_root is not None and r.get("evidence"):
            for part in r["evidence"].split(";"):
                path = part.strip().split("#")[0]
                if path and not (pathlib.Path(repo_root) / path).is_file():
                    problems.append("%s: evidence file not found: %s" % (label, path))
    return problems
