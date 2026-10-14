"""Where verified models live on disk. Standard library only."""
import os
import pathlib
import re

from .locks import LockError

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def cache_root(environ=None):
    env = os.environ if environ is None else environ
    custom = env.get("RAGLEAP_VOICE_HOME")
    if custom:
        return pathlib.Path(custom).expanduser()
    xdg = env.get("XDG_CACHE_HOME")
    base = pathlib.Path(xdg).expanduser() if xdg else pathlib.Path.home() / ".cache"
    return base / "ragleap-voice"


def model_dir(name, revision, root=None):
    """<root>/models/<name>/<revision>. Name and revision are restricted to safe characters."""
    for label, value in (("model name", name), ("revision", revision)):
        if not isinstance(value, str) or len(value) > 128 or not _SAFE.match(value):
            raise LockError("unsafe " + label + ": " + repr(value))
    base = pathlib.Path(root) if root is not None else cache_root()
    return base / "models" / name / revision
