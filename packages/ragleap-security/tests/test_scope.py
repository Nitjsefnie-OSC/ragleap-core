import pytest

from ragleap_security import Scope, ScopeError, require_scope


def test_valid_scope_and_key():
    s = Scope("acme", "alice", "bot", "s1")
    assert s.key == "tenant=acme/subject=alice/agent=bot/session=s1"
    assert Scope("acme").key == "tenant=acme"


@pytest.mark.parametrize("bad", ["", " ", "a/b", "a=b", "a b", "-x", "x\n", "a" * 129, "é", None, 5])
def test_invalid_tenant_refused(bad):
    with pytest.raises(ScopeError):
        Scope(bad)


@pytest.mark.parametrize("field", ["subject", "agent", "session"])
def test_invalid_optional_parts_refused(field):
    with pytest.raises(ScopeError):
        Scope("acme", **{field: "a/b"})
    with pytest.raises(ScopeError):
        Scope("acme", **{field: ""})


def test_boundary_length_accepted():
    assert Scope("a" * 128).tenant == "a" * 128  # positive control for the length check


def test_key_is_injective_and_roundtrips():
    scopes = [Scope("a"), Scope("a", "b"), Scope("a", agent="b"), Scope("a", session="b"),
              Scope("a", "b", "c"), Scope("a", "b", "c", "d"), Scope("a.b", "c")]
    keys = [s.key for s in scopes]
    assert len(set(keys)) == len(keys)
    for s in scopes:
        assert Scope.parse(s.key) == s


@pytest.mark.parametrize("bad", ["", "tenant", "subject=x", "tenant=a/subject", "tenant=a/zzz=b",
                                 "tenant=a/agent=x/subject=y", "tenant=a/tenant=b", "tenant=a//subject=b"])
def test_parse_rejects_malformed_keys(bad):
    with pytest.raises(ScopeError):
        Scope.parse(bad)


def test_scope_is_immutable_and_hashable():
    s = Scope("a")
    with pytest.raises(Exception):
        s.tenant = "b"
    assert {s: 1}[Scope("a")] == 1


def test_covers_tenant_wide_covers_narrower_not_reverse():
    wide, narrow = Scope("a"), Scope("a", "u1", "bot")
    assert wide.covers(narrow) and wide.covers(wide)
    assert not narrow.covers(wide)


def test_covers_refuses_other_tenant_and_other_subject():
    assert not Scope("a").covers(Scope("b"))
    assert not Scope("a", "u1").covers(Scope("a", "u2"))
    assert not Scope("a", "u1").covers(Scope("a"))
    assert Scope("a", "u1").covers(Scope("a", "u1", "bot"))  # positive control


def test_covers_refuses_non_scope_and_subclass():
    class Fake(Scope):
        pass

    assert not Scope("a").covers("tenant=a")
    assert not Scope("a").covers(Fake("a"))
    assert not Scope("a").covers(None)


def test_narrow_adds_parts_and_cannot_change_set_parts():
    s = Scope("a").narrow(subject="u1")
    assert s == Scope("a", "u1")
    assert s.narrow(subject="u1") == s  # same value is fine
    with pytest.raises(ScopeError):
        s.narrow(subject="u2")
    with pytest.raises(ScopeError):
        s.narrow(tenant="b")
    with pytest.raises(ScopeError):
        s.narrow(color="red")


def test_require_scope_accepts_only_exact_scope():
    s = Scope("a")
    assert require_scope(s) is s

    class Fake(Scope):
        pass

    for bad in ("tenant=a", {"tenant": "a"}, None, Fake("a"), 5):
        with pytest.raises(ScopeError):
            require_scope(bad)
