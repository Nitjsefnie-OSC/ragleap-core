# Generates upsert recordings with extraction by running the real Python _upsert_document_once (real
# LLMEntityExtractor / LLMRelationExtractor / EntityDeduplicator) against a fake driver that records every Cypher
# statement and a fake GenerationService that records every model call and returns scripted answers. Writes
# upsert_extraction_cases.json into RAGLEAP_GRAPH_PARITY_DIR (default /tmp/fixtures-graph-a).
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

LOG = []
CURRENT = {"script": {}}


def sv(key, items):
    return {"provider_used": "fake", "answer": json.dumps({key: items}), "structured": {key: items},
            "structured_valid": True, "structured_enforcement": "native"}


def fb(answer):
    return {"provider_used": "fake", "answer": answer, "structured": None, "structured_valid": False,
            "structured_enforcement": "json_object"}


NO_PROVIDER = {"provider_used": None, "answer": "all providers failed", "structured": None, "structured_valid": False}


def EN(*items):
    return sv("entities", [{"name": n, "type": t} for n, t in items])


def RL(*items):
    return sv("relations", [{"subject": s, "relation_type": t, "object": o} for s, t, o in items])


class FakeProvider:
    pass


class FakeGen:
    def __init__(self, primary=None, default_temperature=None, system_prompt=None, **kw):
        self.system_prompt = system_prompt

    def generate_answer(self, query, chunks, response_format=None, temperature=None, **kw):
        kind = "entity" if response_format is ex._ENTITY_JSON_SCHEMA else "relation"
        text = chunks[0]["text"]
        LOG.append({"kind": kind, "query": query, "text": text, "document_name": chunks[0]["document_name"],
                    "temperature": temperature, "system_prompt": self.system_prompt})
        table = CURRENT["script"].get(kind, {})
        if text in table:
            return table[text]
        return sv("entities", []) if kind == "entity" else sv("relations", [])


ex.ProviderConfig = FakeProvider
ex.GenerationService = FakeGen


class FakeSession:
    def __init__(self, drv):
        self.drv = drv

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.drv.calls.append({"cypher": "".join(query.split()), "params": params})
        if "RETURN pw.entity_a AS a" in query:
            return [{"a": a, "b": b} for a, b in self.drv.old_pairs]
        if "RETURN rw.subject AS subject" in query:
            return [{"subject": s, "relation_type": t, "object": o} for s, t, o in self.drv.old_relations]
        return []


class FakeDriver:
    def __init__(self, old_pairs, old_relations):
        self.calls = []
        self.old_pairs = [tuple(x) for x in old_pairs]
        self.old_relations = [tuple(x) for x in old_relations]

    def session(self):
        return FakeSession(self)

    def close(self):
        pass


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


def U(name, chunks, entity=None, relation=None, config=None, **kw):
    d = dict(name=name, document_id="doc-" + name, title="T", chunks=chunks, namespace=None, user_id=None,
             max_entities=80, max_pairs=150, domain_terms=None, old_pairs=[], old_relations=[],
             config=config or {}, script={"entity": entity or {}, "relation": relation or {}})
    d.update(kw)
    return d


def CH(*texts):
    return [{"text": t} for t in texts]


A1 = "Alice works at Acme."
A2 = "Acme hired Bob."
A3 = "Bob thanked Alice."
REL = {"extract_relations": True}
RELX = {"extract_relations": True, "cross_chunk_relations": True}
TYP = {"entity_types": ["PERSON", "ORG"]}
many = [("Entity%02d" % i, "T") for i in range(15)]
ONT = {"WORKS_AT": [["PERSON"], ["ORG"]]}

