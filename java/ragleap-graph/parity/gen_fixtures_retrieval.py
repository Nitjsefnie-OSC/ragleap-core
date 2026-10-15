# Generates parity recordings for GraphRetriever and GraphRetrievalConfig by running the real Python classes against
# fake graph and rag objects that append every call to ONE ordered event log. Writes retrieval_cases.json into
# RAGLEAP_GRAPH_PARITY_DIR (default /tmp/fixtures-graph-a).
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, logging, os, sys
logging.disable(logging.CRITICAL)
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
assert rg.__file__.startswith(SRC), "wrong module path"
from ragleap_graph.retrieval import GraphRetriever, GraphRetrievalConfig
OUT = os.environ.get("RAGLEAP_GRAPH_PARITY_DIR", "/tmp/fixtures-graph-a")
os.makedirs(OUT, exist_ok=True)


class FakeGraph:
    def __init__(self, sc, log):
        self.sc = sc
        self.log = log

    def extract_query_entities(self, query, max_entities=10, domain_terms=None):
        self.log.append(["extract", query, max_entities, domain_terms])
        return self.sc["query_entities"]

    def find_documents_by_entities(self, entity_names, namespace=None, limit=25):
        self.log.append(["find_docs", list(entity_names), namespace, limit])
        return [dict(d) for d in self.sc["docs"]]

    def search_related_entities(self, entity_names, namespace=None, max_depth=2, limit=10):
        self.log.append(["search_related", list(entity_names), namespace, max_depth, limit])
        return [dict(e) for e in self.sc["related"]]


class FakeRag:
    def __init__(self, sc, log):
        self.sc = sc
        self.log = log

    def retrieve(self, query, **kwargs):
        self.log.append(["rag", query, kwargs.get("top_k"), kwargs.get("metadata_filter"), sorted(kwargs)])
        return [dict(c) for c in self.sc["chunks"]]


def D(i, name, n=1, score=1.0, names=None):
    return {"document_id": i, "document_name": name, "matched_entities": n, "graph_score": score,
            "matched_entity_names": names if names is not None else ["Acme Corp"]}


def E(i, name, rel="CO_OCCURS_WITH", depth=1):
    return {"entity_id": i, "entity_name": name, "relationship": rel, "depth": depth}


def CK(cid, doc, name, text, idx=0):
    return {"chunk_id": cid, "text": text, "document_id": doc, "document_name": name, "chunk_index": idx}


def SC(name, **kw):
    d = dict(name=name, query="What products has Acme Corp launched?", call={}, config={},
             query_entities=["Acme Corp"], docs=[D("d3", "acme_contract.pdf", 1, 2.5)],
             related=[E("neo4j", "Neo4j")],
             chunks=[CK("c1", "d1", "q3_report.pdf", "Acme Corp reported strong Q3 revenue growth."),
                     CK("c2", "d2", "press_release.pdf", "The new product line launched in partnership with Neo4j.")],
             rag_none=False)
    d.update(kw)
    return d


S = [
    SC("hybrid_basic"),
    SC("call_top_k_filter", call={"top_k": 3, "metadata_filter": {"tenant": "acme", "tags": ["a", "b"], "n": 1}}),
    SC("call_namespace", call={"namespace": "acme-tenant"}),
    SC("call_all_args_unicode", query="\U0001F600 What about \u00c9cole?",
       call={"top_k": 1, "namespace": "ns-\u00e9", "metadata_filter": {"k\u00e9": "v\U0001F600"}}),
    SC("config_passthrough", config={"graph_expand_depth": 5, "max_graph_results": 3, "max_query_entities": 4,
                                     "domain_terms": ["ALARA", "dose limits"]}),
    SC("config_graph_only_passthrough", config={"mode": "graph_only", "graph_expand_depth": 7, "max_graph_results": 2}),
    SC("no_entities_hybrid", query_entities=[]),
    SC("no_entities_graph_only", query_entities=[], config={"mode": "graph_only"}),
    SC("graph_only_basic", config={"mode": "graph_only"}),
    SC("graph_only_rag_none", config={"mode": "graph_only"}, rag_none=True),
    SC("hybrid_rag_none", rag_none=True),
    SC("hybrid_rag_none_no_entities", rag_none=True, query_entities=[]),
    SC("empty_everything", docs=[], related=[], chunks=[]),
    SC("overlap_flags", chunks=[CK("c1", "d1", "a.pdf", "Acme Corp news.")],
       docs=[D("d1", "a.pdf"), D("d9", "b.pdf", 1, 1.0, ["Globex Corp"])]),
    SC("overlap_missing_and_null_ids",
       chunks=[{"chunk_id": "c1", "text": "x", "document_name": "n"},
               {"chunk_id": "c2", "text": "y", "document_id": None, "document_name": "n"}],
       docs=[D(None, "a.pdf"), D("d1", "b.pdf")]),
    SC("overlap_type_mismatch", chunks=[CK("c1", 1, "a.pdf", "t"), CK("c2", "d2", "b.pdf", "t")],
       docs=[D("1", "a.pdf"), D("d2", "b.pdf")]),
    SC("preview_lengths", chunks=[CK("c%d" % n, "d%d" % n, "n.pdf", "x" * n) for n in (0, 1, 149, 150, 151, 300)]),
    SC("preview_emoji_boundary", chunks=[CK("c1", "d1", "n.pdf", "a" * 149 + "\U0001F600" + "b"),
                                         CK("c2", "d2", "n.pdf", "a" * 148 + "\U0001F600\U0001F600"),
                                         CK("c3", "d3", "n.pdf", "\U0001F600" * 151)]),
    SC("preview_unicode_text", chunks=[CK("c1", "d1", "n.pdf", "\u00c9cole \u4e2d\u6587 " * 40)]),
    SC("chunk_keys_missing", chunks=[{"text": "only text"}, {},
                                     {"chunk_id": "c3", "text": "t", "document_name": None, "document_id": None}]),
    SC("chunk_text_none", chunks=[CK("c1", "d1", "n.pdf", "ok"),
                                  {"chunk_id": "c2", "text": None, "document_id": "d2", "document_name": "n"}]),
    SC("chunk_text_int", chunks=[{"chunk_id": "c1", "text": 5, "document_id": "d1", "document_name": "n"}]),
    SC("chunk_extra_keys_passthrough",
       chunks=[{"chunk_id": "c1", "text": "t", "similarity_score": 0.5, "document_id": "d1", "document_name": "n",
                "chunk_index": 3, "retrieval_method": "hybrid_rrf", "extra": {"nested": [1, 2.5, None, True]}}]),
    SC("graph_path_values", related=[E("e1", None, None, 3), E(None, "Name", "REL", 0),
                                     E("e3", "\u00c9cole", "CO_OCCURS_WITH", 10)]),
    SC("citation_order", chunks=[CK("c1", "d1", "a.pdf", "one"), CK("c2", "d2", "b.pdf", "two"),
                                 CK("c3", "d3", "c.pdf", "three")],
       related=[E("n1", "N1"), E("n2", "N2", "CONTAINS", 2)]),
    SC("duplicate_query_entities", query_entities=["Acme", "acme", "Acme"]),
    SC("many_docs", docs=[D("d%d" % i, "n%d.pdf" % i, i, float(i) + 0.5, ["E%d" % i, "F"]) for i in range(1, 6)],
       chunks=[CK("c1", "d3", "n3.pdf", "t")]),
    SC("graph_only_ignores_scripted_chunks", config={"mode": "graph_only"}, chunks=[CK("c1", "d1", "a.pdf", "t")],
       docs=[D("d1", "a.pdf")]),
]


