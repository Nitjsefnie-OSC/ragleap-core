"""Tests for core/action_senders.py: no network, DNS/HTTP/SMTP mocked."""
import os
import pytest
import sys
from unittest.mock import patch, MagicMock, PropertyMock

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


def _send_crm(target, content, env="default", status=200):
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
    environment = CRM_ENV if env == "default" else env
    with patch.dict(os.environ, environment, clear=True), \
         patch.object(a.requests, "patch", http), \
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


def test_crm_token_missing_with_allowlists_set_refuses_without_request():
    # The discriminating entry for the token limb at the sender layer: both
    # allowlists configured, the token blank. The config guard is the only
    # layer that refuses here - with it dropped, the sender would PATCH with
    # an empty bearer and only HubSpot's 401 would stop the write.
    env = dict(CRM_ENV)
    env["HUBSPOT_ACCESS_TOKEN"] = ""
    ok, http = _send_crm("", CRM_CONTENT, env=env)
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


def test_crm_allowlist_entries_may_carry_whitespace_in_config():
    # Operator config is stripped at the boundary (", " between entries is
    # normal writing); the model's input still matches verbatim. Kills the
    # entry-strip-dropped mutant: without the strip, " lastname" never
    # matches the parsed property name and the update would refuse.
    env = dict(CRM_ENV)
    env["HUBSPOT_CRM_UPDATE_OBJECTS"] = "contacts, companies"
    env["HUBSPOT_CRM_UPDATE_PROPERTIES"] = "firstname, lastname"
    ok, http = _send_crm("", CRM_CONTENT, env=env)
    assert ok is True
    assert http.calls[0]["json"]["properties"] == {"firstname": "Jane", "lastname": "Doe-Xq7"}


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


def test_crm_redirect_status_is_not_success():
    # The 2xx-only success contract pinned against the 3xx band: a 302 is a
    # failure, and nothing further is requested.
    ok, http = _send_crm("", CRM_CONTENT, status=302)
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


# The sender's failure log is a secret boundary: real requests client errors
# carry the configured token (in their message, args and request attribute),
# and requests itself raises InvalidHeader carrying the FULL header value when
# a header value holds an internal CR/LF (requests/utils.py
# _validate_header_part). Red-first: on a sender that logs the failed
# request's exception (`CRM update error: {e}`) every row below fails by
# ASSERTION, never by a raise out of the test.

def _leak_text(sentinel):
    """The payload a leaked CRM exception message carries: the row's sentinel,
    the configured token and the PATCH URL."""
    return (f"example-leaked-exception-detail-{sentinel} "
            f"token={CRM_ENV['HUBSPOT_ACCESS_TOKEN']} "
            f"url={_FakeHubSpotHTTP.PATCH_URL}")


def _request_with_token():
    """The PreparedRequest a real requests client error carries: the request
    that was attempted, its headers holding the configured bearer token."""
    request = a.requests.models.PreparedRequest()
    request.url = _FakeHubSpotHTTP.PATCH_URL
    request.headers = {"Authorization": f"Bearer {CRM_ENV['HUBSPOT_ACCESS_TOKEN']}"}
    return request


def _raise_chained(url, json=None, timeout=None, allow_redirects=None, headers=None):
    cause = ValueError(_leak_text("chained"))
    raise a.requests.exceptions.RequestException(_leak_text("chained")) from cause


def _raise_preparedrequest(url, json=None, timeout=None, allow_redirects=None,
                           headers=None):
    # A genuine requests exception without network: requests raising
    # InvalidHeader on the sender's OWN headers when the configured token
    # holds an internal CR/LF (one .strip() cannot remove).
    prepared = a.requests.models.PreparedRequest()
    prepared.prepare_headers(headers)


def _late_response_side_effect(url, json=None, timeout=None,
                               allow_redirects=None, headers=None):
    # A raise AFTER the HTTP call returns: the response's status_code access
    # itself blows up. Pins the generic handler for non-HTTP raise sites
    # inside the try, not only the request call failing. The PropertyMock
    # goes on this per-call MagicMock subclass, never on MagicMock itself.
    class _LateResponse(MagicMock):
        pass
    resp = _LateResponse()
    type(resp).status_code = PropertyMock(
        side_effect=RuntimeError(_leak_text("late")))
    return resp


