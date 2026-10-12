"""Verified model download ('models pull') and lock building ('models lock'). Standard library only."""
import fnmatch
import os
import re
import secrets
import shutil

from .cache import model_dir
from .fetch import DEFAULT_BASE, FetchError, Policy, download_file, get_json, repo_id_from_url, resolve_url
from .licences import check_licence
from .locks import MAX_FILES, SCHEMA, lock_digest, safe_relpath, validate_lock, verify_dir

SPACE_MARGIN = 256 * 1024 ** 2
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class PullError(Exception):
    """A refusal or failure in pull/lock. Messages never contain tokens or URLs with query strings."""


def token_from_env(environ):
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = (environ.get(key) or "").strip()
        if value:
            return value
    return None


def format_size(n):
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return ("%d B" % value) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1024.0


def _repo_and_revision(source_url, revision):
    repo = repo_id_from_url(source_url)
    if repo is None:
        raise PullError("only sources of the form https://huggingface.co/OWNER/REPO are supported")
    if not _COMMIT.match(revision or ""):
        raise PullError("the revision must be a full 40-character commit hash")
    return repo


def pull_model(entry, lock, cache_root, policy=None, base_url=DEFAULT_BASE, token=None,
               offline=False, allow_unverified=False, say=print):
    """Download one model into the cache after verifying it against its lock. Returns the directory."""
    policy = policy or Policy()
    for key in ("code_license", "weights_license"):
        ok, why = check_licence(getattr(entry, key))
        if not ok:
            raise PullError("%s: %s %r is not on the licence allowlist (%s); refusing"
                            % (entry.name, key, getattr(entry, key), why))
    if entry.status != "verified":
        if not allow_unverified:
            raise PullError("%s is unverified (a research lead, not an endorsement); "
                            "use --allow-unverified to pull it anyway" % entry.name)
        say("WARNING: %s is unverified: files are checked only against the lock stored in this "
            "repository, which no person has reviewed. Licences: code %s, weights %s."
            % (entry.name, entry.code_license, entry.weights_license))
    repo = _repo_and_revision(entry.source_url, entry.revision)
    problems = validate_lock(lock, name=entry.name, revision=entry.revision)
    if problems:
        raise PullError("lock file is invalid: " + "; ".join(problems[:3]))
    if entry.sha256 and lock_digest(lock) != entry.sha256:
        raise PullError("the lock file digest does not match models.toml; refusing")
    if entry.status == "verified" and not entry.sha256:
        raise PullError("verified entry without a lock digest in models.toml; refusing")

    dest = model_dir(entry.name, entry.revision, cache_root)
    if dest.exists() or dest.is_symlink():
        found = verify_dir(lock, dest)
        if not found:
            say("%s: already present and verified (%d files) in %s" % (entry.name, len(lock["files"]), dest))
            return dest
        raise PullError("%s exists but fails verification (%d problem(s), first: %s); "
                        "remove that directory and pull again" % (dest, len(found), found[0]))
    if offline:
        raise PullError("offline mode: %s is not in the cache" % entry.name)

    total = sum(f["size"] for f in lock["files"])
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(str(parent)).free
    if free < total + SPACE_MARGIN:
        raise PullError("not enough disk space: need about %s, %s free"
                        % (format_size(total + SPACE_MARGIN), format_size(free)))

    staging = parent / (".partial-" + entry.revision[:12] + "-" + secrets.token_hex(4))
    try:
        staging.mkdir()
        n = len(lock["files"])
        for i, f in enumerate(lock["files"], 1):
            say("  [%d/%d] %s (%s)" % (i, n, f["path"], format_size(f["size"])))
            url = resolve_url(base_url, repo, entry.revision, f["path"])
            try:
                download_file(url, staging.joinpath(*f["path"].split("/")), policy, token,
                              size=f["size"], sha256=f["sha256"])
            except FetchError as exc:
                raise PullError("%s: %s" % (f["path"], exc))
            except OSError as exc:
                raise PullError("%s: cannot write file (%s)" % (f["path"], type(exc).__name__))
        found = verify_dir(lock, staging)
        if found:
            raise PullError("verification after download failed: " + found[0])
        try:
            os.rename(str(staging), str(dest))
        except OSError as exc:
            raise PullError("cannot move the verified download into place (%s)" % type(exc).__name__)
    except BaseException:
        shutil.rmtree(str(staging), ignore_errors=True)
        raise
    say("%s: %d files verified and installed in %s" % (entry.name, n, dest))
    return dest


def plan_lock(source_url, revision, includes=(), excludes=(), policy=None, base_url=DEFAULT_BASE, token=None):
    """List the files a lock would cover, as [(path, size or None)], using the Hugging Face API."""
    policy = policy or Policy()
    repo = _repo_and_revision(source_url, revision)
    data = get_json("%s/api/models/%s/revision/%s?blobs=true" % (base_url.rstrip("/"), repo, revision), policy, token)
    if not isinstance(data, dict) or data.get("sha") != revision:
        raise PullError("the API did not return the requested revision; refusing")
    siblings = data.get("siblings")
    if not isinstance(siblings, list):
        raise PullError("unexpected API response (no file list)")
    sizes = {}
    for s in siblings:
        if not isinstance(s, dict) or not isinstance(s.get("rfilename"), str):
            raise PullError("unexpected API response (bad file entry)")
        size = s.get("size")
        sizes[s["rfilename"]] = size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None
    chosen = []
    for path in sorted(sizes):
        if includes and not any(fnmatch.fnmatchcase(path, pat) for pat in includes):
            continue
        if any(fnmatch.fnmatchcase(path, pat) for pat in excludes):
            continue
        chosen.append(path)
    if not chosen:
        raise PullError("no files selected")
    if len(chosen) > MAX_FILES:
        raise PullError("too many files (limit %d)" % MAX_FILES)
    bad = [p for p in chosen if safe_relpath(p)]
    if bad:
        raise PullError("unsupported file name(s), exclude them: " + ", ".join(repr(p) for p in bad[:5]))
    return [(p, sizes[p]) for p in chosen]


def build_lock(name, source_url, revision, plan, policy=None, base_url=DEFAULT_BASE, token=None, say=print):
    """Download every planned file (hash only, nothing is stored) and return the lock dict."""
    policy = policy or Policy()
    repo = _repo_and_revision(source_url, revision)
    files = []
    for i, (path, _) in enumerate(plan, 1):
        say("  [%d/%d] hashing %s" % (i, len(plan), path))
        try:
            size, digest = download_file(resolve_url(base_url, repo, revision, path), None, policy, token)
        except FetchError as exc:
            raise PullError("%s: %s" % (path, exc))
        files.append({"path": path, "size": size, "sha256": digest})
    lock = {"schema": SCHEMA, "model": name, "revision": revision, "source_url": source_url, "files": files}
    problems = validate_lock(lock, name=name, revision=revision)
    if problems:
        raise PullError("the built lock is invalid: " + "; ".join(problems[:3]))
    return lock