def run_retrieve(sc):
    log = []
    cfg = GraphRetrievalConfig(**sc["config"])
    graph = FakeGraph(sc, log)
    rag = None if sc["rag_none"] else FakeRag(sc, log)
    retriever = GraphRetriever(graph=graph, rag=rag, config=cfg)
    rec = {k: sc[k] for k in ("name", "query", "call", "config", "query_entities", "docs", "related", "chunks",
                              "rag_none")}
    try:
        rec["result"] = retriever.retrieve(sc["query"], **sc["call"])
    except Exception as e:
        rec["raises"] = type(e).__name__
        rec["message"] = str(e)
    rec["events"] = log
    return rec


def CC(name, **kw):
    rec = {"name": name, "kwargs": kw}
    try:
        c = GraphRetrievalConfig(**kw)
        rec["ok"] = True
        rec["fields"] = {"mode": c.mode, "graph_expand_depth": c.graph_expand_depth,
                         "max_graph_results": c.max_graph_results, "domain_terms": c.domain_terms,
                         "max_query_entities": c.max_query_entities}
    except Exception as e:
        rec["ok"] = False
        rec["error_type"] = type(e).__name__
        rec["message"] = str(e)
    return rec


CFG = [
    CC("defaults"), CC("hybrid_explicit", mode="hybrid"), CC("graph_only", mode="graph_only"),
    CC("custom", mode="graph_only", graph_expand_depth=4, max_graph_results=7, domain_terms=["a", "b"],
       max_query_entities=3),
    CC("depth_eleven_is_valid", graph_expand_depth=11),
    CC("bad_mode_bogus", mode="bogus"), CC("bad_mode_empty", mode=""), CC("bad_mode_case", mode="Hybrid"),
    CC("bad_mode_quote", mode="it's"), CC("bad_mode_both_quotes", mode="a'b\"c"), CC("bad_mode_none", mode=None),
    CC("bad_mode_unicode", mode="h\u00e9\U0001F600"),
    CC("depth_zero", graph_expand_depth=0), CC("depth_negative", graph_expand_depth=-4),
    CC("max_results_zero", max_graph_results=0), CC("max_results_negative", max_graph_results=-1),
    CC("max_entities_zero", max_query_entities=0), CC("max_entities_negative", max_query_entities=-9),
    CC("order_mode_before_depth", mode="x", graph_expand_depth=0),
    CC("order_depth_before_results", graph_expand_depth=0, max_graph_results=0),
    CC("order_results_before_entities", max_graph_results=0, max_query_entities=0),
]

retrieve = [run_retrieve(sc) for sc in S]
json.dump({"config": CFG, "retrieve": retrieve}, open(os.path.join(OUT, "retrieval_cases.json"), "w"), default=str)
print("retrieve scenarios:", len(retrieve), "| config cases:", len(CFG), "| written to", OUT)
print("python errors:", sorted({(r["name"], r["raises"]) for r in retrieve if "raises" in r}))
print("config errors:", sorted({c["error_type"] for c in CFG if not c["ok"]}))
