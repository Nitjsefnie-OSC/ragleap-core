# Generates parity recordings for the LLM entity and relation extractors by running the real Python classes against a
# fake GenerationService (patched into the module) that records every call (query, chunks, response_format,
# temperature) and returns scripted model answers. Also records what the real classes pass to the service constructor.
# Writes extraction_llm_cases.json into RAGLEAP_GRAPH_PARITY_DIR (default /tmp/fixtures-graph-a).
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, logging, os, sys
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


class FakeGen:
    def __init__(self, primary=None, default_temperature=None, system_prompt=None, **kw):
        self.system_prompt = system_prompt
        self.default_temperature = default_temperature
        self.calls = []
        self.result = None

    def generate_answer(self, query, chunks, response_format=None, temperature=None, **kw):
        self.calls.append({"query": query, "chunks": chunks, "response_format": response_format,
                           "temperature": temperature})
        return self.result


ex.ProviderConfig = FakeProvider
ex.GenerationService = FakeGen


def make_cfg(spec):
    spec = dict(spec or {})
    method = spec.pop("method", "llm")
    kw = {"method": method}
    if method == "llm":
        kw["provider"] = FakeProvider()
    ont = spec.pop("relation_ontology", None)
    if ont is not None:
        kw["relation_ontology"] = {k: (list(v[0]), list(v[1])) for k, v in ont.items()}
    kw.update(spec)
    return ex.ExtractionConfig(**kw)


def sv(key, items):
    return {"provider_used": "fake", "answer": json.dumps({key: items}), "structured": {key: items},
            "structured_valid": True, "structured_enforcement": "native"}


def fb(answer, enforcement="json_object"):
    return {"provider_used": "fake", "answer": answer, "structured": None, "structured_valid": False,
            "structured_enforcement": enforcement}


def stv(obj, answer="{}"):
    return {"provider_used": "fake", "answer": answer, "structured": obj, "structured_valid": True,
            "structured_enforcement": "native"}


def ent(n, t="X"):
    return {"name": n, "type": t}


def rel(s, t, o):
    return {"subject": s, "relation_type": t, "object": o}


def E(name, result=None, text="Acme Corp met Bob.", **kw):
    c = {"name": name, "kind": "entity", "text": text, "result": result if result is not None else sv("entities", [])}
    c.update(kw)
    return c


KNOWN = ["Acme Corp", "Globex"]


def R(name, result=None, text="Acme Corp partnered with Globex.", known=KNOWN, **kw):
    c = {"name": name, "kind": "relation", "text": text, "known_entities": list(known),
         "result": result if result is not None else sv("relations", [])}
    c.update(kw)
    return c


NO_PROVIDER = {"answer": "boom", "structured": None, "structured_valid": False}
NO_ANSWER = {"provider_used": "fake", "structured": None, "structured_valid": False}
ONT = {"WORKS_AT": [["PERSON"], ["ORG"]]}
TYPES = ["PERSON", "ORG"]
TYPEMAP = {"alice": "PERSON", "acme": "ORG", "bob": "PERSON"}
RK = ["Alice", "Acme", "Bob", "Carol"]

