# Generates parity recordings for the pure parts of ragleap_graph.extraction by running the real Python code:
# EntityDeduplicator (_similarity, _normalize, resolve), ExtractionConfig validation, and Python repr()/str() of JSON
# values (used by the LLM response parsers). The optional ragleap-rag classes are replaced by a fake provider class
# patched into the module. Writes extraction_core_cases.json into RAGLEAP_GRAPH_PARITY_DIR (default /tmp/fixtures-graph-a).
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0). Run with the
# system python (3.10 here, so Unicode 13 data for repr()).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, logging, os, random, sys
logging.disable(logging.CRITICAL)
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
assert rg.__file__.startswith(SRC), "wrong module path"
import ragleap_graph.extraction as ex
OUT = os.environ.get("RAGLEAP_GRAPH_PARITY_DIR", "/tmp/fixtures-graph-a")
os.makedirs(OUT, exist_ok=True)


class FakeProvider:
    pass


ex.ProviderConfig = FakeProvider  # so method="llm" configs can be built without ragleap-rag

rnd = random.Random(20261014)


def rstr(alpha, lo, hi):
    return "".join(rnd.choice(alpha) for _ in range(rnd.randint(lo, hi)))


# ---- ratio -----------------------------------------------------------------------------------------------------
pairs = [
    ("", ""), ("a", ""), ("", "a"), ("abc", "abc"), ("abcd", "bcde"), ("ab", "ac"),
    ("acme corp", "acme corporation"), ("acme corporation", "acme corp"), ("acme corp", "acme corp"),
    ("\U0001F600a", "\U0001F600b"), ("\uffffx", "\U00010000x"), ("\U00010000x", "\uffffx"),
    ("caf\u00e9 noir", "cafe noir"), ("\u4e2d\u6587\u516c\u53f8", "\u4e2d\u6587"),
    ("a" * 100 + "b" * 100, "a" * 50 + "b" * 150), ("b" * 200 + "a", "a" + "b" * 250),
    ("abab" * 60, "baba" * 60), ("x" * 199, "x" * 201), ("x" * 250 + "y", "y" + "x" * 250),
    ("the quick brown fox", "the quick brown fox jumps over the lazy dog"),
    ("initech llc", "initech"), ("globex industries inc", "globex industries"),
]
for _ in range(300):
    pairs.append((rstr("abc ", 0, 60), rstr("abc ", 0, 60)))
for _ in range(60):
    pairs.append((rstr("abcdef", 120, 320), rstr("abcdef", 150, 320)))
for _ in range(40):
    pairs.append((rstr("ab\u00e9\u4e2d\U0001F600", 0, 40), rstr("ab\u00e9\u4e2d\U0001F600", 0, 40)))
ratio_cases = [{"a": a, "b": b, "ratio": ex.EntityDeduplicator._similarity(a, b)} for a, b in pairs]

# ---- normalize -------------------------------------------------------------------------------------------------
POOL = ["Acme Corp", "ACME Corp.", "Acme Corporation", "acme corp", "Globex Industries", "Globex Industries Inc",
        "Globex", "T.C. Antony", "TC Antony", "T C Antony", "Initech", "Initech LLC", "Caf\u00e9 Noir", "Cafe Noir",
        "\U0001F600 Corp", "\u00dcn\u00efcode GmbH", "Unicode GmbH", "  Spaced   Out  ", "Spaced Out", "a-b_c", "abc",
        "ab", "ac", "Ab", "  ", "", ".", "x.y.z", "\u00a0nbsp\u00a0", "tab\tsep", "zero\u200bwidth",
        "CJK \u4e2d\u6587\u516c\u53f8", "\u4e2d\u6587\u516c\u53f8"]
EXTRA_NORM = ["A.B-C_D,E", "  multiple   spaces\there\nnewline ", "\x1c\x1d\x1e\x1fx", "\u0130stanbul", "\u0391\u03a3",
              "\u00df", "\u01c5", "\ufb01", "a . b", " . x", "x , y", "\u2003em\u2003space\u2003", "\u200bzw", ",.-_"]
normalize_cases = [{"name": n, "normalized": ex.EntityDeduplicator._normalize(n)} for n in POOL + EXTRA_NORM]

# ---- resolve ---------------------------------------------------------------------------------------------------
resolve_inputs = [
    (["ab", "ac"], 0.5), (["Acme Co", "ACME CO"], 0.92), ([], 0.92), (["only"], 0.92), (["x", "x"], 0.92),
    (["Acme Corp", "ACME Corp.", "Globex"], 0.92), (["abcdefghij", "abcdefghxx", "abcdefxxxx"], 0.8),
    (POOL, 0.92), (POOL, 0.7), (POOL, 0.5), (POOL, 1.0),
]
for _ in range(90):
    names = [rnd.choice(POOL) for _ in range(rnd.randint(2, 9))]
    resolve_inputs.append((names, rnd.choice([0.5, 0.7, 0.8, 0.92, 1.0])))
resolve_cases = []
for names, t in resolve_inputs:
    m = ex.EntityDeduplicator(threshold=t).resolve(list(names))
    resolve_cases.append({"names": names, "threshold": t, "mapping": [[k, v] for k, v in m.items()]})