_CRLF_TOKEN = ("your-hubspot-private-app-token\r\n"
               "X-Injected: example-leaked-exception-detail-preparedrequest")
_CRLF_TOKEN_ENV = dict(CRM_ENV, HUBSPOT_ACCESS_TOKEN=_CRLF_TOKEN)

_CRM_CLIENT_ERROR_ROWS = [
    # (sentinel, side-effect factory, env): every failure happens at the HTTP
    # call itself - config, parsing and the allowlists pass first, and each
    # row asserts the PATCH happened exactly once. A row whose guard refuses
    # before requests.patch would pass on broken code and prove nothing.
    pytest.param(
        "connection",
        lambda: a.requests.exceptions.ConnectionError(
            _leak_text("connection"), request=_request_with_token()),
        CRM_ENV,
        id="connection",
    ),
    pytest.param(
        "timeout",
        lambda: a.requests.exceptions.Timeout(
            _leak_text("timeout"), request=_request_with_token()),
        CRM_ENV,
        id="timeout",
    ),
    pytest.param(
        "invalidheader",
        lambda: a.requests.exceptions.InvalidHeader(
            _leak_text("invalidheader"), request=_request_with_token()),
        CRM_ENV,
        id="invalidheader",
    ),
    pytest.param(
        "requestexception",
        lambda: a.requests.exceptions.RequestException(
            _leak_text("requestexception"), request=_request_with_token()),
        CRM_ENV,
        id="requestexception",
    ),
    pytest.param(
        "plain",
        lambda: Exception(_leak_text("plain")),
        CRM_ENV,
        id="plain",
    ),
    pytest.param(
        "chained",
        lambda: _raise_chained,
        CRM_ENV,
        id="chained",
    ),
    pytest.param(
        "preparedrequest",
        lambda: _raise_preparedrequest,
        _CRLF_TOKEN_ENV,
        id="preparedrequest",
    ),
    pytest.param(
        "late",
        lambda: _late_response_side_effect,
        CRM_ENV,
        id="late",
    ),
]


@pytest.mark.parametrize("sentinel,side_effect_factory,env", _CRM_CLIENT_ERROR_ROWS)
def test_crm_client_exception_details_never_reach_the_log(caplog, sentinel,
                                                          side_effect_factory, env):
    # Mutation: the sender logging the failed request's exception - its
    # message, args or request attribute, or the whole traceback. Each row
    # fails at the HTTP call itself and must come back False without raising,
    # with the PATCH made exactly once, exactly one generic ERROR record, and
    # none of the token, the PATCH URL or the row's sentinel in any record's
    # message, exc_text or the formatted caplog output; no record may carry
    # exc_info or a stack.
    import logging
    sender = getattr(a, "send_crm_update", None)
    assert callable(sender), "send_crm_update missing from core.action_senders"
    with caplog.at_level(logging.DEBUG):
        errors = []
        ok = None
        with patch.dict(os.environ, env, clear=True), \
             patch.object(a.requests, "patch",
                          side_effect=side_effect_factory()) as patch_mock:
            try:
                ok = sender("", CRM_CONTENT)
            except Exception as caught:  # a raise is the failure; record it, don't raise
                errors.append(caught)
        # Fail closed, silently: False, no raise, the HTTP call happened.
        assert ok is False
        assert not errors, errors
        patch_mock.assert_called_once()
        records = caplog.records
        text = "\n".join(r.getMessage() for r in records)
        for leak in (CRM_ENV["HUBSPOT_ACCESS_TOKEN"], _FakeHubSpotHTTP.PATCH_URL,
                     f"example-leaked-exception-detail-{sentinel}"):
            assert leak not in text, leak
            assert leak not in caplog.text, leak
            for r in records:
                assert leak not in (r.exc_text or ""), leak
        for r in records:
            assert r.exc_info is None
            assert r.stack_info is None
        crm_records = [r for r in records if r.name == "core.action_senders"]
        assert len(crm_records) == 1
        assert crm_records[0].levelno == logging.ERROR
        # Exact: nothing derived from the exception may be appended to it.
        assert crm_records[0].getMessage() == (
            "CRM update request error - CRM update refused")


