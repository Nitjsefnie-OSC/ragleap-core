# Generates parity recordings for RagLeap.ask, ask_stream, retrieve and evaluate by running the real Python class
# (built without its __init__) over fake collaborators. Every collaborator call, hook event and memory write goes
# into one ordered log per scenario; the results are recorded too.
# Pinned commit: d210dab8155055a913488e85407eb45b6379dc44 (packages/ragleap-rag, version 0.13.0).
# Export first: git archive d210dab8155055a913488e85407eb45b6379dc44 packages/ragleap-rag | tar -x -C /tmp/py-rag-pinned
import copy, json, os, sys, types
import unittest.mock as um

SRC = "/tmp/py-rag-pinned/packages/ragleap-rag/src"
sys.path.insert(0, SRC)
if os.path.isdir("/tmp/pycheck"):
    sys.path.append("/tmp/pycheck")


class _Stub(types.ModuleType):
    __path__ = []

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return um.MagicMock(name=self.__name__ + "." + item)


def _stub(name):
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        n = ".".join(parts[:i])
        if n not in sys.modules:
            sys.modules[n] = _Stub(n)


stubbed = []
for _ in range(60):
    try:
        import ragleap as rl
        break
    except ModuleNotFoundError as e:
        if not e.name or e.name == "ragleap" or e.name.startswith("ragleap."):
            raise
        stubbed.append(e.name)
        _stub(e.name)
else:
    raise SystemExit("too many missing modules: " + str(stubbed))
print("module:", rl.__file__, "| stubbed modules:", stubbed)
assert rl.__file__.startswith(SRC), "wrong module path"
from ragleap.guardrails import GuardrailViolation

FALLBACK = types.SimpleNamespace(provider="fallback-provider")
MARKERS = [("contextual", "standalone question"), ("hyde", "plausible passage"), ("multi", "different phrasings")]
Q = "What is the price?"


class FakeEmbedder:
    model = "model-1"

    def __init__(self, fail, log):
        self.fail = set(fail)
        self.log = log

    def embed_text(self, text):
        self.log.append({"c": "embed", "text": text})
        if text in self.fail:
            return None
        return [float(len(text)), 1.0]


class FakeBackend:
    def __init__(self, results, log):
        self.results = results
        self.log = log

    def _pick(self, key):
        return [dict(c) for c in self.results.get(key, self.results.get("default", []))]

    def search_hybrid(self, query, embedding, top_k=5, metadata_filter=None):
        self.log.append({"c": "hybrid", "q": query, "emb": embedding, "top_k": top_k, "filter": metadata_filter})
        return self._pick(query)

    def search_dense(self, embedding, top_k=5, metadata_filter=None):
        self.log.append({"c": "dense", "emb": embedding, "top_k": top_k, "filter": metadata_filter})
        return self._pick("len%d" % int(embedding[0]))


class FakeMemory:
    def __init__(self, history, log):
        self.history = history
        self.log = log

    def build_history_prompt(self, session_id):
        self.log.append({"c": "mem_build", "session": session_id})
        return self.history

    def add_message(self, session_id, role, content):
        self.log.append({"c": "mem_add", "session": session_id, "role": role, "content": content})


class FakeGenerator:
    def __init__(self, script, pieces, log):
        self.script = script
        self.pieces = pieces
        self.log = log

    @staticmethod
    def _pick(system_prompt, query):
        for key, marker in MARKERS:
            if marker in (system_prompt or "") or marker in (query or ""):
                return key
        return "answer"

    @staticmethod
    def _entry(kind, query, chunks, kw):
        t = kw.get("temperature")
        return {"c": kind, "query": query, "chunk_ids": [c["chunk_id"] for c in chunks],
                "temperature": None if t is None else float(t), "system_prompt": kw.get("system_prompt"),
                "max_tokens": kw.get("max_tokens"), "history_prefix": kw.get("history_prefix") or "",
                "override": "fallback" if kw.get("override_provider") is FALLBACK else None,
                "response_format": kw.get("response_format")}

    def generate_answer(self, query, chunks, **kw):
        self.log.append(self._entry("gen", query, chunks, kw))
        return copy.deepcopy(self.script[self._pick(kw.get("system_prompt"), query)])

    def generate_answer_stream(self, query, chunks, **kw):
        e = self._entry("stream", query, chunks, kw)
        e.pop("response_format")
        self.log.append(e)
        for piece in self.pieces:
            yield piece


def _replace_foo(t):
    return t.replace("foo", "bar")


def _block_forbidden(t):
    if "forbidden" in t:
        raise GuardrailViolation("contains forbidden text")
    return t