for t in (0, -1, 1.5, "nan"):
    real = float("nan") if t == "nan" else t
    try:
        ex.EntityDeduplicator(threshold=real)
        resolve_cases.append({"names": [], "threshold": t, "error": None})
    except Exception as e:
        resolve_cases.append({"names": [], "threshold": t, "error": type(e).__name__, "message": str(e)})


# ---- config ----------------------------------------------------------------------------------------------------
def cc(name, **spec):
    kwargs = dict(spec)
    prov = kwargs.pop("provider", False)
    real = dict(kwargs)
    if prov:
        real["provider"] = FakeProvider()
    if real.get("relation_ontology") is not None:
        real["relation_ontology"] = {k: (list(v[0]), list(v[1])) for k, v in real["relation_ontology"].items()}
    if real.get("dedup_threshold") == "nan":
        real["dedup_threshold"] = float("nan")
    rec = {"name": name, "kwargs": kwargs, "provider": bool(prov)}
    try:
        c = ex.ExtractionConfig(**real)
        rec["ok"] = True
        rec["fields"] = {"method": c.method, "dedup_enabled": c.dedup_enabled, "dedup_threshold": c.dedup_threshold,
                         "max_entities_per_chunk": c.max_entities_per_chunk, "extract_relations": c.extract_relations,
                         "cross_chunk_relations": c.cross_chunk_relations, "entity_types": c.entity_types}
    except Exception as e:
        rec["ok"] = False
        rec["error_type"] = type(e).__name__
        rec["message"] = str(e)
    return rec


ONT = {"WORKS_AT": [["PERSON"], ["ORG"]]}
config_cases = [
    cc("default"),
    cc("regex_dedup", dedup_enabled=True, dedup_threshold=0.5),
    cc("relations_need_llm", extract_relations=True),
    cc("relations_llm_ok", method="llm", provider=True, extract_relations=True),
    cc("cross_without_relations", method="llm", provider=True, cross_chunk_relations=True),
    cc("cross_with_relations", method="llm", provider=True, extract_relations=True, cross_chunk_relations=True),
    cc("ontology_without_types", method="llm", provider=True, extract_relations=True, relation_ontology=ONT),
    cc("ontology_empty_dict_no_types", relation_ontology={}),
    cc("ontology_empty_types", method="llm", provider=True, extract_relations=True, entity_types=[],
       relation_ontology={"A": [["X"], ["Y"]]}),
    cc("ontology_ok", method="llm", provider=True, extract_relations=True, entity_types=["PERSON", "ORG"],
       relation_ontology=ONT),
    cc("llm_without_provider", method="llm"),
    cc("llm_ok_types", method="llm", provider=True, entity_types=["PERSON"]),
    cc("threshold_zero", dedup_threshold=0.0),
    cc("threshold_negative", dedup_threshold=-0.1),
    cc("threshold_above_one", dedup_threshold=1.0001),
    cc("threshold_one", dedup_threshold=1.0),
    cc("threshold_nan", dedup_threshold="nan"),
    cc("max_zero", max_entities_per_chunk=0),
    cc("max_negative", max_entities_per_chunk=-3),
    cc("max_one", max_entities_per_chunk=1),
    cc("order_relations_before_threshold", extract_relations=True, dedup_threshold=5.0),
    cc("order_cross_before_ontology", method="llm", provider=True, cross_chunk_relations=True,
       relation_ontology={"A": [["X"], ["Y"]]}),
    cc("order_ontology_before_provider", method="llm", relation_ontology={"A": [["X"], ["Y"]]}),
    cc("order_provider_before_threshold", method="llm", dedup_threshold=2.0),
    cc("order_threshold_before_max", dedup_threshold=2.0, max_entities_per_chunk=0),
]

# ---- repr / str of JSON values ---------------------------------------------------------------------------------
VALUES = [
    "plain", "it's", 'say "hi"', "both ' and \"", "back\\slash", "nl\nx", "tab\tx", "cr\rx", "ctl\x01x", "del\x7fx",
    "nbsp\u00a0x", "zw\u200bx", "ls\u2028x", "caf\u00e9", "\u4e2d\u6587", "\U0001F600", "\ud800lone", "unassigned\u0378",
    "private\ue000", "tag\U000e0001", "", " ", "'", '"', "\\", "\x00", "\x80", "\xad", "a\u2003b", "\U0010ffff",
    0, 1, -7, 10 ** 20, 1.0, 1.5, 0.1, 1e20, 1e-07, 123456789.125, -0.0, 100.0, True, False, None,
    [], {}, [1, "a", None, True, 1.5], {"k": "v"}, {"k": [1, {"n": None}], "\u00e9": "it's"},
    ["it's", 'say "x"', "plain"], {"a": {"b": {"c": [1, 2, 3]}}}, {"x": 1, "y": 2.0, "z": "w"},
]
repr_cases = [{"value": v, "repr": repr(v), "str": str(v)} for v in VALUES]

data = {"ratio": ratio_cases, "normalize": normalize_cases, "resolve": resolve_cases, "config": config_cases,
        "repr": repr_cases}
json.dump(data, open(os.path.join(OUT, "extraction_core_cases.json"), "w"))
print("ratio:", len(ratio_cases), "| normalize:", len(normalize_cases), "| resolve:", len(resolve_cases),
      "| config:", len(config_cases), "| repr:", len(repr_cases), "| written to", OUT)
print("config errors by python type:", sorted({c["error_type"] for c in config_cases if not c["ok"]}))
