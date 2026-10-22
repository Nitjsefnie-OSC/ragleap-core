import hashlib
import json
import os
import stat
import subprocess
import sys
import threading

import pytest

from ragleap_security import GENESIS, AuditError, AuditLog, Scope, SecretStr, verify


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def fill(log, n=5):
    for i in range(n):
        log.append("step.done", {"i": i}, Scope("acme", "u1"))


def lines(log):
    return open(log.path, "rb").read().split(b"\n")[:-1]


def write_lines(log, ls):
    open(log.path, "wb").write(b"".join(l + b"\n" for l in ls))


def rehash(rec):
    body = {k: v for k, v in rec.items() if k != "hash"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    rec["hash"] = hashlib.sha256(canon).hexdigest()
    return rec


def test_empty_and_missing_log_verify_ok(log):
    r = log.verify()
    assert r.ok and r.records == 0 and r.last_hash == GENESIS


def test_append_chain_and_verify(log):
    fill(log)
    r = log.verify()
    assert r.ok and r.records == 5
    recs = [json.loads(l) for l in lines(log)]
    assert [x["seq"] for x in recs] == [1, 2, 3, 4, 5]
    assert recs[0]["prev"] == GENESIS and recs[1]["prev"] == recs[0]["hash"]
    assert recs[0]["scope"] == "tenant=acme/subject=u1"


def test_append_returns_the_written_record(log):
    rec = log.append("a.b", {"x": 1})
    assert json.loads(lines(log)[0]) == rec and rec["scope"] is None


def test_file_mode_is_private(log):
    fill(log, 1)
    assert stat.S_IMODE(os.stat(log.path).st_mode) == 0o600


def test_secretstr_is_redacted_in_the_log(log):
    log.append("login.ok", {"password": SecretStr("hunter2-hunter2"), "user": "u1"})
    raw = open(log.path).read()
    assert "hunter2" not in raw and "[REDACTED]" in raw and log.verify().ok


def test_edited_record_is_detected(log):
    fill(log)
    ls = lines(log)
    rec = json.loads(ls[2])
    rec["data"]["i"] = 99
    ls[2] = json.dumps(rec).encode()
    write_lines(log, ls)
    r = log.verify()
    assert not r.ok and r.line == 3


def test_deleted_middle_record_is_detected(log):
    fill(log)
    ls = lines(log)
    del ls[2]
    write_lines(log, ls)
    r = log.verify()
    assert not r.ok and r.line == 3


def test_reordered_and_inserted_records_are_detected(log):
    fill(log)
    ls = lines(log)
    ls[1], ls[2] = ls[2], ls[1]
    write_lines(log, ls)
    assert not log.verify().ok
    fill_log = AuditLog(str(log.path) + "2")
    fill(fill_log)
    other = lines(fill_log)
    ls = lines(log)
    ls.insert(2, other[1])
    write_lines(log, ls)
    assert not log.verify().ok


def test_wrong_fields_bad_json_and_incomplete_record_are_detected(log):
    fill(log, 2)
    good = lines(log)
    write_lines(log, [good[0], b"not json"])
    assert log.verify().error == "record is not valid JSON"
    rec = json.loads(good[0])
    rec["extra"] = 1
    write_lines(log, [json.dumps(rec).encode()])
    assert log.verify().error == "record has the wrong fields"
    open(log.path, "wb").write(good[0] + b"\n" + good[1][:20])
    assert log.verify().error == "last record is incomplete"


def test_truncated_tail_is_NOT_detected_without_an_anchor(log):
    # Documented limitation: cutting records off the end leaves a valid shorter log.
    fill(log)
    ls = lines(log)
    write_lines(log, ls[:3])
    assert log.verify().ok


def test_truncated_tail_is_detected_with_an_anchor(log):
    fill(log)
    anchor = log.verify()
    write_lines(log, lines(log)[:3])
    assert not log.verify(expected_count=anchor.records).ok
    assert not log.verify(expected_last_hash=anchor.last_hash).ok
    assert log.verify(expected_count=3).ok  # positive control


def test_full_rewrite_with_recomputed_hashes_is_NOT_detected(log):
    # Documented limitation: tamper-evident, not tamper-proof, against someone who can rewrite the file.
    fill(log, 3)
    recs = [json.loads(l) for l in lines(log)]
    recs[1]["data"]["i"] = 99
    prev = GENESIS
    out = []
    for r in recs:
        r["prev"] = prev
        r = rehash(r)
        prev = r["hash"]
        out.append(json.dumps(r, sort_keys=True, separators=(",", ":")).encode())
    write_lines(log, out)
    assert log.verify().ok


def test_append_refuses_to_extend_a_corrupt_log(log):
    fill(log, 2)
    good = lines(log)
    write_lines(log, [good[0], b"garbage"])
    with pytest.raises(AuditError):
        log.append("more.events")
    open(log.path, "wb").write(good[0] + b"\n" + good[1][:20])
    with pytest.raises(AuditError):
        log.append("more.events")
    rec = json.loads(good[1])
    rec["data"]["i"] = 7
    write_lines(log, [good[0], json.dumps(rec).encode()])
    with pytest.raises(AuditError):
        log.append("more.events")


@pytest.mark.parametrize("event", ["", "Upper", "1abc", "has space", "a" * 65, None, 5, "x\n"])
def test_bad_event_names_refused(log, event):
    with pytest.raises(AuditError):
        log.append(event)


def test_bad_data_and_scope_refused(log):
    with pytest.raises(AuditError):
        log.append("a.b", ["not", "a", "dict"])
    with pytest.raises(AuditError):
        log.append("a.b", {"x": object()})
    with pytest.raises(Exception):
        log.append("a.b", {}, scope="tenant=acme")  # a string is not a Scope
    assert not os.path.exists(log.path) or log.verify().records == 0


def test_oversized_record_refused_and_log_unchanged(log):
    fill(log, 1)
    before = open(log.path, "rb").read()
    with pytest.raises(AuditError):
        log.append("big.one", {"blob": "x" * 70_000})
    assert open(log.path, "rb").read() == before
    log.append("big.ok", {"blob": "x" * 60_000})  # positive control just under the limit
    assert log.verify().ok


def test_threads_keep_the_chain_valid(log):
    def work():
        for i in range(25):
            log.append("t.work", {"i": i})

    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    r = log.verify()
    assert r.ok and r.records == 200


@pytest.mark.skipif(sys.platform == "win32", reason="cross-process locking is POSIX only")
def test_processes_keep_the_chain_valid(log):
    code = (
        "import sys; from ragleap_security import AuditLog; l = AuditLog(sys.argv[1])\n"
        "[l.append('p.work', {'i': i}) for i in range(20)]"
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    ps = [subprocess.Popen([sys.executable, "-c", code, str(log.path)], env=env) for _ in range(4)]
    assert all(p.wait() == 0 for p in ps)
    r = log.verify()
    assert r.ok and r.records == 80


def test_module_level_verify_matches_method(log):
    fill(log, 2)
    assert verify(log.path) == log.verify()