def test_crm_status_failure_logs_only_the_status_code(caplog):
    # Preservation pin: the status path keeps logging only the status code.
    # The mocked 500/404 responses carry the fake's default body
    # (example-hubspot-error-body), so a log line extended with the response
    # body dies here too; none of the token, the body or the request content
    # may reach the log. Green on the current code by design.
    import logging
    for status in (500, 404):
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            ok, http = _send_crm("", CRM_CONTENT, status=status)
        assert ok is False
        assert len(http.calls) == 1
        crm_records = [r for r in caplog.records if r.name == "core.action_senders"]
        assert len(crm_records) == 1
        assert crm_records[0].levelno == logging.ERROR
        assert crm_records[0].getMessage() == f"CRM update failed with status {status}"
        text = "\n".join(r.getMessage() for r in caplog.records)
        for secret in (CRM_ENV["HUBSPOT_ACCESS_TOKEN"], "example-hubspot-error-body",
                       "Jane", "Doe-Xq7"):
            assert secret not in text, secret
            assert secret not in caplog.text, secret
            for r in caplog.records:
                assert secret not in (r.exc_text or ""), secret


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
    http = _FakeHubSpotHTTP()
    with patch.dict(os.environ, CRM_ENV, clear=True), patch.object(a.requests, "patch", http):
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
        # Plan validation must make no network call of any kind: acceptance is
        # decided by parsing and the allowlists alone.
        assert http.calls == []
        http.assert_no_forbidden_writes()


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


# ---- calendar scheduling action ----------------------------------------
# Every literal below is driven (hardcoded), never read back from the
# subject module's constants; the fake HTTP layer fails on any request it
# does not model.

import json as _json

import pytest
import requests

from core.employees import actions as actions_module

CAL_ENV = {
    "GOOGLE_CALENDAR_ID": "owner-cal@example.com",
    "GOOGLE_CALENDAR_CLIENT_ID": "your-client-id.apps.googleusercontent.com",
    "GOOGLE_CALENDAR_CLIENT_SECRET": "your-client-secret",
    "GOOGLE_CALENDAR_REFRESH_TOKEN": "your-refresh-token",
    "EMAIL_ALLOWED_RECIPIENTS": "boss@acme.com,@partner.com",
}
CAL_CONTENT = (
    "Title: Quarterly review\n"
    "Start: 2026-11-03T14:00:00+00:00\n"
    "End: 2026-11-03T15:00:00+00:00\n"
    "Attendees: boss@acme.com, team@partner.com\n"
    "Description: Bring the Q4 plan"
)
# Distinct nonzero values on every side, so a swap in either direction is
# visible: the model-supplied target ("attacker-calendar-id") differs from
# the configured calendar id, and the access token the fake issues differs
# from every configured credential.
CAL_MODEL_TARGET = "attacker-calendar-id"
ACCESS_TOKEN = "sample-access-token"


