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
OPTIONAL_FIELDS = ("depends_on",)
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
        is_default = bool(e.get("default"))
        is_verified = e.get("status") == "verified"
        if not (is_default or is_verified):
            continue
        if is_default and not is_verified:
            problems.append(label + ": default=true requires status=verified")
        if not e.get("revision"):
            problems.append(label + ": a verified or default entry requires a pinned revision")
        if not _HEX64.match(str(e.get("sha256", ""))):
            problems.append(label + ": a verified or default entry requires a 64-hex sha256")
        for key in ("code_license", "weights_license"):
            ok, why = check_licence(e.get(key, ""))
            if not ok:
                problems.append(label + ": " + key + " " + why)
            elif e.get(key) in ATTRIBUTION_REQUIRED and label not in notices_text:
                problems.append(label + ": " + key + " needs attribution in THIRD_PARTY_NOTICES.md")
    by_name = {str(e.get("name")): e for e in entries if isinstance(e, dict)}
    graph = {}
    for i, e in enumerate(entries):
        label = str(e.get("name", "entry#" + str(i)))
        deps = e.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            problems.append(label + ": depends_on must be a list of strings")
            continue
        if len(set(deps)) != len(deps):
            problems.append(label + ": depends_on lists a model twice")
        known = []
        for d in deps:
            if d == label:
                problems.append(label + ": depends_on itself")
            elif d not in by_name:
                problems.append(label + ": depends_on unknown model " + repr(d))
            else:
                known.append(d)
        graph[label] = known
        if e.get("default") or e.get("status") == "verified":
            for d in known:
                if by_name[d].get("status") != "verified":
                    problems.append(label + ": a verified or default entry depends on " + d + ", which is not verified")
    state = {}

    def visit(node, trail):
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            problems.append("dependency cycle: " + " -> ".join(trail[trail.index(node):] + [node]))
            return
        state[node] = 1
        for d in graph.get(node, []):
            visit(d, trail + [node])
        state[node] = 2

    for node in list(graph):
        visit(node, [])
    return problems