GUARDS = {"replace_foo": _replace_foo, "block_forbidden": _block_forbidden}


def chunk(i, method="dense"):
    return {"chunk_id": "c%d" % i, "text": "chunk text %d" % i, "similarity_score": 0.9 - i / 100.0,
            "document_id": "d%d" % i, "document_name": "doc.txt", "chunk_index": i, "retrieval_method": method}


def gens(provider="prov", model="model-x", answer="The answer is 42 per the doc.", chunks_sent=2, extra=None):
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    cit = [{"source_number": 1, "document_name": "doc.txt", "document_id": "d1", "chunk_id": "c1",
            "chunk_index": 1, "text_preview": "the answer is 42 per the doc"}]

    def one(text, sources, cits, sent):
        d = {"answer": text, "sources": sources, "citations": cits, "provider_used": provider,
             "model_used": model, "usage": dict(usage), "chunks_sent": sent}
        return d

    script = {
        "answer": one(answer, ["doc.txt"], cit, chunks_sent),
        "contextual": one("What is the pricing of Acme Corp?", [], [], 0),
        "hyde": one("Acme Corp offers three pricing tiers, starting at ten dollars a month.", [], [], 0),
        "multi": one("How much does Acme charge?\nWhat are Acme's prices?\nAcme pricing details\nA fourth variant", [], [], 0),
    }
    if extra:
        script["answer"].update(extra)
    return script


MQ = {"default": [chunk(1), chunk(2), chunk(3)],
      "How much does Acme charge?": [chunk(1), chunk(2)],
      "What are Acme's prices?": [chunk(2), chunk(3)],
      "Acme pricing details": [chunk(3), chunk(4)],
      Q: [chunk(5)]}
EVAL_CASES = [
    {"query": Q, "expected_document": "doc.txt", "expected_keywords": ["42", "answer"]},
    {"query": "Another question", "expected_document": "other.txt", "expected_keywords": ["missing", "answer"]},
    {"query": "No expectations"},
]
DEF = {
    "ask": dict(query=Q, top_k=5, temperature=None, system_prompt=None, max_tokens=None, hybrid=True,
                session_id=None, metadata_filter=None, response_format=None, query_rewrite=None, multi_query_n=3),
    "ask_stream": dict(query=Q, top_k=5, temperature=None, system_prompt=None, max_tokens=None, hybrid=True,
                       session_id=None, metadata_filter=None),
    "retrieve": dict(query=Q, top_k=5, hybrid=True, metadata_filter=None),
    "evaluate": dict(test_cases=[]),
}
BASE = dict(history="", budget=None, fallback=False, cache=False, output_guardrails=[], embed_fail=[],
            results={"default": [chunk(1), chunk(2)]}, gen=None, stream_pieces=["The ", "answer."], repeat=1,
            priced=False)
SCEN = []


def add(name, method, args=None, **st):
    a = dict(DEF[method])
    a.update(args or {})
    s = copy.deepcopy(BASE)
    s.update(st)
    SCEN.append({"name": name, "method": method, "args": a, "settings": s})


add("ask_basic", "ask")
add("ask_dense_filter", "ask", dict(hybrid=False, top_k=3, metadata_filter={"team": "sales"}))
add("ask_params", "ask", dict(temperature=0.2, max_tokens=256, system_prompt="Answer briefly."))
add("ask_session", "ask", dict(session_id="s1"), history="User: hi\nAssistant: hello")
add("ask_empty_session", "ask", dict(session_id=""), history="should not be used")
add("ask_embed_failure", "ask", dict(session_id="s1"), embed_fail=[Q])
add("ask_no_results", "ask", results={"default": []}, gen=gens(chunks_sent=0))
add("ask_contextual", "ask", dict(session_id="s1", query_rewrite="contextual"),
    history="User: tell me about Acme\nAssistant: Acme is a company.")
add("ask_contextual_no_history", "ask", dict(session_id="s1", query_rewrite="contextual"), history="")
add("ask_hyde", "ask", dict(query_rewrite="hyde"))
add("ask_multi_query", "ask", dict(query_rewrite="multi_query"), results=MQ)
add("ask_multi_query_dense", "ask", dict(query_rewrite="multi_query", hybrid=False, top_k=2), results=MQ)
add("ask_multi_query_variant_embed_fail", "ask", dict(query_rewrite="multi_query", multi_query_n=2), results=MQ,
    embed_fail=["What are Acme's prices?"])