C = [
    E("basic", sv("entities", [ent("Acme Corp", "ORG"), ent("Bob", "PERSON")])),
    E("text_unstripped", sv("entities", [ent("Acme", "ORG")]), text="  Acme Corp ships.  \n"),
    E("blank_text_no_call", text="   \t\n"),
    E("empty_text_no_call", text=""),
    E("nbsp_text_no_call", text="\u00a0\u2003"),
    E("domain_terms", domain_terms=["Widget", "Gizmo"]),
    E("domain_terms_empty_list", domain_terms=[]),
    E("entity_types_in_prompt", config={"entity_types": ["ORG", "PERSON"]}, domain_terms=["Widget"]),
    E("entity_types_coerce", sv("entities", [ent("A", "ORG"), ent("B", "Org"), ent("C", "PERSON"), ent("D", ""),
                                             ent("E", None), {"name": "F"}]), config={"entity_types": ["ORG"]}),
    E("types_unconstrained", sv("entities", [ent("A", "weird"), ent("B", ""), ent("C", None), ent("D", 5),
                                             ent("E", True), ent("F", 1.5), ent("G", ["a"])])),
    E("names_dedupe_and_blank", sv("entities", [ent("Acme"), ent("ACME"), ent("  acme  "), ent(""), ent("  "),
                                                ent("Bob")])),
    E("name_null", sv("entities", [ent(None, "X"), ent("Ok")])),
    E("name_other_types", sv("entities", [ent(123), ent(1.5), ent(True), ent(False), ent(["a", "b"]),
                                          ent({"k": "v"}), ent(10 ** 25)])),
    E("name_missing", sv("entities", [{"type": "X"}, {"name": "Ok"}])),
    E("unicode_names", sv("entities", [ent("\u00a0Acme\u00a0"), ent("\u00c9cole"), ent("\u00c9COLE"),
                                       ent("\U0001F600 Corp"), ent("\u0130stanbul"), ent("i\u0307stanbul"),
                                       ent("\u00df"), ent("SS")])),
    E("cap_counts_blank_slot", sv("entities", [ent(""), ent("A"), ent("B"), ent("C")]),
      config={"max_entities_per_chunk": 2}),
    E("cap_one", sv("entities", [ent("A"), ent("B")]), config={"max_entities_per_chunk": 1}),
    E("cap_with_duplicates", sv("entities", [ent("A"), ent("a"), ent("B"), ent("C")]),
      config={"max_entities_per_chunk": 3}),
    E("fallback_answer_valid", fb(json.dumps({"entities": [ent("FromAnswer", "ORG")]}))),
    E("structured_invalid_uses_answer", {"provider_used": "fake",
                                         "answer": json.dumps({"entities": [ent("Answer")]}),
                                         "structured": {"entities": [ent("Structured")]},
                                         "structured_valid": False, "structured_enforcement": "native"}),
    E("structured_not_dict", {"provider_used": "fake", "answer": json.dumps({"entities": [ent("FromAnswer")]}),
                              "structured": ["x"], "structured_valid": True, "structured_enforcement": "native"}),
    E("structured_entities_null", stv({"entities": None}, json.dumps({"entities": [ent("FromAnswer")]}))),
    E("structured_entities_missing", stv({}, json.dumps({"entities": [ent("FromAnswer")]}))),
    E("fallback_invalid_json", fb("not json at all")),
    E("fallback_empty_answer", fb("")),
    E("fallback_whitespace_answer", fb("   \n")),
    E("fallback_answer_absent", NO_ANSWER),
    E("fallback_json_list", fb("[1, 2]")),
    E("fallback_json_null", fb("null")),
    E("fallback_json_string", fb('"entities"')),
    E("fallback_trailing_data", fb('{"entities": []} trailing')),
    E("fallback_nan_name", fb('{"entities": [{"name": NaN, "type": "X"}]}')),
    E("fallback_infinity", fb('{"entities": [{"name": Infinity, "type": -Infinity}]}')),
    E("fallback_duplicate_keys", fb('{"entities": [{"name": "A", "name": "B", "type": "T"}]}')),
    E("fallback_single_quotes", fb("{'entities': []}")),
    E("fallback_trailing_comma", fb('{"entities": [],}')),
    E("fallback_bigint", fb('{"entities": [{"name": 12345678901234567890123, "type": "T"}]}')),
    E("fallback_float_forms", fb('{"entities": [{"name": 1e2, "type": 1.0}, {"name": 0.1, "type": 1e-7},'
                                 ' {"name": -0.0, "type": 2.5E+3}]}')),
    E("fallback_json_whitespace", fb('  \n {"entities": [{"name": "A", "type": "T"}]}\n\t')),
    E("fallback_control_char", fb('{"entities": [{"name": "a\tb", "type": "T"}]}')),
    E("fallback_escapes", fb('{"entities": [{"name": "caf\\u00e9 \\ud83d\\ude00 \\n", "type": "T"}]}')),
    E("entities_dict_typeerror", stv({"entities": {"a": 1}})),
    E("entities_string_attribute", stv({"entities": "abc"})),
    E("entities_empty_string", stv({"entities": ""})),
    E("entities_int", stv({"entities": 5})),
    E("entities_true", stv({"entities": True})),
    E("entities_float", stv({"entities": 1.5})),
    E("items_str", sv("entities", ["x"])),
    E("items_int", sv("entities", [1])),
    E("items_null", sv("entities", [None])),
    E("items_list", sv("entities", [["a"]])),
    E("items_bool", sv("entities", [True])),
    E("items_float", sv("entities", [1.5])),
    E("items_valid_then_bad", sv("entities", [ent("A"), "bad"])),
    E("items_bad_beyond_cap", sv("entities", [ent("A"), "bad"]), config={"max_entities_per_chunk": 1}),
    E("provider_none", {"provider_used": None, "answer": "all providers failed", "structured": None,
                        "structured_valid": False}),
    E("provider_missing", NO_PROVIDER),
    E("provider_none_answer_absent", {"provider_used": None}),
    E("ctor_regex_config", config={"method": "regex"}),

    R("rel_basic", sv("relations", [rel("Acme Corp", "partnered_with", "Globex")])),
    R("rel_fewer_than_two_known", known=["A"]),
    R("rel_no_known", known=[]),
    R("rel_blank_text", text="  \t"),
    R("rel_duplicate_known_counts", sv("relations", [rel("A", "X", "A")]), known=["A", "A"]),
    R("rel_model_casing_kept", sv("relations", [rel("acme corp", "X", "GLOBEX")])),
    R("rel_unknown_entity_dropped", sv("relations", [rel("Nobody", "X", "Globex"), rel("Acme Corp", "X", "Nobody"),
                                                     rel("Acme Corp", "X", "Globex")])),
    R("rel_self_relation_dropped", sv("relations", [rel("Acme Corp", "X", "ACME CORP")])),
    R("rel_empty_fields_skipped", sv("relations", [rel("", "X", "Globex"), rel("Acme Corp", "", "Globex"),
                                                   rel("Acme Corp", "X", ""), rel("  ", "X", "Globex"),
                                                   {"subject": "Acme Corp", "object": "Globex"},
                                                   rel("Acme Corp", "X", "Globex")])),
    R("rel_type_upper_strip", sv("relations", [rel("Acme Corp", " reported ", "Globex"),
                                               rel("Acme Corp", "partnered with", "Globex"),
                                               rel("Acme Corp", "stra\u00dfe", "Globex"),
                                               rel("Acme Corp", "\u0149x", "Globex"),
                                               rel("Acme Corp", "\u01c6\ufb01\u01f0", "Globex"),
                                               rel("Acme Corp", "\u0130\u0131", "Globex"),
                                               rel("Acme Corp", "\u0390", "Globex")])),
    R("rel_type_other_values", sv("relations", [rel("Acme Corp", None, "Globex"), rel("Acme Corp", 5, "Globex"),
                                                rel("Acme Corp", True, "Globex"), rel("Acme Corp", 1.5, "Globex")])),
    R("rel_subject_other_values", sv("relations", [rel(None, "X", "Globex"), rel(["a"], "X", "Globex")]),
      known=["None", "Globex", "['a']"]),
    R("rel_unicode_lower_match", sv("relations", [rel("\u00c9COLE", "X", "Globex"), rel("STRASSE", "Y", "Globex")]),
      known=["\u00c9cole", "Stra\u00dfe", "Globex"]),
    R("rel_resolve_references", resolve_references=True),
    R("rel_domain_terms", domain_terms=["Widget"]),
    R("rel_domain_terms_and_resolve", domain_terms=["Widget", "Gizmo"], resolve_references=True),
    R("rel_text_unstripped", sv("relations", [rel("Acme Corp", "X", "Globex")]), text="  Acme.  \n"),
    R("rel_ontology_filter", sv("relations", [rel("Alice", "WORKS_AT", "Acme"), rel("Acme", "WORKS_AT", "Alice"),
                                              rel("Acme", "REPORTED", "Alice"), rel("Bob", "WORKS_AT", "Carol"),
                                              rel("Bob", "works_at", "Acme"), rel("Carol", "WORKS_AT", "Acme")]),
      known=RK, config={"entity_types": TYPES, "relation_ontology": ONT}, entity_types=TYPEMAP),
    R("rel_ontology_no_types", sv("relations", [rel("Alice", "WORKS_AT", "Acme"), rel("Acme", "WORKS_AT", "Alice")]),
      known=RK, config={"entity_types": TYPES, "relation_ontology": ONT}, entity_types=None),
    R("rel_ontology_empty_types", sv("relations", [rel("Acme", "WORKS_AT", "Alice")]),
      known=RK, config={"entity_types": TYPES, "relation_ontology": ONT}, entity_types={}),
    R("rel_types_without_ontology", sv("relations", [rel("Acme", "WORKS_AT", "Alice")]), known=RK,
      entity_types=TYPEMAP),
    R("rel_fallback_valid", fb(json.dumps({"relations": [rel("Acme Corp", "X", "Globex")]}))),
    R("rel_fallback_invalid", fb("nope")),
    R("rel_fallback_answer_absent", NO_ANSWER),
    R("rel_fallback_json_list", fb("[]")),
    R("rel_fallback_nan", fb('{"relations": [{"subject": NaN, "relation_type": "X", "object": "Globex"}]}'),
      known=["nan", "Globex"]),
    R("rel_structured_null_fallback", stv({"relations": None}, json.dumps({"relations": [rel("Acme Corp", "X", "Globex")]}))),
    R("rel_relations_dict", stv({"relations": {"a": 1}})),
    R("rel_relations_empty_dict", stv({"relations": {}})),
    R("rel_relations_string", stv({"relations": "abc"})),
    R("rel_relations_empty_string", stv({"relations": ""})),
    R("rel_relations_int", stv({"relations": 5})),
    R("rel_relations_true", stv({"relations": True})),
    R("rel_relations_float", stv({"relations": 1.5})),
    R("rel_items_str", sv("relations", ["x"])),
    R("rel_items_int", sv("relations", [1])),
    R("rel_items_null", sv("relations", [None])),
    R("rel_items_list", sv("relations", [["a"]])),
    R("rel_items_valid_then_bad", sv("relations", [rel("Acme Corp", "X", "Globex"), 7])),
    R("rel_provider_none", {"provider_used": None, "answer": "all failed", "structured": None,
                            "structured_valid": False}),
    R("rel_provider_missing", NO_PROVIDER),
    R("rel_ctor_regex_config", config={"method": "regex"}),
]


