"""Test-set manifest (CSV). Columns: id,path,reference,language,license,source[,sha256].

Paths are relative to the manifest file. Every item must carry an allowlisted
licence (same policy as models.toml). Returns (items, problems); an empty
problems list means the manifest is usable.
"""
import csv
import hashlib
import pathlib
from dataclasses import dataclass

from ..licences import check_licence

REQUIRED = ("id", "path", "reference", "language", "license", "source")


@dataclass(frozen=True)
class TestItem:
    __test__ = False  # not a pytest class
    id: str
    path: str
    reference: str
    language: str
    license: str
    source: str


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(manifest_path):
    base = pathlib.Path(manifest_path).resolve().parent
    items, problems, seen = [], [], set()
    with open(manifest_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            return [], ["manifest missing columns: " + ", ".join(missing)]
        for n, row in enumerate(reader, 2):
            label = "row " + str(n) + " (" + str(row.get("id", "?")) + ")"
            empty = [c for c in REQUIRED if not (row.get(c) or "").strip()]
            if empty:
                problems.append(label + ": empty " + ", ".join(empty))
                continue
            if row["id"] in seen:
                problems.append(label + ": duplicate id")
            seen.add(row["id"])
            ok, why = check_licence(row["license"])
            if not ok:
                problems.append(label + ": licence " + why)
            p = (base / row["path"]).resolve()
            if not p.is_file():
                problems.append(label + ": audio file not found")
                continue
            want = (row.get("sha256") or "").strip().lower()
            if want and _sha256(p) != want:
                problems.append(label + ": sha256 mismatch")
            items.append(TestItem(row["id"], str(p), row["reference"],
                                  row["language"], row["license"], row["source"]))
    return items, problems