S = [
    U("llm_basic", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")),
                                       A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))}),
    U("llm_types_first_wins", CH(A1, A2), entity={A1: EN(("Acme", "ORG"), ("Alice", "PERSON")),
                                                 A2: EN(("Acme", "COMPANY"), ("Bob", "PERSON"))}),
    U("llm_case_variants_across_chunks", CH(A1, A2), entity={A1: EN(("Acme", "UNKNOWN"), ("Alice", "PERSON")),
                                                            A2: EN(("ACME", "ORG"), ("Bob", "PERSON"))}),
    U("llm_cap_12", CH(A1), entity={A1: EN(*many)}),
    U("llm_extractor_cap_5", CH(A1), entity={A1: EN(*many[:8])}, config={"max_entities_per_chunk": 5}),
    U("llm_empty_skips_chunk", CH(A1, A2), entity={A1: EN(), A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A2: RL(("Acme", "WORKS_WITH", "Bob"))}, config=REL),
    U("llm_blank_chunks", [{"text": ""}, {"text": "   "}, {"nottext": "x"}, {"text": None}, {"text": A1}],
      entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))}),
    U("llm_strip_text", [{"text": "  Alice works at Acme.  \n"}], entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))}),
    U("llm_domain_terms", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme"))}, config=REL, domain_terms=["Widget", "Gizmo"]),
    U("llm_entity_types", CH(A1), entity={A1: EN(("Alice", "Person"), ("Acme", "ORG"), ("Bob", "PERSON"))}, config=TYP),
    U("llm_max_entities_cut", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")),
                                                  A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))}, max_entities=2),
    U("llm_namespace_user", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))}, namespace="ns", user_id="u1"),
    U("rel_basic", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme"), ("Bob", "works at", "Acme"))}, config=REL),
    U("rel_counts_across_chunks", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")),
                                                      A2: EN(("Acme", "ORG"), ("Bob", "PERSON"), ("Alice", "PERSON"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme"), ("Alice", "WORKS_AT", "Nobody")),
                A2: RL(("Alice", "WORKS_AT", "Acme"), ("Bob", "WORKS_AT", "Acme"))}, config=REL),
    U("rel_model_casing_kept", CH(A1, A2), entity={A1: EN(("Acme", "ORG"), ("Alice", "PERSON")),
                                                   A2: EN(("Acme", "ORG"), ("Alice", "PERSON"))},
      relation={A1: RL(("Acme", "X", "Alice")), A2: RL(("acme", "X", "ALICE"))}, config=REL),
    U("rel_cross_chunk", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")),
                                             A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme")), A2: RL(("Acme", "HIRED", "Bob")),
                A1 + "\n\n" + A2: RL(("Alice", "KNOWS", "Bob"))}, config=RELX),
    U("rel_cross_chunk_same_relation", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")),
                                                           A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme")), A1 + "\n\n" + A2: RL(("Alice", "WORKS_AT", "Acme"))}, config=RELX),
    U("rel_cross_chunk_one_entity", CH(A1), entity={A1: EN(("Acme", "ORG"))}, config=RELX),
    U("rel_cross_chunk_blank_between", ["" and {"text": ""} or {"text": A1}, {"text": ""}, {"text": A2}, {"text": "  "}],
      entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")), A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A1 + "\n\n" + A2: RL(("Alice", "KNOWS", "Bob"))}, config=RELX, domain_terms=["Widget"]),
    U("rel_cross_chunk_case_variants", CH(A1, A2), entity={A1: EN(("Acme", "ORG")), A2: EN(("ACME", "ORG"), ("Bob", "PERSON"))},
      relation={A1 + "\n\n" + A2: RL(("Acme", "HIRED", "Bob"))}, config=RELX),
    U("rel_ontology", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"), ("Bob", "PERSON"), ("Carol", "Other"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme"), ("Acme", "WORKS_AT", "Alice"), ("Acme", "REPORTED", "Alice"),
                       ("Bob", "WORKS_AT", "Carol"), ("Bob", "works_at", "Acme"))},
      config={"extract_relations": True, "entity_types": ["PERSON", "ORG"], "relation_ontology": ONT}),
    U("rel_max_pairs_cut", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"), ("Bob", "PERSON")),
                                               A2: EN(("Alice", "PERSON"), ("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A1: RL(("Alice", "X", "Acme"), ("Alice", "Y", "Acme")),
                A2: RL(("Alice", "Y", "Acme"), ("Bob", "Z", "Acme"))}, config=REL, max_pairs=2),
    U("rel_old_relations", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme"))}, config=REL,
      old_relations=[["alice", "WORKS_AT", "acme"], ["x", "Y", "z"]]),
    U("rel_namespace_user", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))},
      relation={A1: RL(("Alice", "WORKS_AT", "Acme"))}, config=REL, namespace="ns", user_id="u1"),
    U("dedup_llm_basic", CH(A1, A2), entity={A1: EN(("Acme Corp", "ORG"), ("Globex", "ORG")),
                                            A2: EN(("ACME Corp.", "ORG"), ("Globex", "ORG"), ("Initech", "ORG"))},
      config={"dedup_enabled": True}),
    U("dedup_self_pair_dropped", CH(A1), entity={A1: EN(("Acme Corp", "ORG"), ("ACME Corp.", "ORG"), ("Globex", "ORG"))},
      config={"dedup_enabled": True}),
    U("dedup_relations", CH(A1, A2, A3),
      entity={A1: EN(("Acme Corp", "ORG"), ("Globex", "ORG")), A2: EN(("ACME Corp.", "ORG"), ("Globex", "ORG")),
              A3: EN(("Acme Corp", "ORG"), ("ACME Corp.", "ORG"))},
      relation={A1: RL(("Acme Corp", "PARTNERED_WITH", "Globex")), A2: RL(("ACME Corp.", "PARTNERED_WITH", "Globex")),
                A3: RL(("Acme Corp", "ALIAS_OF", "ACME Corp."))},
      config={"extract_relations": True, "dedup_enabled": True}),
    U("dedup_relation_key_not_mapped", CH(A1, A2),
      entity={A1: EN(("Acme Corp", "ORG"), ("Globex", "ORG")), A2: EN(("ACME Corp.", "ORG"), ("Globex", "ORG"))},
      relation={A1: RL(("acme corp", "PARTNERED_WITH", "Globex"))},
      config={"extract_relations": True, "dedup_enabled": True}),
    U("dedup_threshold_low", CH(A1, A2), entity={A1: EN(("Acme Corp", "ORG"), ("Acme Inc", "ORG"), ("Globex Corp", "ORG")),
                                                A2: EN(("Globex Inc", "ORG"), ("Initech", "ORG"))},
      config={"dedup_enabled": True, "dedup_threshold": 0.5}),
    U("dedup_no_entities", CH(A1, A2), config={"dedup_enabled": True}),
    U("dedup_old_pairs", CH(A1, A2), entity={A1: EN(("Acme Corp", "ORG"), ("Globex", "ORG")),
                                            A2: EN(("ACME Corp.", "ORG"), ("Globex", "ORG"))},
      config={"dedup_enabled": True}, old_pairs=[["acme corp", "globex"]]),
    U("dedup_regex", CH("Acme Corp announced a partnership with Globex Industries.",
                        "ACME Corp. signed a deal with Globex Industries and Initech Systems."),
      config={"method": "regex", "dedup_enabled": True, "dedup_threshold": 0.8}),
    U("dedup_regex_default_threshold", CH("Acme Corporation met Globex Industries.", "Acme Corp met Globex Industries."),
      config={"method": "regex", "dedup_enabled": True}),
    U("fail_entity_provider", CH(A1), entity={A1: NO_PROVIDER}),
    U("fail_entity_malformed", CH(A1), entity={A1: fb("garbage")}),
    U("fail_entity_bad_item", CH(A1), entity={A1: sv("entities", ["x"])}),
    U("fail_relation_provider", CH(A1), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG"))},
      relation={A1: NO_PROVIDER}, config=REL),
    U("fail_second_chunk", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")), A2: NO_PROVIDER}),
    U("fail_cross_chunk", CH(A1, A2), entity={A1: EN(("Alice", "PERSON"), ("Acme", "ORG")),
                                              A2: EN(("Acme", "ORG"), ("Bob", "PERSON"))},
      relation={A1 + "\n\n" + A2: fb("not json")}, config=RELX),
]