class _FakeGoogleHTTP:
    """Fake HTTP layer for the calendar sender. It models EXACTLY two requests
    - the OAuth token exchange and the events.insert for the one configured
    calendar - and FAILS the run on any other request: a stub that accepts an
    unmodeled command agrees with anything, so it would prove nothing."""

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    INSERT_URL = (
        "https://www.googleapis.com/calendar/v3/calendars/"
        "owner-cal%40example.com/events?sendUpdates=all"
    )

    def __init__(self, token_status=200, token_body='{"access_token": "%s"}' % ACCESS_TOKEN,
                 insert_status=200, insert_body="example-insert-error-body",
                 token_raise=None, insert_raise=None):
        self.token_status = token_status
        self.token_body = token_body
        self.insert_status = insert_status
        self.insert_body = insert_body
        self.token_raise = token_raise
        self.insert_raise = insert_raise
        self.calls = []

    def __call__(self, url, json=None, data=None, timeout=None,
                 allow_redirects=None, headers=None):
        self.calls.append({"url": url, "json": json, "data": data,
                           "headers": dict(headers or {})})
        if allow_redirects is not False or timeout != 15:
            # Mutation: dropping the no-redirect / timeout contract.
            raise AssertionError(f"request without the sender contract: {url}")
        if url == self.TOKEN_URL and json is None and isinstance(data, dict):
            if data.get("grant_type") != "refresh_token":
                raise AssertionError(f"unmodeled token request body: {sorted(data)}")
            if (data.get("client_id") != CAL_ENV["GOOGLE_CALENDAR_CLIENT_ID"]
                    or data.get("client_secret") != CAL_ENV["GOOGLE_CALENDAR_CLIENT_SECRET"]
                    or data.get("refresh_token") != CAL_ENV["GOOGLE_CALENDAR_REFRESH_TOKEN"]):
                # Mutation: credential values swapped or replaced.
                raise AssertionError("token exchange did not use the configured credentials")
            if self.token_raise is not None:
                raise self.token_raise
            resp = MagicMock(status_code=self.token_status)
            resp.json.return_value = _json.loads(self.token_body)
            return resp
        if url == self.INSERT_URL and data is None and isinstance(json, dict):
            if headers.get("Authorization") != f"Bearer {ACCESS_TOKEN}":
                # Mutation: a token not issued by the fake being replayed.
                raise AssertionError("insert did not carry the fake-issued access token")
            if self.insert_raise is not None:
                raise self.insert_raise
            resp = MagicMock(status_code=self.insert_status)
            resp.text = self.insert_body  # a distinctive body the log test can hunt for
            return resp
        raise AssertionError(f"unmodeled request: {url}")


def _send_calendar(target, content, env=None, http=None):
    """One calendar send through the sender, with the HTTP layer replaced.
    Env defaults to the full calendar configuration; pass {} for none."""
    with patch.dict(os.environ, CAL_ENV if env is None else env), \
         patch.object(a.requests, "post", http or _FakeGoogleHTTP()):
        return a.send_calendar_event(target, content)


def test_calendar_action_wired_into_the_action_surface():
    # Mutation: the tool never mapping to the calendar channel would leave
    # the action unplannable even with the sender present.
    assert actions_module.ACTION_TOOLS.get("schedule_event", {}).get("channel") == "calendar"


def test_calendar_is_an_outbound_tool_for_the_taint_rule():
    from core import agent_loop
    # Mutation: dropping schedule_event here would let a run that just read
    # untrusted web/MCP content create a calendar event without owner
    # approval even in full mode (agent_loop's force_semi taint rule).
    assert "schedule_event" in agent_loop.OUTBOUND_TOOLS


def test_calendar_unconfigured_refuses_without_request():
    # Defaults byte-identical: with nothing configured nothing happens.
    http = MagicMock()
    ok = _send_calendar(CAL_MODEL_TARGET, CAL_CONTENT, env={}, http=http)
    assert ok is False
    http.assert_not_called()  # no write of any kind, not a checked subset


def test_calendar_malformed_content_refused_before_any_request():
    # Mutation: network before validation. Each case is refused with zero
    # requests of any kind.
    bad_contents = (
        "",
        "Title: X",
        "Start: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00",
        "Title: X\nStart: next tuesday\nEnd: 2026-11-03T15:00:00+00:00",
        "Title: X\nStart: 2026-11-03T14:00:00\nEnd: 2026-11-03T15:00:00",  # naive: no offset
        "Title: X\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T14:00:00+00:00",
        "Title: X\nStart: 2026-11-03T15:00:00+00:00\nEnd: 2026-11-03T14:00:00+00:00",
        "Summary: X\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00",
        "Title: X\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00\n"
        "Attendees: stranger@evil.com",  # screening happens with no network too
        "Title: X\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00\n"
        "Attendees: boss@acme.com\nAttendees: team@acme.com",  # duplicate field: refused
        "Title: X\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00\n"
        "Attendees:\nAttendees: boss@acme.com",  # duplicate after an empty first value: refused too
        "Title:\nTitle: Real\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00",
        # duplicate Title after an empty first value: refused too
    )
    for content in bad_contents:
        http = MagicMock()
        ok = _send_calendar("", content, http=http)
        assert ok is False, content
        http.assert_not_called()


