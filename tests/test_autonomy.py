"""
Tests for core/autonomy.py - the single-tenant Autonomous Loop.
Requires a Postgres DB with db/schema.sql applied, reachable via the
DATABASE_URL env var (same convention as core/employees/_db.py).
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import action_senders
from core import autonomy
from core.employees._db import get_connection


@pytest.fixture(autouse=True)
def clean_autonomy_tables():
    """Reset autonomy tables before each test so tests do not interfere."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM autonomy_settings")
        cur.execute("DELETE FROM autonomy_pending")
        cur.execute("DELETE FROM autonomy_log")
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield


def test_default_settings_are_off():
    settings = autonomy.get_autonomy_settings()
    assert settings["mode"] == "off"
    assert settings["channels"] == []
    assert settings["actions"] == []


def test_set_and_get_settings_roundtrip():
    ok = autonomy.set_autonomy(
        mode="semi",
        channels=["telegram"],
        actions=["followup"],
        approval_channel="telegram",
        approval_target="12345",
    )
    assert ok is True

    settings = autonomy.get_autonomy_settings()
    assert settings["mode"] == "semi"
    assert settings["channels"] == ["telegram"]
    assert settings["actions"] == ["followup"]
    assert settings["approval_target"] == "12345"


def test_off_mode_skips_everything():
    autonomy.set_autonomy(mode="off")
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123", content="hi"
    )
    assert result["status"] == "skipped"
    assert result["result"] == "autonomy off"


def test_action_allowlist_blocks_disallowed_action():
    autonomy.set_autonomy(mode="full", actions=["reply"], channels=[])
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123", content="hi"
    )
    assert result["status"] == "skipped"
    assert "not in allowed actions" in result["result"]


def test_channel_allowlist_blocks_disallowed_channel():
    autonomy.set_autonomy(mode="full", actions=[], channels=["discord"])
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123", content="hi"
    )
    assert result["status"] == "skipped"
    assert "not in allowed channels" in result["result"]


def test_full_mode_executes_via_custom_fn_and_logs():
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    called = {}

    def fake_execute():
        called["ran"] = True
        return "custom result"

    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=fake_execute,
    )
    assert result["status"] == "executed"
    assert result["result"] == "custom result"
    assert called["ran"] is True

    report = autonomy.generate_autonomy_daily_report()
    assert "followup" in report


def test_semi_mode_creates_pending_and_approval_flow():
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="999", content="test message"
    )
    assert result["status"] == "pending_approval"
    action_id = result["action_id"]
    assert len(action_id) == 8

    reply = autonomy.process_approval_response(f"NO {action_id}")
    assert reply is not None
    assert "rejected" in reply.lower()


def test_process_approval_response_ignores_non_approval_messages():
    reply = autonomy.process_approval_response("What are your business hours?")
    assert reply is None


def test_process_approval_response_unknown_id():
    reply = autonomy.process_approval_response("YES ZZZZZZZZ")
    assert reply is not None
    assert "not found" in reply.lower()


def test_sensitive_role_forces_full_to_semi():
    """core.employees.defaults.SENSITIVE_DOMAIN_ROLES enforcement: a role
    in that set must never execute directly even when general mode is
    'full' -- it should be forced down to the approval flow instead."""
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    called = {}

    def fake_execute():
        called["ran"] = True
        return "should not run"

    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=fake_execute, role="legal_intake",
    )
    assert result["status"] == "pending_approval"
    assert "ran" not in called, "sensitive-domain role executed directly in full mode -- guardrail not enforced"


def test_non_sensitive_role_full_mode_executes_normally():
    """A role NOT in SENSITIVE_DOMAIN_ROLES should behave exactly like
    the no-role case -- full mode executes directly, no forced downgrade."""
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    called = {}

    def fake_execute():
        called["ran"] = True
        return "custom result"

    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=fake_execute, role="sales",
    )
    assert result["status"] == "executed"
    assert called["ran"] is True


def test_role_is_persisted_in_autonomy_log():
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=lambda: "ok", role="support",
    )
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM autonomy_log ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "support"


def test_role_is_persisted_through_semi_approval_flow():
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="999",
        content="test message", role="healthcare_intake",
    )
    assert result["status"] == "pending_approval"
    action_id = result["action_id"]

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM autonomy_pending WHERE action_id = %s", (action_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "healthcare_intake"

    reply = autonomy.process_approval_response(f"NO {action_id}")
    assert reply is not None

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM autonomy_log ORDER BY id DESC LIMIT 1")
        log_row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert log_row is not None
    assert log_row[0] == "healthcare_intake"


def test_role_optional_backward_compatible():
    """Existing callers that never pass role must keep working exactly
    as before -- role stays None throughout, nothing breaks."""
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    result = autonomy.execute_or_request(
        action_type="followup", channel="telegram", target="123",
        content="hi", execute_fn=lambda: "ok",
    )
    assert result["status"] == "executed"


# ---- HubSpot CRM record-update action ----------------------------------------

CRM_CONTENT = (
    "Object: contacts\n"
    "Id: 715559271\n"
    "Set: firstname = Jane\n"
    "Set: lastname = Doe"
)


def _patched_crm_sender(return_value=True):
    """Replace the CRM sender so no test touches HubSpot; create=True so the
    red run on a pre-feature main fails by assertion (the gate never calls
    the sender) instead of erroring on a missing attribute. Every
    configuration patch below spans the WHOLE flow its test claims to prove -
    proposal AND approval execution - because a patch that ends at the
    proposal step lets the real (unconfigured) sender answer at approval
    time."""
    return patch.object(action_senders, "send_crm_update",
                        return_value=True, create=True)


