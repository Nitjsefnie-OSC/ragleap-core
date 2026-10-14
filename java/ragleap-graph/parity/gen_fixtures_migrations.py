# Generates parity recordings for the graph backfills and the migration framework by running the real Python code
# against fake drivers/sessions that record every Cypher statement and parameter. Writes backfill_cases.json and
# migrations_cases.json into RAGLEAP_GRAPH_PARITY_DIR (default /tmp/fixtures-graph-a).
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, logging, os, sys
logging.disable(logging.CRITICAL)
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
assert rg.__file__.startswith(SRC), "wrong module path"
from ragleap_graph.migrations import Migration, MigrationRunner, ALL_MIGRATIONS
runner_mod = sys.modules["ragleap_graph.migrations.runner"]
OUT = os.environ.get("RAGLEAP_GRAPH_PARITY_DIR", "/tmp/fixtures-graph-a")
os.makedirs(OUT, exist_ok=True)


class Res:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
    def __iter__(self):
        return iter(self.rows)
    def single(self):
        return self.rows[0] if self.rows else None


def label_of(query):
    if "CO_OCCURS_WITH" in query:
        return "co"
    for label in ("RelationWeight", "PairWeight", "Document", "Entity"):
        if "(n:%s)" % label in query:
            return label
    return None


class Session:
    def __init__(self, scenario):
        self.s = scenario
        self.calls = []
        self.applied = set(scenario.get("applied_ids", []))
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def run(self, query, **params):
        self.calls.append({"cypher": "".join(query.split()), "params": params})
        rows = self.s.get("rows", {})
        if "RETURN count(m) > 0 AS applied" in query:
            return Res([{"applied": params["id"] in self.applied}])
        if "CREATE (m:_Migration" in query:
            self.applied.add(params["id"])
            return Res([])
        if "RETURN m.applied_at AS applied_at" in query:
            row = self.s.get("status_row", {"applied_at": "2026-01-01T00:00:00Z", "elapsed_ms": 42})
            return Res([row] if row is not None else [])
        if "UNWIND" in query:
            return Res([])
        label = label_of(query)
        if "user_id IS NULL" in query:
            return Res(rows.get("user_id", {}).get(label, []))
        if "composite_key IS NULL" in query:
            return Res(rows.get("composite", {}).get(label, []))
        raise AssertionError("unexpected query: %r" % query)


class Driver:
    def __init__(self, scenario):
        self.session_obj = Session(scenario)
    def session(self):
        return self.session_obj
    def close(self):
        pass


U = {"Entity": [{"updated": 3}], "Document": [{"updated": 2}],
     "PairWeight": [{"updated": 0}], "RelationWeight": [{"updated": 11}]}
CK = {
    "Document": [
        {"eid": "4:abc:1", "namespace": "n1", "user_id": "u1", "id": "doc-1"},
        {"eid": "4:abc:2", "namespace": None, "user_id": None, "id": None},
        {"eid": "4:abc:3", "namespace": "", "user_id": "", "id": 7},
        {"eid": "4:abc:4", "namespace": "n\u00e9", "user_id": "\U0001F600", "id": 0},
    ],
    "Entity": [
        {"eid": "4:e:1", "namespace": "n1", "user_id": "u1", "name": "Acme Corp"},
        {"eid": "4:e:2", "namespace": None, "user_id": None, "name": None},
        {"eid": "4:e:3", "namespace": "n1", "user_id": "", "name": "\u00c9cole \U0001F600"},
    ],
    "PairWeight": [
        {"eid": "4:p:1", "namespace": "n1", "user_id": "u1", "document_id": "d1", "entity_a": "acme corp", "entity_b": "globex"},
        {"eid": "4:p:2", "namespace": None, "user_id": None, "document_id": None, "entity_a": None, "entity_b": None},
        {"eid": "4:p:3", "namespace": "n1", "user_id": "u1", "document_id": 12, "entity_a": "a", "entity_b": "b"},
    ],
    "RelationWeight": [
        {"eid": "4:r:1", "namespace": "n1", "user_id": "u1", "document_id": "d1", "subject": "Acme Corp",
         "relation_type": "PARTNERED_WITH", "object": "Globex"},
        {"eid": "4:r:2", "namespace": None, "user_id": None, "document_id": None, "subject": None,
         "relation_type": None, "object": None},
    ],
}
MANY = [{"eid": "4:m:%d" % i, "namespace": "n", "user_id": "u", "name": "e%d" % i} for i in range(7)]
CO = [
    {"eid": "5:r:1", "namespace": "n1", "user_id": "u1", "a": "Globex", "b": "Acme"},
    {"eid": "5:r:2", "namespace": "n1", "user_id": "u1", "a": "Acme", "b": "Globex"},
    {"eid": "5:r:3", "namespace": None, "user_id": None, "a": None, "b": "x"},
    {"eid": "5:r:4", "namespace": "n1", "user_id": "", "a": "same", "b": "same"},
    {"eid": "5:r:5", "namespace": "n1", "user_id": "u", "a": "\U00010000x", "b": "\uffffx"},
    {"eid": "5:r:6", "namespace": "n1", "user_id": "u", "a": "B", "b": "a"},
    {"eid": "5:r:7", "namespace": "n1", "user_id": "u", "a": "", "b": "z"},
]

