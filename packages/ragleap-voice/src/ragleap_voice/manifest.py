"""Model manifest loader. Standard library only."""
import pathlib
from dataclasses import dataclass

from ._toml import loads
from .licences import REQUIRED_FIELDS, validate_entries


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