def test_calendar_sends_exact_modeled_requests():
    http = _FakeGoogleHTTP()
    ok = _send_calendar("", CAL_CONTENT, http=http)
    assert ok is True
    token_call, insert_call = http.calls[0], http.calls[1]
    assert token_call["url"] == "https://oauth2.googleapis.com/token"
    assert insert_call["url"] == (
        "https://www.googleapis.com/calendar/v3/calendars/"
        "owner-cal%40example.com/events?sendUpdates=all"
    )
    assert insert_call["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    body = insert_call["json"]
    assert body["summary"] == "Quarterly review"
    assert body["start"] == {"dateTime": "2026-11-03T14:00:00+00:00"}
    assert body["end"] == {"dateTime": "2026-11-03T15:00:00+00:00"}
    assert body["attendees"] == [{"email": "boss@acme.com"}, {"email": "team@partner.com"}]
    assert body["description"] == "Bring the Q4 plan"


def test_calendar_model_target_never_chooses_the_destination():
    # Mutation (a): the calendar id taken from the model's target. The fake
    # only models the CONFIGURED calendar's URL, so a target-chosen calendar
    # makes the send fail and this assertion go red.
    http = _FakeGoogleHTTP()
    ok = _send_calendar(CAL_MODEL_TARGET, CAL_CONTENT, http=http)
    assert ok is True
    assert http.calls[1]["url"] == _FakeGoogleHTTP.INSERT_URL
    assert CAL_MODEL_TARGET not in http.calls[1]["url"]


def test_calendar_no_attendees_still_schedules_without_attendee_field():
    http = _FakeGoogleHTTP()
    content = ("Title: Focus block\n"
               "Start: 2026-11-04T09:00:00+00:00\n"
               "End: 2026-11-04T10:00:00+00:00")
    assert _send_calendar("", content, http=http) is True
    assert "attendees" not in http.calls[1]["json"]


def test_calendar_screening_passes_case_and_whitespace_variants():
    # The agreement side of the screening table: near-miss lookalikes that
    # MUST pass, so the check is not a refuser-of-everything.
    http = _FakeGoogleHTTP()
    content = ("Title: Sync\n"
               "Start: 2026-11-05T10:00:00+00:00\n"
               "End: 2026-11-05T11:00:00+00:00\n"
               "Attendees: BOSS@ACME.COM , team@partner.com")
    assert _send_calendar("", content, http=http) is True
    assert http.calls[1]["json"]["attendees"] == [
        {"email": "BOSS@ACME.COM"}, {"email": "team@partner.com"}]


def test_calendar_disallowed_attendee_refuses_whole_event():
    # Mutations (b) allowlist check skipped and (c) one bad attendee dropped:
    # one allowed + one disallowed attendee must refuse the WHOLE event, with
    # no write of any kind - nobody is dropped, nothing partially sends.
    http = MagicMock()
    content = ("Title: Leak\n"
               "Start: 2026-11-03T14:00:00+00:00\n"
               "End: 2026-11-03T15:00:00+00:00\n"
               "Attendees: boss@acme.com, stranger@evil.com")
    assert _send_calendar("", content, http=http) is False
    http.assert_not_called()


def test_calendar_attendee_screening_fixed_point_breakers():
    # Members a naive checker would accept but that must each refuse the
    # event: ; -smuggled second address, @domain suffix lookalikes against
    # the @partner.com entry, comma smuggle, newline smuggling, angle
    # brackets, trailing whitespace inside the address.
    breakers = (
        "boss@acme.com ;x@evil.com",
        "x@notpartner.com",
        "x@sub.partner.com",
        "boss@acme.com,x@evil.com",
        "boss@acme.com\nx@evil.com",
        "<boss@acme.com>",
        " stranger@evil.com ",
    )
    for attendee in breakers:
        http = MagicMock()
        content = (f"Title: T\nStart: 2026-11-03T14:00:00+00:00\n"
                   f"End: 2026-11-03T15:00:00+00:00\nAttendees: {attendee}")
        assert _send_calendar("", content, http=http) is False, attendee
        http.assert_not_called()


def test_calendar_google_errors_fail_closed_without_raising():
    # Mutation (d): the sender raising on a network error. The direct call
    # must return False, never raise.
    token_401 = _FakeGoogleHTTP(
        token_status=401, token_body='{"error": "example-invalid-grant-body"}')
    assert _send_calendar("", CAL_CONTENT, http=token_401) is False
    assert len(token_401.calls) == 1  # refused before any insert attempt

    insert_500 = _FakeGoogleHTTP(insert_status=500)
    assert _send_calendar("", CAL_CONTENT, http=insert_500) is False
    assert len(insert_500.calls) == 2

    with patch.dict(os.environ, CAL_ENV), \
         patch.object(a.requests, "post", side_effect=Exception("connection reset")):
        assert a.send_calendar_event("", CAL_CONTENT) is False


def test_calendar_secrets_never_hit_the_log(caplog):
    # Mutation (e): a token or response body in a log line. Distinct markers
    # per surface; none may appear in any record under any failure.
    import logging
    with caplog.at_level(logging.DEBUG):
        _send_calendar("", CAL_CONTENT, http=_FakeGoogleHTTP(
            token_status=401, token_body='{"error": "example-token-endpoint-body"}'))
        _send_calendar("", CAL_CONTENT, http=_FakeGoogleHTTP(insert_status=500))
        _send_calendar("", CAL_CONTENT, http=_FakeGoogleHTTP(
            token_body='{"warning": "example-no-token-body"}'))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (ACCESS_TOKEN, "your-refresh-token", "your-client-secret",
                   "example-token-endpoint-body", "example-no-token-body",
                   "example-insert-error-body"):
        assert secret not in text, secret


def _leak_marker(stage, kind):
    """A distinct request-detail-shaped marker per (stage, exception-kind):
    a URL with a query string and a bearer-looking value."""
    return (f"https://calendar.example.invalid/events?cal=demo-{stage}"
            f"&bearer=example-{kind}-leak")


def _calendar_raise_cases():
    cases = []
    for stage in ("token", "insert"):
        for kind in ("Exception", "ConnectionError", "Timeout", "HTTPError"):
            marker = _leak_marker(stage, kind)
            if kind == "Exception":
                exc = Exception(marker)
            else:
                exc = getattr(requests.exceptions, kind)(marker)
            cases.append(pytest.param(stage, kind, exc, id=f"{stage}-{kind}"))
    return cases


@pytest.mark.parametrize("stage,kind,exc", _calendar_raise_cases())
def test_calendar_http_exception_text_never_reaches_the_log(caplog, stage, kind, exc):
    # Mutation: the catch-all logging exception text (`Calendar event error:
    # {e}`). The marker the exception carries must appear nowhere on the whole
    # log surface; the sender stays fail-closed with one generic ERROR record.
    import logging
    marker = str(exc)
    http = _FakeGoogleHTTP(**{f"{stage}_raise": exc})
    with caplog.at_level(logging.DEBUG):
        assert _send_calendar("", CAL_CONTENT, http=http) is False
    assert marker not in caplog.text  # formatted handler output incl. tracebacks
    for record in caplog.records:
        assert marker not in record.getMessage(), marker
        for arg in (record.args or ()):
            assert marker not in str(arg)
        assert record.exc_info is None
    assert kind not in caplog.text
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
    assert len(http.calls) == (1 if stage == "token" else 2)


def test_calendar_http_exception_log_message_is_constant_across_exceptions(caplog):
    # Mutation: the catch-all interpolating anything exception-derived. Two
    # different exceptions on the same stage must produce byte-identical
    # ERROR messages, or the log is a channel for request detail.
    import logging
    with caplog.at_level(logging.DEBUG):
        for stage in ("token", "insert"):
            messages = []
            for marker in ("https://calendar.example.invalid/?q=example-first-leak",
                           "https://calendar.example.invalid/?q=demo-second-leak"):
                exc = requests.exceptions.ConnectionError(marker)
                http = _FakeGoogleHTTP(**{f"{stage}_raise": exc})
                before = len(caplog.records)
                assert _send_calendar("", CAL_CONTENT, http=http) is False
                errors = [r for r in caplog.records[before:]
                          if r.levelno == logging.ERROR]
                assert len(errors) == 1
                messages.append(errors[0].getMessage())
            assert messages[0] == messages[1]


def test_calendar_status_code_logging_is_untouched(caplog):
    # Mutation: a later log-hygiene change also touching the status-code-only
    # lines. Those carry no exception detail and must stay byte-identical.
    import logging
    with caplog.at_level(logging.DEBUG):
        assert _send_calendar("", CAL_CONTENT, http=_FakeGoogleHTTP(
            token_status=401,
            token_body='{"error": "example-token-status-body"}')) is False
        assert _send_calendar("", CAL_CONTENT,
                              http=_FakeGoogleHTTP(insert_status=500)) is False
    messages = [r.getMessage() for r in caplog.records]
    assert "Google token exchange failed with status 401" in messages
    assert "Calendar insert failed with status 500" in messages


def test_calendar_tool_offered_only_when_fully_configured():
    from core.employees import actions as actions_mod
    with patch.dict(os.environ, dict(CAL_ENV), clear=True):
        assert "schedule_event" in actions_mod.available_tools()
        for missing in ("GOOGLE_CALENDAR_ID", "GOOGLE_CALENDAR_CLIENT_ID",
                        "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REFRESH_TOKEN"):
            env = dict(CAL_ENV)
            env[missing] = ""
            with patch.dict(os.environ, env, clear=True):
                # Mutation: gating off would offer the tool to unconfigured
                # deployments and change the default behaviour.
                assert "schedule_event" not in actions_mod.available_tools(), missing


def test_validate_plan_calendar_requires_valid_content_and_never_a_target():
    tools = {"schedule_event": "desc"}
    with patch.dict(os.environ, CAL_ENV):
        plan = actions_module._validate_plan(
            {"tool": "schedule_event", "target": CAL_MODEL_TARGET, "content": CAL_CONTENT}, tools)
        assert plan is not None
        assert plan["target"] == ""  # the model's target never survives validation
        assert plan["channel"] == "calendar"
        for bad in ("", "Title: X",
                    "Title: X\nStart: 2026-11-03T14:00:00+00:00",
                    "Title: X\nStart: 2026-11-03T15:00:00+00:00\nEnd: 2026-11-03T14:00:00+00:00",
                    "Title: X\nStart: 2026-11-03T14:00:00+00:00\nEnd: 2026-11-03T15:00:00+00:00\n"
                    "Attendees: stranger@evil.com"):
            assert actions_module._validate_plan(
                {"tool": "schedule_event", "target": "", "content": bad}, tools) is None, bad


def test_autonomy_dispatch_schedules_calendar_event_end_to_end():
    # Route-level: the guard's input (env) is patched truthy so the dispatch
    # reaches a fully modeled sender. RED on BASE: "Unsupported channel".
    http = _FakeGoogleHTTP()
    with patch.dict(os.environ, CAL_ENV), patch.object(a.requests, "post", http):
        out = autonomy._send_via_channel("calendar", CAL_MODEL_TARGET, CAL_CONTENT)
    assert out == "Calendar event: scheduled"
    assert len(http.calls) == 2


def test_autonomy_dispatch_reports_failed_for_calendar():
    # The distinct failure side: a non-2xx insert reports failed, not sent.
    http = _FakeGoogleHTTP(insert_status=500)
    with patch.dict(os.environ, CAL_ENV), patch.object(a.requests, "post", http):
        out = autonomy._send_via_channel("calendar", "", CAL_CONTENT)
    assert out == "Calendar event: failed"
    assert "scheduled" not in out and "sent" not in out


def test_autonomy_calendar_dispatch_without_config_fails_closed():
    # Route-level with the guard answering before the code under test:
    # nothing configured means no write of any kind.
    http = MagicMock()
    with patch.dict(os.environ, {}, clear=True), patch.object(a.requests, "post", http):
        out = autonomy._send_via_channel("calendar", "", CAL_CONTENT)
    assert out == "Calendar event: failed"
    http.assert_not_called()
