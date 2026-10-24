"""Tests for core/action_senders.py: no network, DNS/HTTP/SMTP mocked."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import action_senders as a
from core import autonomy

PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]
ENV = {"WEBHOOK_TARGETS": "n8n=https://hooks.example.com/abc?x=1,crm=https://crm.example.com/in"}
EMAIL_ENV = {
    "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "u",
    "SMTP_PASSWORD": "p", "SMTP_FROM": "bot@example.com",
    "EMAIL_ALLOWED_RECIPIENTS": "boss@acme.com,@partner.com",
}


def _addr(ip):
    return [(2, 1, 6, "", (ip, 443))]


def _smtp():
    cls = MagicMock()
    smtp = MagicMock()
    cls.return_value.__enter__.return_value = smtp
    return cls, smtp


def test_webhook_unknown_target_fails_without_request():
    with patch.dict(os.environ, ENV), patch.object(a.requests, "post") as post:
        assert a.send_webhook("evil", "hi") is False
    post.assert_not_called()


def test_webhook_known_target_posts_without_redirects():
    with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post", return_value=MagicMock(status_code=200)) as post:
        assert a.send_webhook("n8n", "hello") is True
    assert post.call_args.args[0] == "https://hooks.example.com/abc?x=1"
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["json"]["text"] == "hello"


def test_webhook_non_public_addresses_blocked():
    for ip in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.10", "100.64.0.1"):
        with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=_addr(ip)), \
             patch.object(a.requests, "post") as post:
            assert a.send_webhook("n8n", "hi") is False, ip
        post.assert_not_called()


def test_webhook_http_scheme_blocked():
    env = {"WEBHOOK_TARGETS": "n8n=http://hooks.example.com/abc"}
    with patch.dict(os.environ, env), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post") as post:
        assert a.send_webhook("n8n", "hi") is False
    post.assert_not_called()


def test_webhook_non_2xx_is_failure():
    with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post", return_value=MagicMock(status_code=500)):
        assert a.send_webhook("n8n", "hi") is False


def test_webhook_request_exception_returns_false():
    with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post", side_effect=Exception("boom")):
        assert a.send_webhook("n8n", "hi") is False


def test_slack_requires_slack_hosted_url():
    for bad in ("", "https://evil.example.com/x", "http://hooks.slack.com/x"):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": bad}), patch.object(a.requests, "post") as post:
            assert a.send_slack("x", "hi") is False
        post.assert_not_called()


def test_slack_posts_when_configured():
    url = "https://hooks.slack.com/services/T/B/x"
    with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": url}), \
         patch.object(a.requests, "post", return_value=MagicMock(status_code=200)) as post:
        assert a.send_slack("label", "hello") is True
    assert post.call_args.args[0] == url and post.call_args.kwargs["json"]["text"] == "hello"
    assert post.call_args.kwargs["allow_redirects"] is False


def test_email_empty_allowlist_sends_nothing():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, {**EMAIL_ENV, "EMAIL_ALLOWED_RECIPIENTS": ""}), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com", "hi") is False
    cls.assert_not_called()


def test_email_unlisted_recipient_blocked():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("stranger@evil.com", "hi") is False
    cls.assert_not_called()


def test_email_header_injection_and_multiple_recipients_blocked():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com\nBcc: x@evil.com", "hi") is False
        assert a.send_email("boss@acme.com,x@evil.com", "hi") is False
    cls.assert_not_called()


def test_email_allowed_address_sends():
    cls, smtp = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com", "Hello body") is True
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    msg = smtp.send_message.call_args.args[0]
    assert msg["To"] == "boss@acme.com" and msg["From"] == "bot@example.com"


def test_email_domain_allowlist_is_exact_domain():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("anyone@partner.com", "hi") is True
        assert a.send_email("x@notpartner.com", "hi") is False
        assert a.send_email("x@sub.partner.com", "hi") is False


def test_email_subject_line_convention():
    cls, smtp = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        a.send_email("boss@acme.com", "Subject: Order shipped\n\nYour order left.")
        a.send_email("boss@acme.com", "no subject line here")
    first, second = [c.args[0] for c in smtp.send_message.call_args_list]
    assert first["Subject"] == "Order shipped" and "Your order left." in first.get_content()
    assert second["Subject"] == "Message from RagLeap"


def test_email_smtp_failure_returns_false():
    cls, smtp = _smtp()
    smtp.send_message.side_effect = Exception("smtp down")
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com", "hi") is False


def test_autonomy_dispatch_reports_sent_or_failed_for_new_channels():
    for channel, fn, target in (("webhook", "send_webhook", "n8n"), ("slack", "send_slack", "x"),
                                ("email", "send_email", "boss@acme.com")):
        with patch.object(a, fn, return_value=True):
            assert "sent" in autonomy._send_via_channel(channel, target, "hi")
        with patch.object(a, fn, return_value=False):
            out = autonomy._send_via_channel(channel, target, "hi")
            assert "failed" in out and "sent" not in out


def test_autonomy_unknown_channel_still_unsupported():
    assert "Unsupported channel" in autonomy._send_via_channel("carrier_pigeon", "x", "hi")


def test_plain_address_rules():
    ok = ["boss@acme.com", "a.b+c@sub.example.co.uk"]
    bad = ["a@b", "@x.com", "x@", "a@@b.com", "a@b..com", "a@.com", "a@b.com.", "a b@x.com",
           "a@b.com\nBcc: x@y.com", "a@b.com,c@d.com", "a@b.com;c@d.com", "<a@b.com>", "ü@b.com", ""]
    for addr in ok:
        assert a._is_plain_address(addr), addr
    for addr in bad:
        assert not a._is_plain_address(addr), addr


def test_pathological_address_is_rejected_fast_and_length_capped():
    import time
    for evil in ("!@!." + "!." * 5000, "a" * 100000 + "@x.com", "a@" + "b." * 100000):
        t0 = time.monotonic()
        assert a._is_plain_address(evil) is False
        assert time.monotonic() - t0 < 0.5


# ---- HubSpot CRM record-update action ----------------------------------------
# Every literal below is driven (hardcoded), never read back from the subject
# module's constants; the fake HTTP layer fails on any request it does not
# model. Red-first: on a pre-feature main every test below fails by ASSERTION
# (never ImportError/NameError/AttributeError) because each one asserts the
# missing surface - the sender, the tool mapping, the OUTBOUND_TOOLS entry -
# before exercising the behaviour to come.

from core.employees import actions as actions_module

CRM_ENV = {
    "HUBSPOT_ACCESS_TOKEN": "your-hubspot-private-app-token",
    "HUBSPOT_CRM_UPDATE_OBJECTS": "contacts,companies",
    "HUBSPOT_CRM_UPDATE_PROPERTIES": "firstname,lastname,prénom",
}
CRM_CONTENT = (
    "Object: contacts\n"
    "Id: 715559271\n"
    "Set: firstname = Jane\n"
    "Set: lastname = Doe-Xq7\n"
)
# The model-supplied target is never the destination (the HubSpot account is
# env configuration); a distinctive value proves it never reaches the URL.
MODEL_TARGET = "attacker-chosen-record-id"


class _ForbiddenCRMVerb:
    """Tripwire for the HTTP verbs a record update must never use: a create or
    merge is a POST, an archive is a DELETE, an upsert-flavoured client might
    PUT or go through the generic request(). Records the attempt (so a test
    can assert on it even where the sender swallows exceptions) and then fails
    the run loudly."""

    def __init__(self, verb):
        self.verb = verb
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        raise AssertionError(
            f"CRM update made a {self.verb} request - only the modeled PATCH is allowed")


class _FakeHubSpotHTTP:
    """Fake HTTP layer for the CRM sender. It models EXACTLY one request - the
    properties PATCH for the one allowlisted record on the configured account -
    and FAILS the run on any other request: a stub that accepts an unmodeled
    command agrees with anything, so it would prove nothing."""

    PATCH_URL = "https://api.hubapi.com/crm/v3/objects/contacts/715559271"

    def __init__(self, patch_status=200, patch_body="example-hubspot-error-body"):
        self.patch_status = patch_status
        self.patch_body = patch_body
        self.calls = []
        self.forbidden = {v: _ForbiddenCRMVerb(v)
                          for v in ("post", "put", "delete", "request")}

    def __call__(self, url, json=None, data=None, timeout=None,
                 allow_redirects=None, headers=None):
        self.calls.append({"url": url, "json": json,
                           "headers": dict(headers or {})})
        if allow_redirects is not False or timeout != 15:
            # Mutation: dropping the no-redirect / timeout contract.
            raise AssertionError(f"request without the sender contract: {url}")
        if url == self.PATCH_URL and data is None and isinstance(json, dict):
            if (headers or {}).get("Authorization") != f"Bearer {CRM_ENV['HUBSPOT_ACCESS_TOKEN']}":
                # Mutation: the token swapped for another credential or target.
                raise AssertionError("PATCH did not carry the configured HubSpot token")
            resp = MagicMock(status_code=self.patch_status)
            resp.text = self.patch_body  # a distinctive body the log test can hunt for
            return resp
        raise AssertionError(f"unmodeled request: {url}")

    def assert_not_called(self):
        assert not self.calls, f"unexpected request(s): {[c['url'] for c in self.calls]}"

    def assert_no_forbidden_writes(self):
        """No create, merge, archive or upsert-shaped request of any verb."""
        for verb, trip in self.forbidden.items():
            assert not trip.calls, f"unexpected {verb} request"


def _send_crm(target, content, env="default", status=200, patch_side_effect=None):
    """One CRM update through the sender with the whole HTTP layer replaced:
    requests.patch is answered by the fake modeling exactly the one allowlisted
    PATCH, and post/put/delete/request are tripwires. env="default" installs
    the full CRM configuration; any other value replaces the environment
    wholesale ({} = nothing configured). Returns (ok, http). Asserts the
    sender exists first, so a red run on a pre-feature main fails by
    assertion instead of AttributeError."""
    sender = getattr(a, "send_crm_update", None)
    assert callable(sender), "send_crm_update missing from core.action_senders"
    http = _FakeHubSpotHTTP(patch_status=status)
    patcher = patch.object(a.requests, "patch", http)
    if patch_side_effect is not None:
        patcher = patch.object(a.requests, "patch", side_effect=patch_side_effect)
    environment = CRM_ENV if env == "default" else env
    with patch.dict(os.environ, environment, clear=True), \
         patcher, \
         patch.object(a.requests, "post", http.forbidden["post"]), \
         patch.object(a.requests, "put", http.forbidden["put"]), \
         patch.object(a.requests, "delete", http.forbidden["delete"]), \
         patch.object(a.requests, "request", http.forbidden["request"]):
        return sender(target, content), http


def test_crm_action_wired_into_the_action_surface():
    # RED on a pre-feature main: ACTION_TOOLS has no such tool, .get answers {}.
    assert actions_module.ACTION_TOOLS.get("update_crm_record", {}).get("channel") == "crm"


def test_crm_is_an_outbound_tool_for_the_taint_rule():
    from core import agent_loop
    # RED on a pre-feature main. Dropping update_crm_record here would let a
    # run that just read untrusted web/MCP content write CRM properties
    # without owner approval even in full mode (agent_loop's force_semi rule).
    assert "update_crm_record" in agent_loop.OUTBOUND_TOOLS


def test_crm_unconfigured_refuses_without_request():
    # Default-deny: with nothing configured nothing is written and no request
    # of any kind is made.
    ok, http = _send_crm(MODEL_TARGET, CRM_CONTENT, env={})
    assert ok is False
    http.assert_not_called()
    http.assert_no_forbidden_writes()


def test_crm_malformed_content_refused_before_any_request():
    # Mutation: network before validation. Each case is refused with zero
    # requests of any kind. Table carries the required-field refusals (missing
    # Object/Id/Set, empty required value), the record-id shape refusals
    # (non-numeric, over 19 digits), the Set-line refusals (no ' = '
    # separator, empty property name, empty value), an unknown key, duplicated
    # keys, and the oversized-value refusal (over 1000 chars).
    bad_contents = (
        "",
        "Object: contacts",
        "Id: 715559271",
        "Object:\nId: 715559271",
        "Object: contacts\nId:",
        "Object: contacts\nId: 715559271",
        "Object: contacts\nId: 71a559\nSet: firstname = Jane",
        "Object: contacts\nId: " + "9" * 20 + "\nSet: firstname = Jane",
        "Object: contacts\nId: 715559271\nSet: firstname",
        "Object: contacts\nId: 715559271\nSet:  = Jane",
        "Object: contacts\nId: 715559271\nSet: firstname = ",
        "Summary: x\nObject: contacts\nId: 715559271\nSet: firstname = Jane",
        "Object: contacts\nObject: companies\nId: 715559271\nSet: firstname = Jane",
        "Object: contacts\nId: 715559271\nId: 715559272\nSet: firstname = Jane",
        "Object: contacts\nId: 715559271\nSet: firstname = A\nSet: firstname = B",  # duplicate Set property: refused, never last-value-wins
        "Object: contacts\nId: 715559271\nSet: firstname = " + "x" * 1001,
    )
    for content in bad_contents:
        ok, http = _send_crm("", content)
        assert ok is False, content
        http.assert_not_called()
        http.assert_no_forbidden_writes()


def test_crm_allowlist_refusals_happen_before_any_request():
    # Objects and properties outside the operator's allowlists refuse the
    # whole update with ZERO modeled requests: refusal happens before network.
    # One bad property among good ones refuses the whole update - nothing
    # partial is ever written.
    for content in (
        "Object: deals\nId: 715559271\nSet: firstname = Jane",
        "Object: contacts\nId: 715559271\nSet: jobtitle = Jane",
        "Object: contacts\nId: 715559271\nSet: firstname = Jane\nSet: jobtitle = X",
    ):
        ok, http = _send_crm("", content)
        assert ok is False, content
        http.assert_not_called()
        http.assert_no_forbidden_writes()


def test_crm_allowlist_is_exact_match_fixed_point_breakers():
    # The allowlists are EXACT-match tables. Every member below is a
    # fixed-point-breaking variant of an allowlisted entry - case-folded,
    # whitespace-wrapped, NFC/NFKC-decomposed or look-alike Unicode - and must
    # refuse the whole update, never be silently normalized onto the
    # allowlisted name.
    breakers = (
        "Object: Contacts\nId: 715559271\nSet: firstname = Jane",   # case-folded object
        "Object: contacts \nId: 715559271\nSet: firstname = Jane",  # wrapped object
        "Object: contacts\nId: 715559271 \nSet: firstname = Jane",  # wrapped id
        "Object: contacts\nId: 715559271\nSet: Firstname = Jane",   # case-folded property
        "Object: contacts\nId: 715559271\nSet:  firstname = Jane",  # property, extra leading space
        "Object: contacts\nId: 715559271\nSet: firstname  = Jane",  # property, extra inner space
        "Object: contacts\nId: 715559271\nSet: ﬁrstname = Jane",  # ﬁ ligature look-alike
        "Object: contacts\nId: 715559271\nSet: laѕtname = Jane",  # Cyrillic ѕ look-alike
        "Object: contacts\nId: 715559271\nSet: prénom = X",   # NFD of the NFC allowlist entry
    )
    for content in breakers:
        ok, http = _send_crm("", content)
        assert ok is False, content
        http.assert_not_called()
        http.assert_no_forbidden_writes()


def test_crm_allowlisted_unicode_name_agrees_exactly():
    # The agreement side of the exact-match table: the allowlisted NFC form
    # itself must pass, so the check is not a refuser-of-everything.
    ok, http = _send_crm("", "Object: contacts\nId: 715559271\nSet: prénom = Amélie")
    assert ok is True
    assert http.calls[0]["json"]["properties"]["prénom"] == "Amélie"


def test_crm_success_sends_exact_modeled_patch():
    ok, http = _send_crm("", CRM_CONTENT)
    assert ok is True
    assert len(http.calls) == 1
    http.assert_no_forbidden_writes()
    call = http.calls[0]
    assert call["url"] == _FakeHubSpotHTTP.PATCH_URL
    assert call["headers"]["Authorization"] == f"Bearer {CRM_ENV['HUBSPOT_ACCESS_TOKEN']}"
    # The record id travels in the URL, never as a body field; the body holds
    # only the allowlisted properties.
    assert call["json"] == {"properties": {"firstname": "Jane", "lastname": "Doe-Xq7"}}


def test_crm_model_target_is_never_the_destination():
    # The account and its token come from configuration; the model's target
    # never reaches the URL and is never required.
    ok, http = _send_crm(MODEL_TARGET, CRM_CONTENT)
    assert ok is True
    assert http.calls[0]["url"] == _FakeHubSpotHTTP.PATCH_URL
    assert MODEL_TARGET not in http.calls[0]["url"]


def test_crm_value_at_the_size_cap_still_sends():
    # The agreement side of the oversized-value refusal: a value exactly at
    # the 1000-char cap goes through untruncated.
    ok, http = _send_crm("", "Object: contacts\nId: 715559271\nSet: lastname = " + "x" * 1000)
    assert ok is True
    assert http.calls[0]["json"]["properties"]["lastname"] == "x" * 1000


def test_crm_not_found_fails_closed_and_never_upserts():
    # A not-found record is a FAILURE: the sender returns False and makes no
    # further request of any verb - an upsert (a create) is exactly the bug.
    ok, http = _send_crm("", CRM_CONTENT, status=404)
    assert ok is False
    assert len(http.calls) == 1
    http.assert_no_forbidden_writes()


def test_crm_http_errors_fail_closed_without_raising():
    # Mutation: the sender raising on a network error. The direct call must
    # return False, never raise.
    ok, http = _send_crm("", CRM_CONTENT, status=500)
    assert ok is False and len(http.calls) == 1
    sender = getattr(a, "send_crm_update", None)
    assert callable(sender), "send_crm_update missing from core.action_senders"
    with patch.dict(os.environ, CRM_ENV, clear=True), \
         patch.object(a.requests, "patch", side_effect=Exception("connection reset")):
        assert sender("", CRM_CONTENT) is False


def test_crm_secrets_never_hit_the_log(caplog):
    # Mutation: a token, a request body or a response body in a log line.
    # Distinct markers per surface; none may appear in any record under any
    # outcome (unconfigured refusal, not-found, server error).
    import logging
    with caplog.at_level(logging.DEBUG):
        _send_crm("", CRM_CONTENT, env={})
        _send_crm("", CRM_CONTENT, status=404)
        _send_crm("", CRM_CONTENT, status=500)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("your-hubspot-private-app-token", "Doe-Xq7", "Jane",
                   "example-hubspot-error-body"):
        assert secret not in text, secret


def test_crm_tool_offered_only_when_fully_configured():
    # Offered only with the token AND non-empty object and property
    # allowlists; anything missing keeps the tool absent (default-deny).
    with patch.dict(os.environ, dict(CRM_ENV), clear=True):
        assert "update_crm_record" in actions_module.available_tools()
    for missing in ("HUBSPOT_ACCESS_TOKEN", "HUBSPOT_CRM_UPDATE_OBJECTS",
                    "HUBSPOT_CRM_UPDATE_PROPERTIES"):
        env = dict(CRM_ENV)
        env[missing] = ""
        with patch.dict(os.environ, env, clear=True):
            # Mutation: gating off would offer the tool to unconfigured
            # deployments and change the default behaviour.
            assert "update_crm_record" not in actions_module.available_tools(), missing


def test_validate_plan_crm_update_never_lets_the_model_choose_target_or_bypass_the_allowlist():
    # The structure assertion comes first: on a pre-feature main this fails
    # HERE, by assertion, instead of walking into a KeyError below.
    assert actions_module.ACTION_TOOLS.get("update_crm_record", {}).get("channel") == "crm"
    tools = {"update_crm_record": "desc"}
    with patch.dict(os.environ, CRM_ENV, clear=True):
        plan = actions_module._validate_plan(
            {"tool": "update_crm_record", "target": MODEL_TARGET, "content": CRM_CONTENT}, tools)
        assert plan is not None
        assert plan["target"] == ""  # the model's target never survives validation
        assert plan["channel"] == "crm"
        for bad in (
            "",
            "Object: deals\nId: 715559271\nSet: firstname = Jane",
            "Object: contacts\nId: 715559271\nSet: jobtitle = Jane",
            "Object: contacts\nId: 715559271\nSet: firstname",
        ):
            assert actions_module._validate_plan(
                {"tool": "update_crm_record", "target": "", "content": bad}, tools) is None, bad


def test_autonomy_dispatch_updates_crm_record_end_to_end():
    # Route-level: the guard's inputs (env) are patched truthy so the dispatch
    # reaches a fully modeled sender. RED on a pre-feature main:
    # "Unsupported channel".
    sender = getattr(a, "send_crm_update", None)
    assert callable(sender), "send_crm_update missing from core.action_senders"
    http = _FakeHubSpotHTTP()
    with patch.dict(os.environ, CRM_ENV, clear=True), patch.object(a.requests, "patch", http):
        out = autonomy._send_via_channel("crm", MODEL_TARGET, CRM_CONTENT)
    assert "updated" in out and "failed" not in out
    assert len(http.calls) == 1


def test_autonomy_dispatch_reports_failed_for_crm():
    sender = getattr(a, "send_crm_update", None)
    assert callable(sender), "send_crm_update missing from core.action_senders"
    http = _FakeHubSpotHTTP(patch_status=404)
    with patch.dict(os.environ, CRM_ENV, clear=True), patch.object(a.requests, "patch", http):
        out = autonomy._send_via_channel("crm", "", CRM_CONTENT)
    assert "failed" in out and "updated" not in out


def test_autonomy_crm_dispatch_without_config_fails_closed():
    # Route-level with the guard answering before the code under test:
    # nothing configured means no write of any kind.
    sender = getattr(a, "send_crm_update", None)
    assert callable(sender), "send_crm_update missing from core.action_senders"
    http = _FakeHubSpotHTTP()
    with patch.dict(os.environ, {}, clear=True), patch.object(a.requests, "patch", http):
        out = autonomy._send_via_channel("crm", "", CRM_CONTENT)
    assert "failed" in out
    http.assert_not_called()
    http.assert_no_forbidden_writes()