UID = "backfill_user_id_defaults"
CKM = "backfill_composite_key"
COM = "backfill_co_occurs_with_composite_key"


def bf(name, method, rows=None, no_driver=False, **kw):
    args = {"namespace": None}
    if method != UID:
        args["batch_size"] = 500
    args.update(kw)
    return {"name": name, "method": method, "args": args, "rows": rows or {}, "no_driver": no_driver}


B = [
    bf("user_id_all", UID, rows={"user_id": U}),
    bf("user_id_ns", UID, rows={"user_id": U}, namespace="n1"),
    bf("user_id_ns_empty", UID, rows={"user_id": U}, namespace=""),
    bf("user_id_ns_unicode", UID, rows={"user_id": U}, namespace="ns-\u00e9-\U0001F600"),
    bf("user_id_no_rows", UID),
    bf("user_id_partial", UID, rows={"user_id": {"Entity": [{"updated": 4}], "Document": [{"updated": 9}]}}),
    bf("user_id_no_driver", UID, no_driver=True),
    bf("composite_default", CKM, rows={"composite": CK}),
    bf("composite_ns", CKM, rows={"composite": CK}, namespace="n1"),
    bf("composite_ns_empty", CKM, rows={"composite": CK}, namespace=""),
    bf("composite_batch_1", CKM, rows={"composite": CK}, batch_size=1),
    bf("composite_batch_3_many", CKM, rows={"composite": {"Entity": MANY}}, batch_size=3),
    bf("composite_batch_0", CKM, rows={"composite": CK}, batch_size=0),
    bf("composite_batch_0_empty", CKM, batch_size=0),
    bf("composite_batch_negative", CKM, rows={"composite": CK}, batch_size=-2),
    bf("composite_empty", CKM),
    bf("composite_no_driver", CKM, no_driver=True),
    bf("co_default", COM, rows={"composite": {"co": CO}}),
    bf("co_ns", COM, rows={"composite": {"co": CO}}, namespace="n1"),
    bf("co_batch_2", COM, rows={"composite": {"co": CO}}, batch_size=2),
    bf("co_batch_0", COM, rows={"composite": {"co": CO}}, batch_size=0),
    bf("co_batch_negative", COM, rows={"composite": {"co": CO}}, batch_size=-1),
    bf("co_empty", COM),
    bf("co_no_driver", COM, no_driver=True),
]


def run_backfill(case):
    drv = None if case["no_driver"] else Driver({"rows": case["rows"]})
    g = rg.GraphIndex.__new__(rg.GraphIndex)
    g.driver = drv
    result, raises = None, None
    try:
        result = getattr(g, case["method"])(**case["args"])
    except Exception as e:
        raises = type(e).__name__
    case["calls"] = [] if drv is None else drv.session_obj.calls
    case["result"] = result
    case["raises"] = raises
    return case


class SpecMigration(Migration):
    def __init__(self, spec):
        self.spec = spec
    @property
    def id(self):
        return self.spec["id"]
    @property
    def description(self):
        return self.spec.get("description", "fake migration")
    def up(self, session):
        if "raises" in self.spec:
            raise ValueError(self.spec["raises"])
        return self.spec["result"] if "result" in self.spec else {"updated": 1}


class FakeTime:
    def __init__(self, step):
        self.n = 0
        self.step = step
    def monotonic_ns(self):
        v = self.n * self.step
        self.n += 1
        return v


def spec(id_, **kw):
    d = {"id": id_}
    d.update(kw)
    return d


def rc(name, ops, migrations=None, **kw):
    c = {"name": name, "ops": ops, "migrations": migrations or []}
    c.update(kw)
    return c