def test_crm_off_mode_skips_with_no_sender_call():
    # Guard branch: off mode. actions/channels empty, so ONLY the mode
    # refuses; no write of any kind happens.
    autonomy.set_autonomy(mode="off")
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="", content=CRM_CONTENT
        )
    assert result["status"] == "skipped"
    assert result["result"] == "autonomy off"
    assert sender.called is False


def test_crm_actions_allowlist_blocks_with_no_sender_call():
    # Guard branch: actions allowlist (mode full, channels empty, so the
    # actions gate is the only refuser).
    autonomy.set_autonomy(mode="full", actions=["followup"], channels=[])
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="", content=CRM_CONTENT
        )
    assert result["status"] == "skipped"
    assert "not in allowed actions" in result["result"]
    assert sender.called is False


def test_crm_channels_allowlist_blocks_with_no_sender_call():
    # Guard branch: channels allowlist (mode full, actions empty).
    autonomy.set_autonomy(mode="full", actions=[], channels=["email"])
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="", content=CRM_CONTENT
        )
    assert result["status"] == "skipped"
    result_text = str(result.get("result"))
    assert "not in allowed channels" in result_text
    assert sender.called is False


def test_crm_full_mode_executes_and_logs():
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="", content=CRM_CONTENT
        )
    assert result["status"] == "executed"
    assert "updated" in str(result["result"]) and "failed" not in str(result["result"])
    assert sender.called is True
    report = autonomy.generate_autonomy_daily_report()
    assert "update_crm_record" in report


def test_crm_semi_mode_pending_then_approval_executes_through_the_same_path():
    # Semi mode: pending row + approval request through the existing
    # mechanism; approving runs it through _send_via_channel, the same path
    # as every other channel - no parallel mechanism. The sender patch spans
    # proposal AND approval execution (see _patched_crm_sender).
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="", content=CRM_CONTENT
        )
        assert result["status"] == "pending_approval"
        action_id = result["action_id"]
        assert len(action_id) == 8

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT channel, target, content FROM autonomy_pending WHERE action_id = %s",
                        (action_id,))
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "crm" and row[1] == "" and row[2] == CRM_CONTENT

        # Approving must run the SAME _send_via_channel path with the patched
        # sender still in place - without the patch the real (unconfigured)
        # sender would answer here and prove nothing.
        reply = autonomy.process_approval_response(f"YES {action_id}")
    assert reply is not None
    assert "approved and executed" in reply
    assert "updated" in reply and "failed" not in reply
    assert sender.called is True
    assert sender.call_args.args == ("", CRM_CONTENT)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT channel, target, content FROM autonomy_pending WHERE action_id = %s",
                    (action_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert row is None  # approved actions leave the pending table

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT approved FROM autonomy_log WHERE action_type = 'update_crm_record' "
                    "ORDER BY id DESC LIMIT 1")
        log_row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    assert log_row is not None and log_row[0] is True


def test_crm_sensitive_role_forces_full_to_semi():
    # Guard branch: a sensitive-domain role must never execute a CRM write
    # directly in full mode; it is forced down to the approval flow.
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="",
            content=CRM_CONTENT, role="legal_intake",
        )
    assert result["status"] == "pending_approval"
    assert sender.called is False


def test_crm_non_sensitive_role_stays_full():
    # The distinct other side: a non-sensitive role executes normally.
    autonomy.set_autonomy(mode="full", actions=[], channels=[])
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="",
            content=CRM_CONTENT, role="sales",
        )
    assert result["status"] == "executed"
    assert "updated" in str(result["result"])
    assert sender.called is True


@pytest.mark.parametrize("mode,actions_allow,channels_allow,role,expect", [
    # The PRODUCT of the axes: the action reaches the network only in the
    # one combination where every gate opens.
    ("off", [], [], None, "skipped"),
    ("full", ["update_crm_record"], ["crm"], None, "executed"),
    ("full", ["update_crm_record"], ["crm"], "legal_intake", "pending_approval"),
    ("semi", ["update_crm_record"], ["crm"], None, "pending_approval"),
    ("full", ["followup"], ["crm"], None, "skipped"),
    ("full", ["update_crm_record"], ["email"], None, "skipped"),
    ("semi", ["followup"], ["crm"], None, "skipped"),
    ("semi", ["update_crm_record"], ["email"], None, "skipped"),
])
def test_crm_gate_product_matrix(mode, actions_allow, channels_allow, role, expect):
    autonomy.set_autonomy(mode=mode, actions=actions_allow, channels=channels_allow,
                          approval_channel="telegram", approval_target="")
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="",
            content=CRM_CONTENT, role=role,
        )
    assert result["status"] == expect
    assert sender.called is (expect == "executed")


def test_crm_rejection_still_logs_through_the_same_path():
    autonomy.set_autonomy(
        mode="semi", actions=[], channels=[],
        approval_channel="telegram", approval_target="",
    )
    with _patched_crm_sender() as sender:
        result = autonomy.execute_or_request(
            action_type="update_crm_record", channel="crm", target="", content=CRM_CONTENT
        )
    assert result["status"] == "pending_approval"
    reply = autonomy.process_approval_response(f"NO {result['action_id']}")
    assert reply is not None
    assert "rejected" in reply.lower()
    assert sender.called is False  # a rejected CRM write never executes