def run(sc):
    CURRENT["script"] = sc["script"]
    LOG.clear()
    cfg = make_cfg(sc["config"])
    g = rg.GraphIndex(config=rg.GraphConfig(uri="bolt://localhost:1", user="x", password="x"), extraction=cfg)
    drv = FakeDriver(sc["old_pairs"], sc["old_relations"])
    g.driver = drv
    rec = {k: sc[k] for k in ("name", "config", "script", "old_pairs", "old_relations")}
    rec["args"] = {k: sc[k] for k in ("document_id", "title", "chunks", "namespace", "user_id", "max_entities",
                                      "max_pairs", "domain_terms")}
    try:
        rec["summary"] = g._upsert_document_once(
            document_id=sc["document_id"], title=sc["title"], chunks=sc["chunks"], namespace=sc["namespace"],
            user_id=sc["user_id"], max_entities=sc["max_entities"], max_pairs=sc["max_pairs"],
            domain_terms=sc["domain_terms"])
    except Exception as e:
        rec["raises"] = type(e).__name__
        rec["message"] = str(e)
    rec["calls"] = drv.calls
    rec["llm_calls"] = list(LOG)
    return rec


out = [run(sc) for sc in S]
json.dump(out, open(os.path.join(OUT, "upsert_extraction_cases.json"), "w"), default=str)
print("scenarios:", len(out), "| written to", OUT)
print("python errors:", sorted({(o["name"], o["raises"]) for o in out if "raises" in o}))
print("summaries:", [(o["name"], o["summary"]["entities_indexed"], o["summary"]["relationships_indexed"],
                      o["summary"]["relations_indexed"]) for o in out if "summary" in o][:40])
