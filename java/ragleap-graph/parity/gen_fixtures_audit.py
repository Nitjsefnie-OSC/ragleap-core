# Generates parity recordings for the Postgres audit logger by running the real Python AuditLogger against a stubbed
# psycopg2 that records every connect, autocommit, execute (SQL and parameters) and close, plus the warnings the
# logger emits (as kinds). Writes audit_cases.json into RAGLEAP_GRAPH_PARITY_DIR (default /tmp/fixtures-graph-a).
# Pinned commit: 226fa4de350ba702f13ce996b594ad614f98d881 (packages/ragleap-graph, version 0.9.0).
# Export first: git archive 226fa4de350ba702f13ce996b594ad614f98d881 packages/ragleap-graph | tar -x -C /tmp/py-graph-pinned
import json, logging, os, sys, types
SRC = "/tmp/py-graph-pinned/packages/ragleap-graph/src"
sys.path.insert(0, SRC)
import ragleap_graph as rg
assert rg.__file__.startswith(SRC), "wrong module path"
from ragleap_graph._audit import AuditConfig, AuditLogger
OUT = os.environ.get("RAGLEAP_GRAPH_PARITY_DIR", "/tmp/fixtures-graph-a")
os.makedirs(OUT, exist_ok=True)


def kind_of(msg):
    if msg.startswith("Audit log connection failed"):
        return "connect_failed"
    if msg.startswith("Audit log schema setup failed"):
        return "schema_failed"
    if msg.startswith("Audit log write failed"):
        return "write_failed"
    if msg.startswith("AuditConfig.database_url is set but psycopg2"):
        return "no_driver"
    return "other:" + msg


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.kinds = []

    def emit(self, record):
        self.kinds.append(kind_of(record.getMessage()))


class State:
    def __init__(self, sc):
        self.sc = sc
        self.events = []
        self.connects = 0
        self.executes = 0


class FakeCursor:
    def __init__(self, st):
        self.st = st

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        i = self.st.executes
        self.st.executes += 1
        self.st.events.append(["execute", "".join(sql.split()).replace("%s", "?"),
                               list(params) if params is not None else []])
        if i in self.st.sc["execute_failures"]:
            raise RuntimeError("scripted execute failure")


class FakeConn:
    def __init__(self, st):
        self.st = st
        self._autocommit = None

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._autocommit = value
        self.st.events.append(["autocommit", value])

    def cursor(self):
        return FakeCursor(self.st)

    def close(self):
        self.st.events.append(["close"])
        if self.st.sc["close_fails"]:
            raise RuntimeError("scripted close failure")


def install(st):
    if st.sc["driver_missing"]:
        sys.modules["psycopg2"] = None
        return

    def connect(url):
        i = st.connects
        st.connects += 1
        st.events.append(["connect", url])
        results = st.sc["connect_results"]
        if i < len(results) and results[i] is False:
            raise RuntimeError("scripted connect failure")
        return FakeConn(st)

    mod = types.ModuleType("psycopg2")
    mod.connect = connect
    sys.modules["psycopg2"] = mod


def decode(v):
    if isinstance(v, dict):
        if set(v) == {"__set__"}:
            return set(v["__set__"])
        if set(v) == {"__float__"}:
            return float(v["__float__"])
        return {k: decode(x) for k, x in v.items()}
    if isinstance(v, list):
        return [decode(x) for x in v]
    return v


URL = {"database_url": "postgresql://user:pw@localhost:5432/db"}


def S(name, ops, config=URL, connect_results=None, execute_failures=None, driver_missing=False, close_fails=False):
    return {"name": name, "ops": ops, "config": config, "connect_results": connect_results or [],
            "execute_failures": execute_failures or [], "driver_missing": driver_missing, "close_fails": close_fails}


def L(**kw):
    a = {"action": "upsert_document"}
    a.update(kw)
    return ["log", a]


