import io

import pytest

from ragleap_security import Deadline, LimitError, bounded_read, check_json_shape, check_size


def test_check_size_str_bytes_and_boundary():
    check_size("abc", 3)
    check_size(b"abc", 3)
    with pytest.raises(LimitError):
        check_size("abcd", 3)
    with pytest.raises(LimitError):
        check_size(b"abcd", 3)


def test_check_size_counts_utf8_bytes_not_characters():
    with pytest.raises(LimitError):
        check_size("ééé", 5)  # 3 characters, 6 bytes
    check_size("ééé", 6)


def test_check_size_message_has_no_input():
    with pytest.raises(LimitError) as e:
        check_size("secret-value", 3)
    assert "secret-value" not in str(e.value)


@pytest.mark.parametrize("bad", [-1, True, 1.5, "3", None])
def test_check_size_rejects_bad_limits(bad):
    with pytest.raises(ValueError):
        check_size("a", bad)
    with pytest.raises(TypeError):
        check_size(5, 10)


def test_json_shape_depth_and_nodes():
    deep = cur = []
    for _ in range(40):
        nxt = []
        cur.append(nxt)
        cur = nxt
    with pytest.raises(LimitError):
        check_json_shape(deep, max_depth=32)
    check_json_shape(deep, max_depth=64)  # positive control
    with pytest.raises(LimitError):
        check_json_shape(list(range(10)), max_nodes=5)
    check_json_shape({"a": [1, 2, {"b": 3}]})


def test_json_shape_survives_hostile_nesting_without_recursion_error():
    cur = []
    root = cur
    for _ in range(100_000):
        nxt = []
        cur.append(nxt)
        cur = nxt
    with pytest.raises(LimitError):
        check_json_shape(root)


def test_json_shape_rejects_bad_settings():
    for kw in ({"max_depth": 0}, {"max_nodes": 0}, {"max_depth": True}):
        with pytest.raises(ValueError):
            check_json_shape([], **kw)


def test_bounded_read():
    assert bounded_read(io.BytesIO(b"abc"), 3) == b"abc"
    with pytest.raises(LimitError):
        bounded_read(io.BytesIO(b"abcd"), 3)


def test_deadline_with_fake_clock():
    now = [100.0]
    d = Deadline(5, clock=lambda: now[0])
    assert not d.expired() and d.remaining() == 5
    d.check()
    now[0] = 104.9
    assert not d.expired()
    now[0] = 105.0
    assert d.expired() and d.remaining() == 0
    with pytest.raises(LimitError):
        d.check("work")


@pytest.mark.parametrize("bad", [-1, True, "5", None])
def test_deadline_rejects_bad_seconds(bad):
    with pytest.raises(ValueError):
        Deadline(bad)