def run(c):
    rec = dict(c)
    try:
        cfg = make_cfg(c.get("config"))
        ext = ex.LLMEntityExtractor(cfg) if c["kind"] == "entity" else ex.LLMRelationExtractor(cfg)
    except Exception as e:
        rec["ctor_raises"] = type(e).__name__
        rec["ctor_message"] = str(e)
        rec["calls"] = []
        return rec
    svc = ext._service
    svc.result = c["result"]
    rec["ctor"] = {"system_prompt": svc.system_prompt, "default_temperature": svc.default_temperature}
    try:
        if c["kind"] == "entity":
            out = ext.extract(c["text"], domain_terms=c.get("domain_terms"))
            rec["output"] = [[x.name, x.type] for x in out]
        else:
            out = ext.extract(c["text"], known_entities=c["known_entities"], domain_terms=c.get("domain_terms"),
                              resolve_references=c.get("resolve_references", False),
                              entity_types=c.get("entity_types"))
            rec["output"] = [[x.subject, x.relation_type, x.object] for x in out]
    except Exception as e:
        rec["raises"] = type(e).__name__
        rec["message"] = str(e)
    rec["calls"] = svc.calls
    return rec


cases = [run(c) for c in C]
json.dump({"cases": cases}, open(os.path.join(OUT, "extraction_llm_cases.json"), "w"), default=str)
ents = [c for c in cases if c["kind"] == "entity"]
rels = [c for c in cases if c["kind"] == "relation"]
print("entity cases:", len(ents), "| relation cases:", len(rels), "| written to", OUT)
print("python error types:", sorted({c.get("raises") or c.get("ctor_raises") for c in cases
                                     if c.get("raises") or c.get("ctor_raises")}))