SC = [
    S("disabled_no_config", [L(user_id="u1")], config=None),
    S("disabled_url_none", [L()], config={"database_url": None}),
    S("disabled_url_empty", [L()], config={"database_url": ""}),
    S("basic_log", [L(user_id="u1", namespace="ns", document_id="d1", entity_count=3,
                      detail={"relationships_indexed": 2, "relations_indexed": 0})]),
    S("second_log_reuses_connection", [L(user_id="u1"), L(user_id="u2", action="find")]),
    S("empty_user_and_namespace_become_null", [L(user_id="", namespace="")]),
    S("none_user_and_namespace", [L(user_id=None, namespace=None)]),
    S("document_id_empty_kept", [L(document_id="")]),
    S("entity_count_zero_and_none", [L(entity_count=0), L(entity_count=None)]),
    S("detail_none", [L(detail=None)]),
    S("detail_empty_dict", [L(detail={})]),
    S("detail_nested_unicode", [L(detail={"k\u00e9": ["\u4e2d\u6587", "\U0001F600", {"n": None}], "b": True, "i": 7})]),
    S("detail_floats", [L(detail={"a": 1.5, "b": 1e22, "c": 1e-05, "d": {"__float__": "nan"},
                                  "e": {"__float__": "inf"}, "f": {"__float__": "-inf"}, "g": -0.0})]),
    S("detail_escapes", [L(detail={"q": "say \"hi\"", "b": "back\\slash", "n": "line\nbreak", "c": "\u0001"})]),
    S("detail_not_serializable_drops_connection", [L(detail={"bad": {"__set__": [1]}}), L(user_id="u2")]),
    S("connect_fails_then_ok", [L(), L()], connect_results=[False, True]),
    S("connect_always_fails", [L(), L(), L()], connect_results=[False, False, False]),
    S("schema_create_table_fails_then_retried", [L(), L()], execute_failures=[0]),
    S("schema_index_fails_then_retried", [L(), L()], execute_failures=[2]),
    S("insert_fails_drops_connection", [L(user_id="a"), L(user_id="b")], execute_failures=[4]),
    S("driver_missing_warns_once", [L(), L(), L()], driver_missing=True),
    S("close_after_log", [L(), ["close"]]),
    S("close_without_connection", [["close"], ["close"]]),
    S("close_fails_is_swallowed", [L(), ["close"], L()], close_fails=True),
    S("log_after_close_reconnects", [L(), ["close"], L(user_id="again")]),
    S("alternating", [L(user_id="1"), L(user_id="2"), ["close"], L(user_id="3"), L(user_id="4")]),
    S("unicode_action_and_ids", [L(action="\u00e9v\u00e9nement \U0001F600", user_id="\u00fcser", namespace="n\u00e4",
                                   document_id="d\U0001F600")]),
]


def run(sc):
    st = State(sc)
    install(st)
    audit_logger = logging.getLogger("ragleap_graph.audit")
    cap = Capture()
    audit_logger.addHandler(cap)
    audit_logger.setLevel(logging.WARNING)
    audit_logger.propagate = False
    try:
        cfg = None if sc["config"] is None else AuditConfig(database_url=sc["config"]["database_url"])
        logger_obj = AuditLogger(cfg)
        for op in sc["ops"]:
            if op[0] == "log":
                a = op[1]
                detail = decode(a["detail"]) if a.get("detail") is not None else None
                logger_obj.log(user_id=a.get("user_id"), namespace=a.get("namespace"), action=a["action"],
                               document_id=a.get("document_id"), entity_count=a.get("entity_count"), detail=detail)
            else:
                logger_obj.close()
    finally:
        audit_logger.removeHandler(cap)
        sys.modules.pop("psycopg2", None)
    rec = dict(sc)
    rec["events"] = st.events
    rec["warnings"] = cap.kinds
    return rec


cases = [run(sc) for sc in SC]
json.dump({"cases": cases}, open(os.path.join(OUT, "audit_cases.json"), "w"))
print("audit scenarios:", len(cases), "| written to", OUT)
print("warning kinds seen:", sorted({k for c in cases for k in c["warnings"]}))
