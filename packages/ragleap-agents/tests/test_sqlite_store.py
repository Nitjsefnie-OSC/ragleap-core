import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import ragleap_agents
from ragleap_agents import InMemoryStateStore, SQLiteStateStore


def make(run_id="r1", status="awaiting_approval", **extra):
    s = {"run_id": run_id, "status": status, "pending": None, "steps": []}
    s.update(extra)
    return s


def test_roundtrip_and_unknown_run(tmp_path):
    store = SQLiteStateStore(tmp_path / "s.db")
    assert store.load("nope") is None
    store.save("r1", make(task="hi"))
    assert store.load("r1") == make(task="hi")


def test_state_survives_a_new_store_object(tmp_path):
    p = tmp_path / "s.db"
    SQLiteStateStore(p).save("r1", make())
    assert SQLiteStateStore(p).load("r1") == make()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_a_new_database_file_is_private(tmp_path):
    p = tmp_path / "s.db"
    SQLiteStateStore(p)
    assert (os.stat(p).st_mode & 0o777) == 0o600


@pytest.mark.parametrize("bad", ["", "../x", "a b", "a" * 65, "r;DROP", None, 5])
def test_bad_run_ids_are_refused(tmp_path, bad):
    store = SQLiteStateStore(tmp_path / "s.db")
    with pytest.raises(ValueError):
        store.save(bad, make())
    with pytest.raises(ValueError):
        store.load(bad)
    with pytest.raises(ValueError):
        store.save_if_status(bad, make(), "awaiting_approval")


@pytest.mark.parametrize("bad", ["", ":memory:"])
def test_only_a_real_file_path_is_accepted(bad):
    with pytest.raises(ValueError):
        SQLiteStateStore(bad)


def test_a_state_must_match_its_run_id_and_have_a_known_status(tmp_path):
    store = SQLiteStateStore(tmp_path / "s.db")
    with pytest.raises(ValueError):
        store.save("r1", make(run_id="other"))
    with pytest.raises(ValueError):
        store.save("r1", make(status="weird"))
    with pytest.raises(ValueError):
        store.save("r1", ["not", "a", "dict"])


def _tamper(path, run_id, text):
    con = sqlite3.connect(str(path))
    con.execute("UPDATE runs SET state = ? WHERE run_id = ?", (text, run_id))
    con.commit()
    con.close()


@pytest.mark.parametrize("text", [
    "not json", "[]", "null",
    json.dumps(make(run_id="other")),
    json.dumps(make(status="weird")),
])
def test_a_tampered_row_is_refused_on_load_and_on_claim(tmp_path, text):
    p = tmp_path / "s.db"
    store = SQLiteStateStore(p)
    store.save("r1", make())
    _tamper(p, "r1", text)
    with pytest.raises(ValueError):
        store.load("r1")
    with pytest.raises(ValueError):
        store.save_if_status("r1", make(status="running"), "awaiting_approval")
    con = sqlite3.connect(str(p))
    assert con.execute("SELECT state FROM runs").fetchone()[0] == text  # a refused claim writes nothing
    con.close()


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_save_if_status_succeeds_only_once(tmp_path, kind):
    store = InMemoryStateStore() if kind == "memory" else SQLiteStateStore(tmp_path / "s.db")
    store.save("r1", make())
    assert store.save_if_status("r1", make(status="running"), "awaiting_approval") is True
    assert store.save_if_status("r1", make(status="running"), "awaiting_approval") is False
    assert store.load("r1")["status"] == "running"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_save_if_status_on_an_unknown_run_is_false(tmp_path, kind):
    store = InMemoryStateStore() if kind == "memory" else SQLiteStateStore(tmp_path / "s.db")
    assert store.save_if_status("nope", make(run_id="nope", status="running"), "awaiting_approval") is False
    assert store.load("nope") is None


def test_a_claim_waits_for_a_competing_writer_instead_of_failing(tmp_path):
    p = tmp_path / "s.db"
    store = SQLiteStateStore(p)
    store.save("r1", make())
    other = sqlite3.connect(str(p), isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    result = []
    t = threading.Thread(target=lambda: result.append(
        store.save_if_status("r1", make(status="running"), "awaiting_approval")))
    t.start()
    time.sleep(0.3)
    assert t.is_alive()  # the claim is waiting for the competing writer
    other.execute("UPDATE runs SET state = ? WHERE run_id = ?", (json.dumps(make(status="running")), "r1"))
    other.execute("COMMIT")
    other.close()
    t.join(20)
    assert result == [False]  # the competitor won; this claim saw "running" and lost cleanly


CHILD = textwrap.dedent('''
    import os, sys, time
    sys.path.insert(0, sys.argv[1])
    from ragleap_agents import SQLiteStateStore
    store = SQLiteStateStore(sys.argv[2])
    open(sys.argv[3] + "." + sys.argv[4], "w").close()
    deadline = time.time() + 20
    while not os.path.exists(sys.argv[3]):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.001)
    state = {"run_id": "r1", "status": "running", "pending": None, "steps": []}
    print("1" if store.save_if_status("r1", state, "awaiting_approval") else "0")
''')


def test_exactly_one_of_several_processes_wins_the_claim(tmp_path):
    db, go = tmp_path / "s.db", tmp_path / "go"
    SQLiteStateStore(db).save("r1", make())
    src = os.path.dirname(os.path.dirname(os.path.abspath(ragleap_agents.__file__)))
    procs = [
        subprocess.Popen([sys.executable, "-c", CHILD, src, str(db), str(go), str(i)],
                         stdout=subprocess.PIPE, text=True)
        for i in range(4)
    ]
    t0 = time.time()
    while sum(os.path.exists("%s.%d" % (go, i)) for i in range(4)) < 4:
        assert time.time() - t0 < 30, "the child processes did not start"
        time.sleep(0.01)
    open(str(go), "w").close()
    outs = []
    for p in procs:
        out, _ = p.communicate(timeout=60)
        assert p.returncode == 0
        outs.append(out.strip())
    assert sorted(outs) == ["0", "0", "0", "1"]
    assert SQLiteStateStore(db).load("r1")["status"] == "running"
