"""Model manifest loader. Standard library only."""
import pathlib
from dataclasses import dataclass

from ._toml import loads
from .licences import REQUIRED_FIELDS, validate_entries
from .locks import LockError, load_lock, lock_digest, validate_lock


class ManifestError(Exception):
    """The manifest could not be read or has the wrong shape."""


@dataclass(frozen=True)
class ModelEntry:
    name: str
    kind: str
    source_url: str
    revision: str
    sha256: str
    code_license: str
    weights_license: str
    languages: tuple
    capabilities: tuple
    min_hardware: str
    status: str
    default: bool


_STR_FIELDS = ("name", "kind", "source_url", "revision", "sha256", "code_license",
               "weights_license", "min_hardware", "status")
_LIST_FIELDS = ("languages", "capabilities")


def default_manifest_path():
    """Installed wheel: data/models.toml. Source checkout: models.toml at the package root."""
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parent / "data" / "models.toml", here.parents[2] / "models.toml"):
        if candidate.is_file():
            return candidate
    raise ManifestError("models.toml not found next to the package or in the source checkout")


def _entry(raw, index):
    label = str(raw.get("name", "entry#" + str(index)))
    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ManifestError(label + ": missing field(s): " + ", ".join(missing))
    unknown = sorted(set(raw) - set(REQUIRED_FIELDS))
    if unknown:
        raise ManifestError(label + ": unknown field(s): " + ", ".join(unknown))
    for f in _STR_FIELDS:
        if not isinstance(raw[f], str):
            raise ManifestError(label + ": field " + f + " must be a string")
    for f in _LIST_FIELDS:
        v = raw[f]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ManifestError(label + ": field " + f + " must be a list of strings")
    if not isinstance(raw["default"], bool):
        raise ManifestError(label + ": field default must be true or false")
    return ModelEntry(
        name=raw["name"], kind=raw["kind"], source_url=raw["source_url"], revision=raw["revision"],
        sha256=raw["sha256"], code_license=raw["code_license"], weights_license=raw["weights_license"],
        languages=tuple(raw["languages"]), capabilities=tuple(raw["capabilities"]),
        min_hardware=raw["min_hardware"], status=raw["status"], default=raw["default"])


def load_manifest(path=None):
    """Return (entries, problems). Problems come from the licence policy check; a malformed
    manifest raises ManifestError instead."""
    p = pathlib.Path(path) if path else default_manifest_path()
    try:
        data = loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError("cannot read " + str(p) + ": " + str(exc))
    raws = data.get("model", [])
    if not isinstance(raws, list):
        raise ManifestError("'model' must be an array of tables ([[model]])")
    entries = [_entry(r, i) for i, r in enumerate(raws)]
    notices_file = p.parent / "THIRD_PARTY_NOTICES.md"
    notices = notices_file.read_text(encoding="utf-8") if notices_file.is_file() else ""
    return entries, validate_entries(raws, notices)


def lock_problems(entries, manifest_path=None):
    """Check the lock files next to the manifest. Verified or default entries must have a lock whose
    digest equals the entry's sha256 field; any lock that exists must be well formed and match its entry."""
    p = pathlib.Path(manifest_path) if manifest_path else default_manifest_path()
    ldir = p.parent / "locks"
    problems = []
    for e in entries:
        lp = ldir / (e.name + ".json")
        needs = e.status == "verified" or e.default
        if not lp.is_file():
            if needs:
                problems.append(e.name + ": verified or default entry needs locks/" + e.name + ".json")
            continue
        try:
            lock = load_lock(lp)
        except LockError as exc:
            problems.append(e.name + ": " + str(exc))
            continue
        for why in validate_lock(lock, name=e.name, revision=e.revision or None):
            problems.append(e.name + ": lock " + why)
        if needs and lock_digest(lock) != e.sha256:
            problems.append(e.name + ": sha256 in models.toml does not match the lock file digest")
    names = {e.name for e in entries}
    if ldir.is_dir():
        for f in sorted(ldir.glob("*.json")):
            if f.stem not in names:
                problems.append("orphan lock file without manifest entry: " + f.name)
    return problems
