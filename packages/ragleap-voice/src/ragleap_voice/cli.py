"""Command line for ragleap-voice (pre-alpha). Standard library only.

Currently read-only: it inspects the model manifest. Nothing is downloaded.
"""
import argparse
import dataclasses
import json
import os
import pathlib
import sys

from . import __version__
from .cache import cache_root, model_dir
from .locks import UNSAFE_SUFFIXES, LockError, load_lock, lock_digest, validate_lock, verify_dir
from .fetch import DEFAULT_BASE, FetchError, Policy
from .manifest import ManifestError, default_manifest_path, load_manifest, lock_problems
from .pull import PullError, build_lock, dependency_order, format_size, plan_lock, pull_model, token_from_env


def _table(entries):
    header = ("NAME", "KIND", "STATUS", "DEFAULT", "CODE LICENCE", "WEIGHTS LICENCE", "LANGUAGES")
    rows = [(e.name, e.kind, e.status, "yes" if e.default else "no", e.code_license,
             e.weights_license, ",".join(e.languages) or "-") for e in entries]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(header)]

    def fmt(cols):
        return "  ".join(c.ljust(w) for c, w in zip(cols, widths)).rstrip()

    return "\n".join([fmt(header)] + [fmt(r) for r in rows])


def _cmd_list(args):
    entries, _ = load_manifest(args.manifest)
    if args.kind:
        entries = [e for e in entries if e.kind == args.kind]
    if args.json:
        print(json.dumps([dataclasses.asdict(e) for e in entries], indent=2, ensure_ascii=False))
        return 0
    if not entries:
        print("no models match")
        return 0
    print(_table(entries))
    print("\nStatus 'unverified' means a lead from research, not an endorsement.")
    return 0


def _cmd_show(args):
    entries, _ = load_manifest(args.manifest)
    match = [e for e in entries if e.name == args.name]
    if not match:
        print("error: unknown model " + repr(args.name) + " (try: ragleap-voice models list)", file=sys.stderr)
        return 1
    e = match[0]
    d = dataclasses.asdict(e)
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0
    for key, value in d.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(value) or "-"
        elif isinstance(value, bool):
            value = "yes" if value else "no"
        elif value == "":
            value = "-"
        print((key + ":").ljust(17) + str(value))
    if e.status != "verified":
        print("\nnote: unverified. Revision, hash and licences are not confirmed at the source; "
              "this entry cannot be a default.")
    return 0


def _cmd_check(args):
    entries, problems = load_manifest(args.manifest)
    problems = list(problems) + lock_problems(entries, args.manifest)
    if problems:
        print("manifest has %d problem(s):" % len(problems), file=sys.stderr)
        for p in problems:
            print(" - " + p, file=sys.stderr)
        return 1
    print("manifest OK: %d model(s), %d verified, %d default" % (
        len(entries), sum(e.status == "verified" for e in entries), sum(e.default for e in entries)))
    return 0


def _verify_one(args, e):
    if not e.revision:
        print("error: " + e.name + " has no pinned revision, so there is nothing to verify against", file=sys.stderr)
        return 1
    mpath = pathlib.Path(args.manifest) if args.manifest else default_manifest_path()
    lp = mpath.parent / "locks" / (e.name + ".json")
    if not lp.is_file():
        print("error: no lock file for " + e.name + " (expected " + str(lp) + ")", file=sys.stderr)
        return 1
    lock = load_lock(lp)
    problems = validate_lock(lock, name=e.name, revision=e.revision)
    if not problems and e.sha256 and lock_digest(lock) != e.sha256:
        problems = ["sha256 in models.toml does not match the lock file digest"]
    if not problems:
        root = pathlib.Path(args.cache_dir) if args.cache_dir else cache_root()
        directory = model_dir(e.name, e.revision, root)
        problems = verify_dir(lock, directory)
    if problems:
        print("verification of " + e.name + " failed (%d problem(s)):" % len(problems), file=sys.stderr)
        for p in problems:
            print(" - " + p, file=sys.stderr)
        return 1
    print("%s: %d file(s) verified OK in %s" % (e.name, len(lock["files"]), directory))
    return 0


def _network():
    """Network settings for pull and lock. Strict and fixed; tests replace this function."""
    return Policy(), DEFAULT_BASE


def _offline(args):
    if args.offline:
        return True
    return os.environ.get("RAGLEAP_VOICE_OFFLINE", "").strip().lower() in ("1", "true", "yes")


def _locate(args):
    entries, _ = load_manifest(args.manifest)
    match = [e for e in entries if e.name == args.name]
    if not match:
        raise PullError("unknown model " + repr(args.name) + " (try: ragleap-voice models list)")
    mpath = pathlib.Path(args.manifest) if args.manifest else default_manifest_path()
    return match[0], mpath.parent / "locks" / (match[0].name + ".json")


