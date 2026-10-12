"""Model lock files: pinned revision plus size and SHA-256 for every file.

Standard library only. A lock file (locks/<model>.json) is the evidence behind a 'verified'
manifest entry: models.toml stores the SHA-256 of the lock's canonical form in its sha256
field, so changing either the lock or the manifest is detected.
"""
import hashlib
import json
import os
import pathlib
import re
import stat

SCHEMA = 1
MAX_FILES = 5000
MAX_FILE_BYTES = 64 * 1024 ** 3
MAX_LOCK_BYTES = 8 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._+=@,~-]+$")


class LockError(Exception):
    """A lock file or cache path is unreadable, unsafe or inconsistent."""


def safe_relpath(path):
    """Return None when path is a safe relative POSIX path, else a reason string."""
    if not isinstance(path, str) or not path:
        return "empty or non-string path"
    if len(path) > 300:
        return "path too long"
    if "\\" in path or "\x00" in path:
        return "backslash or NUL in path"
    if path.startswith("/"):
        return "absolute path"
    for seg in path.split("/"):
        if seg in ("", ".", ".."):
            return "empty, '.' or '..' segment"
        if not _SEGMENT.match(seg):
            return "unsupported characters in segment " + repr(seg)
    return None


def canonical_bytes(lock):
    return (json.dumps(lock, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def lock_digest(lock):
    return hashlib.sha256(canonical_bytes(lock)).hexdigest()


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key " + repr(key))
        out[key] = value
    return out


def load_lock(path):
    p = pathlib.Path(path)
    try:
        if p.stat().st_size > MAX_LOCK_BYTES:
            raise LockError("lock file " + p.name + " is too large")
        data = json.loads(p.read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicates)
    except LockError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LockError("cannot read lock file " + p.name + ": " + str(exc))
    if not isinstance(data, dict):
        raise LockError("lock file " + p.name + " must contain a JSON object")
    return data


def validate_lock(lock, name=None, revision=None):
    """Return a list of problems (empty means the lock is well formed and matches name/revision)."""
    if not isinstance(lock, dict):
        return ["lock is not a JSON object"]
    problems = []
    extra = sorted(set(lock) - {"schema", "model", "revision", "source_url", "files"})
    if extra:
        problems.append("unknown key(s): " + ", ".join(extra))
    if lock.get("schema") != SCHEMA:
        problems.append("schema must be " + str(SCHEMA))
    for key in ("model", "revision", "source_url"):
        if not isinstance(lock.get(key), str) or not lock.get(key):
            problems.append(key + " missing or not a string")
    if name is not None and lock.get("model") != name:
        problems.append("model %r does not match manifest entry %r" % (lock.get("model"), name))
    if revision is not None and lock.get("revision") != revision:
        problems.append("revision %r does not match manifest revision %r" % (lock.get("revision"), revision))
    files = lock.get("files")
    if not isinstance(files, list) or not files:
        problems.append("files must be a non-empty list")
        return problems
    if len(files) > MAX_FILES:
        problems.append("too many files (limit %d)" % MAX_FILES)
        return problems
    seen, dirs, paths = set(), set(), []
    for i, f in enumerate(files):
        label = "files[%d]" % i
        if not isinstance(f, dict):
            problems.append(label + ": not an object")
            continue
        unknown = sorted(set(f) - {"path", "size", "sha256"})
        if unknown:
            problems.append(label + ": unknown key(s): " + ", ".join(unknown))
        path = f.get("path")
        why = safe_relpath(path)
        if why:
            problems.append(label + ": " + why)
        else:
            label = path
            key = path.casefold()
            if key in seen:
                problems.append(label + ": duplicate path (case-insensitive)")
            seen.add(key)
            paths.append(key)
            parts = key.split("/")
            for k in range(1, len(parts)):
                dirs.add("/".join(parts[:k]))
        size = f.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_FILE_BYTES:
            problems.append(label + ": invalid size")
        sha = f.get("sha256")
        if not isinstance(sha, str) or not _HEX64.match(sha):
            problems.append(label + ": sha256 must be 64 lowercase hex characters")
    for key in paths:
        if key in dirs:
            problems.append(key + ": path conflict, listed both as a file and as a directory")
    return problems


def hash_file(path, block=1 << 20):
    """Return (size, sha256 hex digest), reading the file in blocks."""
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(block), b""):
            h.update(chunk)
            total += len(chunk)
    return total, h.hexdigest()


def verify_dir(lock, directory):
    """Check a cached model directory against a (validated) lock. Returns a list of problems."""
    base = pathlib.Path(directory)
    if base.is_symlink() or not base.is_dir():
        return ["directory missing or not a plain directory: " + str(base)]
    problems = []
    wanted = set()
    for f in lock["files"]:
        rel = f["path"]
        wanted.add(rel)
        parts = rel.split("/")
        if any(base.joinpath(*parts[:k]).is_symlink() for k in range(1, len(parts))):
            problems.append(rel + ": parent directory is a symlink (not allowed)")
            continue
        p = base.joinpath(*parts)
        try:
            st = p.lstat()
        except OSError:
            problems.append(rel + ": missing")
            continue
        if stat.S_ISLNK(st.st_mode):
            problems.append(rel + ": is a symlink (not allowed)")
            continue
        if not stat.S_ISREG(st.st_mode):
            problems.append(rel + ": not a regular file")
            continue
        if st.st_size != f["size"]:
            problems.append("%s: size %d, expected %d" % (rel, st.st_size, f["size"]))
            continue
        _, digest = hash_file(p)
        if digest != f["sha256"]:
            problems.append(rel + ": sha256 mismatch")
    for dirpath, dirnames, filenames in os.walk(str(base), followlinks=False):
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                rel = os.path.relpath(full, str(base)).replace(os.sep, "/")
                problems.append(rel + ": unexpected symlink")
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), str(base)).replace(os.sep, "/")
            if rel not in wanted:
                problems.append(rel + ": unexpected file")
    return problems
