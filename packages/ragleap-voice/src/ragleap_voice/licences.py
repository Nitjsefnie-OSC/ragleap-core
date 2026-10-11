"""Licence policy: allowlist and manifest validation. Standard library only."""
import re

ALLOWED = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "CC-BY-4.0",
})
ATTRIBUTION_REQUIRED = frozenset({"CC-BY-4.0"})
REQUIRED_FIELDS = (
    "name", "kind", "source_url", "revision", "sha256", "code_license",
    "weights_license", "languages", "capabilities", "min_hardware",
    "status", "default",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def check_licence(expr):
    """Return (ok, reason) for an SPDX expression. Anything not allowlisted fails."""
    expr = (expr or "").strip()
    if not expr:
        return False, "empty licence"
    if "(" in expr or ")" in expr:
        return False, "compound expression with parentheses: review manually"
    if " AND " in expr:
        parts = [p.strip() for p in expr.split(" AND ")]
        bad = [p for p in parts if p not in ALLOWED]
        return (not bad), ("ok" if not bad else "not allowlisted: " + ", ".join(bad))
    if " OR " in expr:
        parts = [p.strip() for p in expr.split(" OR ")]
        ok = any(p in ALLOWED for p in parts)
        return ok, ("ok" if ok else "no allowlisted alternative")
    ok = expr in ALLOWED
    return ok, ("ok" if ok else "not allowlisted: " + expr)


def validate_entries(entries, notices_text=""):
    """Return a list of problem strings (empty list means the manifest passes)."""
    problems = []
    names = set()
    for i, e in enumerate(entries):
        label = str(e.get("name", "entry#" + str(i)))
        for f in REQUIRED_FIELDS:
            if f not in e:
                problems.append(label + ": missing field " + f)
        if label in names:
            problems.append(label + ": duplicate name")
        names.add(label)
        if not e.get("default"):
            continue
        if e.get("status") != "verified":
            problems.append(label + ": default=true requires status=verified")
        if not e.get("revision"):
            problems.append(label + ": default=true requires a pinned revision")
        if not _HEX64.match(str(e.get("sha256", ""))):
            problems.append(label + ": default=true requires a 64-hex sha256")
        for key in ("code_license", "weights_license"):
            ok, why = check_licence(e.get(key, ""))
            if not ok:
                problems.append(label + ": " + key + " " + why)
            elif e.get(key) in ATTRIBUTION_REQUIRED and label not in notices_text:
                problems.append(label + ": " + key + " needs attribution in THIRD_PARTY_NOTICES.md")
    return problems