def _cmd_pull(args):
    entries, _ = load_manifest(args.manifest)
    by_name = {e.name: e for e in entries}
    entry = by_name.get(args.name)
    if entry is None:
        raise PullError("unknown model " + repr(args.name) + " (try: ragleap-voice models list)")
    order = dependency_order(entry, by_name)
    mpath = pathlib.Path(args.manifest) if args.manifest else default_manifest_path()
    plan = []
    for e in order:
        lp = mpath.parent / "locks" / (e.name + ".json")
        if not lp.is_file():
            raise PullError("no lock file for %s (expected %s); a maintainer creates it with 'models lock'" % (e.name, lp))
        plan.append((e, load_lock(lp)))
    if len(plan) > 1:
        print("pulling %d models, dependencies first: %s" % (len(plan), ", ".join(e.name for e, _ in plan)))
    root = pathlib.Path(args.cache_dir) if args.cache_dir else cache_root()
    policy, base = _network()
    token = token_from_env(os.environ)
    dest = None
    for e, lock in plan:
        dest = pull_model(e, lock, root, policy=policy, base_url=base, token=token,
                          offline=_offline(args), allow_unverified=args.allow_unverified, say=print)
    print("%s is ready at %s" % (entry.name, dest))
    return 0


def _cmd_lock(args):
    entry, _ = _locate(args)
    out = pathlib.Path(args.out)
    if out.exists() and not args.overwrite:
        raise PullError(str(out) + " already exists (use --overwrite)")
    policy, base = _network()
    token = token_from_env(os.environ)
    plan = plan_lock(entry.source_url, args.revision, includes=tuple(args.include or ()),
                     excludes=tuple(args.exclude or ()), policy=policy, base_url=base, token=token)
    known = sum(s or 0 for _, s in plan)
    print("%d file(s), about %s according to the API:" % (len(plan), format_size(known)))
    for path, size in plan[:50]:
        print("  %s  %s" % (path, format_size(size) if size is not None else "?"))
    if len(plan) > 50:
        print("  ... and %d more" % (len(plan) - 50))
    risky = [p for p, _ in plan if p.lower().endswith(UNSAFE_SUFFIXES)]
    if risky:
        print()
        print("NOTE: %d file(s) are in pickle-capable formats (for example %s). Loading such files can run code, "
              "and an entry whose lock lists them cannot be marked verified. Use --exclude to leave them out." % (len(risky), risky[0]))
    if not args.yes:
        print("\nThis downloads every file above to hash it. Do not run it on a production server "
              "(use a notebook or a laptop). Re-run with --yes to continue.")
        return 2
    lock = build_lock(entry.name, entry.source_url, args.revision, plan, policy=policy, base_url=base,
                      token=token, say=print)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote " + str(out))
    print("lock digest (the sha256 value for models.toml): " + lock_digest(lock))
    print("Next: a person reviews the lock, then sets revision and sha256 in models.toml. "
          "The entry stays 'unverified' until that review.")
    return 0


def _cmd_verify(args):
    entries, _ = load_manifest(args.manifest)
    by_name = {e.name: e for e in entries}
    if args.name not in by_name:
        print("error: unknown model " + repr(args.name) + " (try: ragleap-voice models list)", file=sys.stderr)
        return 1
    rc = 0
    for e in dependency_order(by_name[args.name], by_name):
        rc = max(rc, _verify_one(args, e))
    return rc


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ragleap-voice", description="Open, local speech-to-text and text-to-speech (pre-alpha).")
    parser.add_argument("--version", action="version", version="ragleap-voice " + __version__)
    sub = parser.add_subparsers(dest="command", metavar="command")
    models = sub.add_parser("models", help="inspect the model manifest (read-only)")
    msub = models.add_subparsers(dest="models_command", metavar="subcommand")

    def leaf(name, help_text, func):
        p = msub.add_parser(name, help=help_text)
        p.add_argument("--manifest", metavar="PATH", help="use this models.toml instead of the packaged one")
        p.set_defaults(func=func)
        return p

    ls = leaf("list", "list models in the manifest", _cmd_list)
    ls.add_argument("--kind", help="only this kind, for example stt or tts")
    ls.add_argument("--json", action="store_true", help="machine-readable output")
    show = leaf("show", "show one manifest entry", _cmd_show)
    show.add_argument("name")
    show.add_argument("--json", action="store_true", help="machine-readable output")
    leaf("check", "validate the manifest and its lock files against the licence policy", _cmd_check)
    ver = leaf("verify", "verify a cached model and its dependencies against their lock files (offline, read-only)", _cmd_verify)
    ver.add_argument("name")
    ver.add_argument("--cache-dir", metavar="PATH", help="use this cache root instead of the default")
    pl = leaf("pull", "download a model (and its dependencies) from Hugging Face and verify it against its lock file", _cmd_pull)
    pl.add_argument("name")
    pl.add_argument("--cache-dir", metavar="PATH", help="use this cache root instead of the default")
    pl.add_argument("--allow-unverified", action="store_true", help="also pull entries whose status is not verified")
    pl.add_argument("--offline", action="store_true", help="no network: only check what is already cached (also RAGLEAP_VOICE_OFFLINE=1)")
    lk = leaf("lock", "maintainer tool: build a lock file by downloading and hashing every file (large downloads)", _cmd_lock)
    lk.add_argument("name")
    lk.add_argument("--revision", required=True, metavar="COMMIT", help="full 40-character commit hash to pin")
    lk.add_argument("--out", required=True, metavar="PATH", help="where to write the lock JSON")
    lk.add_argument("--include", action="append", metavar="PATTERN", help="only files matching this pattern (repeatable)")
    lk.add_argument("--exclude", action="append", metavar="PATTERN", help="skip files matching this pattern (repeatable)")
    lk.add_argument("--overwrite", action="store_true", help="replace an existing lock file")
    lk.add_argument("--yes", action="store_true", help="confirm the large download")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        return func(args)
    except (ManifestError, LockError, PullError, FetchError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1
