"""Command line for ragleap-voice (pre-alpha). Standard library only.

Currently read-only: it inspects the model manifest. Nothing is downloaded.
"""
import argparse
import dataclasses
import json
import pathlib
import sys

from . import __version__
from .cache import cache_root, model_dir
from .locks import LockError, load_lock, lock_digest, validate_lock, verify_dir
from .manifest import ManifestError, default_manifest_path, load_manifest, lock_problems


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


def _cmd_verify(args):
    entries, _ = load_manifest(args.manifest)
    match = [e for e in entries if e.name == args.name]
    if not match:
        print("error: unknown model " + repr(args.name) + " (try: ragleap-voice models list)", file=sys.stderr)
        return 1
    e = match[0]
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
    ver = leaf("verify", "verify a cached model against its lock file (offline, read-only)", _cmd_verify)
    ver.add_argument("name")
    ver.add_argument("--cache-dir", metavar="PATH", help="use this cache root instead of the default")
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
    except (ManifestError, LockError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1