RUN = {"op": "run_pending"}
DRY = {"op": "run_pending", "dry_run": True}
ST = {"op": "status"}
SORT_IDS = ["0002_second", "0001_first", "b", "B", "a", "\uffffx", "\U00010000x", "0010_x", "0003_y"]
VARIETY = {
    "counts": {"Entity": 5, "Document": 0}, "list": [1, 2, [3, {"k": None}]], "flag": True, "off": False,
    "text": "quote\" back\\slash nl\n tab\t cr\r bs\b ff\f ctl\x01 del\x7f",
    "uni": "caf\u00e9 \u4e2d\u6587 \U0001F600", "empty_dict": {}, "empty_list": [],
    "big": 123456789012345678901234567890, "neg": -7,
}
FLOATS = {"f": [1.5, 0.0001, 1e-05, 1e16, 1e15, 123456789.123, -0.0, 100.0, 1e22, 0.1, 2.5e-07, -1234.5]}
R = [
    rc("driver_none", [RUN], migrations=[spec("0001_a")], driver_none=True),
    rc("sort_dry_run", [DRY], migrations=[spec(i) for i in SORT_IDS]),
    rc("sort_apply", [RUN, ST], migrations=[spec(i, result={"id": i}) for i in SORT_IDS]),
    rc("dry_run_no_execute", [DRY], migrations=[spec("0001_test", raises="must not run", result={"updated": 99})]),
    rc("skips_applied", [RUN], migrations=[spec("0001_already_done")], applied_ids=["0001_already_done"]),
    rc("apply_records", [RUN], migrations=[spec("0001_test", description="does a thing", result={"Entity": 5})]),
    rc("failure_stops", [RUN], migrations=[spec("0001_fails", raises="simulated migration failure"), spec("0002_never_reached")]),
    rc("failure_second", [RUN], migrations=[spec("0001_ok", result={"a": 1}), spec("0002_fails", raises="boom: \u00e9")]),
    rc("failure_empty_message", [RUN], migrations=[spec("0001_fails", raises="")]),
    rc("status_mixed", [ST], migrations=[spec("0001_applied"), spec("0002_pending")], applied_ids=["0001_applied"]),
    rc("status_none_values", [ST], migrations=[spec("0001_applied")], applied_ids=["0001_applied"],
       status_row={"applied_at": None, "elapsed_ms": None}),
    rc("status_no_row", [ST], migrations=[spec("0001_applied")], applied_ids=["0001_applied"], status_row=None),
    rc("idempotent", [RUN, RUN, ST], migrations=[spec("0001_a", result={"n": 1}), spec("0002_b", result={"n": 2})]),
    rc("down_default", [{"op": "down", "index": 0}], migrations=[spec("0001_test")]),
    rc("result_json_variety", [RUN], migrations=[spec("0001_x", result=VARIETY)]),
    rc("result_json_floats", [RUN], migrations=[spec("0001_x", result=FLOATS)]),
    rc("result_none", [RUN], migrations=[spec("0001_x", result=None)]),
    rc("clock_floor", [RUN], migrations=[spec("0001_a"), spec("0002_b")], clock_step_ns=999999),
    rc("registry_real", [DRY, RUN, RUN, ST], registry=True, rows={"user_id": U, "composite": CK}),
]


def run_runner(c):
    scenario = {"applied_ids": c.get("applied_ids", []), "rows": c.get("rows", {})}
    if "status_row" in c:
        scenario["status_row"] = c["status_row"]
    drv = Driver(scenario)
    migs = list(ALL_MIGRATIONS) if c.get("registry") else [SpecMigration(s) for s in c["migrations"]]
    runner_mod.time = FakeTime(c.get("clock_step_ns", 7500000))
    c["ops_out"] = []
    try:
        runner = MigrationRunner(None if c.get("driver_none") else drv, migs)
    except Exception as e:
        c["ctor_raises"] = type(e).__name__
        c["ctor_message"] = str(e)
        c["calls"] = []
        return c
    for op in c["ops"]:
        rec = {"op": op["op"]}
        try:
            if op["op"] == "run_pending":
                rec["result"] = runner.run_pending(dry_run=op.get("dry_run", False))
            elif op["op"] == "status":
                rec["result"] = runner.status()
            elif op["op"] == "down":
                rec["result"] = migs[op["index"]].down(None)
        except Exception as e:
            rec["raises"] = type(e).__name__
            rec["message"] = str(e)
        c["ops_out"].append(rec)
        if "raises" in rec:
            break
    c["calls"] = drv.session_obj.calls
    c["sorted_ids"] = [m.id for m in runner.migrations]
    return c


b_out = [run_backfill(c) for c in B]
r_out = [run_runner(c) for c in R]
json.dump(b_out, open(os.path.join(OUT, "backfill_cases.json"), "w"), indent=1)
json.dump({"registry": [{"id": m.id, "description": m.description} for m in ALL_MIGRATIONS], "cases": r_out},
          open(os.path.join(OUT, "migrations_cases.json"), "w"), indent=1)
print("backfill scenarios:", len(b_out), "| runner scenarios:", len(r_out), "| written to", OUT)
for c in b_out:
    if c["raises"]:
        print("  python raised in", c["name"], "->", c["raises"])
for c in r_out:
    for o in c["ops_out"]:
        if o.get("raises"):
            print("  python raised in", c["name"], "->", o["raises"])