add("ask_over_budget", "ask", dict(query_rewrite="hyde"), budget=0.0, fallback=True)
add("ask_budget_not_reached", "ask", budget=1000000.0, fallback=True)
add("ask_priced", "ask", repeat=2, priced=True, budget=0.000001, fallback=True)
add("ask_guard_transform", "ask", output_guardrails=["replace_foo"], gen=gens(answer="foo is the answer"))
add("ask_guard_blocked", "ask", output_guardrails=["replace_foo", "block_forbidden"],
    gen=gens(answer="this is forbidden stuff"))
add("ask_response_format", "ask",
    dict(response_format={"type": "object", "properties": {"price": {"type": "number"}}}),
    gen=gens(extra={"structured": {"price": 9.5}, "structured_valid": True, "structured_enforcement": "native"}))
add("ask_cache_repeat", "ask", cache=True, repeat=2)
add("stream_basic", "ask_stream")
add("stream_session_dense", "ask_stream", dict(session_id="s1", hybrid=False, top_k=2),
    history="User: hi\nAssistant: hello")
add("stream_embed_failure", "ask_stream", embed_fail=[Q])
add("stream_guard_blocked", "ask_stream", output_guardrails=["block_forbidden"], stream_pieces=["this is ", "forbidden"])
add("stream_over_budget", "ask_stream", budget=0.0, fallback=True)
add("stream_unicode", "ask_stream", stream_pieces=["Hello ", "\U0001F600 world"])
add("stream_params", "ask_stream", dict(temperature=0.5, max_tokens=64, system_prompt="Be terse.",
                                       metadata_filter={"a": 1}))
add("retrieve_hybrid", "retrieve")
add("retrieve_dense_filter", "retrieve", dict(hybrid=False, top_k=3, metadata_filter={"team": "x"}))
add("retrieve_embed_failure", "retrieve", embed_fail=[Q])
add("retrieve_cache", "retrieve", cache=True, repeat=2)
add("evaluate_basic", "evaluate", dict(test_cases=EVAL_CASES))
add("evaluate_empty", "evaluate", dict(test_cases=[]))


def build(st, log):
    rag = rl.RagLeap.__new__(rl.RagLeap)
    rag.database_url = "postgresql://unused"
    rag.embedding_dimensions = 2
    rag._vector_backend = FakeBackend(st["results"], log)
    rag._embedder = FakeEmbedder(st["embed_fail"], log)
    rag._memory = FakeMemory(st["history"], log)
    rag._generator = FakeGenerator(st["gen"], st["stream_pieces"], log)
    rag._cost_tracker = rl.CostTracker(budget_usd_per_month=st["budget"])
    rag._budget_fallback = FALLBACK if st["fallback"] else None
    rag._output_guardrails = [GUARDS[n] for n in st["output_guardrails"]] or None
    rag._input_guardrails = None
    rag._on_ingest = None
    rag._on_query = [lambda ev: log.append({"c": "hook", "name": "on_query", "event": copy.deepcopy(ev)})]
    rag._on_answer = [lambda ev: log.append({"c": "hook", "name": "on_answer", "event": copy.deepcopy(ev)})]
    rag._cache_enabled = st["cache"]
    rag._query_cache = rl.QueryEmbeddingCache(max_size=100) if st["cache"] else None
    rag._reranker = None
    rag._chunker = None
    return rag


table = getattr(rl.cost, "SEED_PRICING_TABLE", None)
out, skipped = [], []
for sc in SCEN:
    st = sc["settings"]
    if st["priced"]:
        if not table:
            skipped.append(sc["name"])
            continue
        prov = next(iter(table))
        model = next(iter(table[prov]))
        st["gen"] = gens(provider=prov, model=model)
        st["priced_pair"] = [prov, model]
    elif st["gen"] is None:
        st["gen"] = gens()
    log, results, raised = [], [], None
    rag = build(st, log)
    try:
        for _ in range(st["repeat"]):
            if sc["method"] == "ask":
                results.append(rag.ask(**sc["args"]))
            elif sc["method"] == "ask_stream":
                results.append(list(rag.ask_stream(**sc["args"])))
            elif sc["method"] == "retrieve":
                results.append(rag.retrieve(**sc["args"]))
            else:
                results.append(rag.evaluate(**sc["args"]))
    except ValueError as e:
        raised = str(e)
    out.append({"name": sc["name"], "method": sc["method"], "args": sc["args"], "settings": st,
                "expected": {"results": results, "raises": raised}, "log": log})
os.makedirs("/tmp/fixtures-facade", exist_ok=True)
with open("/tmp/fixtures-facade/facade_cases.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=True, indent=1)
print("scenarios:", len(out), "| raises:", [o["name"] for o in out if o["expected"]["raises"]],
      "| skipped:", skipped)
