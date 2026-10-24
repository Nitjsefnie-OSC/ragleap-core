"""
Tests for the Meta WhatsApp Cloud API provider (WHATSAPP_PROVIDER=meta).

Offline only: the Graph API is stubbed at the router's requests.post boundary,
and the /webhook/whatsapp handlers are called directly with fake Requests
(the same route-by-path lookup tests/test_approval_sender.py uses), so no test
touches the network.

The boundary doubles refuse what they do not model (a form() read on the JSON
request, a non-Graph URL, unexpected keyword arguments), so an unmodelled call
fails loudly instead of passing silently.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.api import app
from channels.whatsapp import router as wa


APP_SECRET = "example-meta-app-secret"
VERIFY_TOKEN = "example-verify-token"

# A representative Meta `messages` webhook payload: one text message from
# wa_id 15551234567. Kept byte-stable so the fixed signature vector below
# (and every signed-POST test) signs exactly these bytes.
TEST_BODY = json.dumps({
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15550001111", "phone_number_id": "111222333"},
                "contacts": [{"profile": {"name": "Test User"}, "wa_id": "15551234567"}],
                "messages": [{"from": "15551234567", "id": "wamid.TESTMSG001", "timestamp": "1730000000",
                              "type": "text", "text": {"body": "hello from Meta"}}],
            },
        }],
    }],
}).encode("utf-8")

# Fixed vector pinning the documented scheme: "sha256=" + hex HMAC-SHA256 of
# the raw request body with the Meta app secret. Computed once with the same
# APP_SECRET/TEST_BODY pair above; if the implementation ever signs with
# another algorithm, another input, or another secret, this fails.
EXPECTED_SIGNATURE = "sha256=4006c2586cb92e27ca76904e5975f935e49b3f1d63331537cd14cbaeda6a78c1"


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _meta_config(**overrides):
    """
    Nested patch context for the router's module-level Meta config, mirroring
    how tests/test_approval_sender.py and tests/test_api_key_auth.py patch
    module attributes that re-read the environment at import time.
    """
    stack = ExitStack()
    stack.enter_context(patch.object(wa, "WHATSAPP_PROVIDER", "meta"))
    stack.enter_context(patch.object(wa, "META_APP_SECRET", overrides.get("META_APP_SECRET", APP_SECRET)))
    stack.enter_context(patch.object(wa, "META_VERIFY_TOKEN", overrides.get("META_VERIFY_TOKEN", VERIFY_TOKEN)))
    stack.enter_context(patch.object(wa, "META_ACCESS_TOKEN", overrides.get("META_ACCESS_TOKEN", "EAAG-test-access-token")))
    stack.enter_context(patch.object(wa, "META_PHONE_NUMBER_ID", overrides.get("META_PHONE_NUMBER_ID", "111222333")))
    return stack


class _MetaJsonRequest:
    """
    Fake Request modelling a Meta webhook POST: raw body + headers only.
    form() refuses loudly -- the Meta branch must never parse form fields.
    """
    def __init__(self, body, headers):
        self._body = body
        self.headers = headers
        self.query_params = {}

    async def body(self):
        return self._body

    async def json(self):
        return json.loads(self._body)

    def form(self):
        raise AssertionError("form() called on a Meta JSON webhook request")


class _MetaAndTwilioRequest(_MetaJsonRequest):
    """Same JSON request, but also models a Twilio-shaped form() for the
    provider-routing test, which walks into the Twilio branch on purpose."""
    async def form(self):
        return {"Body": "hello from Meta", "From": "whatsapp:+15551234567"}


class _MetaVerifyRequest:
    """Fake Request modelling Meta's webhook-verification GET (query params only)."""
    def __init__(self, query):
        self.query_params = query
        self.headers = {}

    async def body(self):
        raise AssertionError("body() called on a webhook verification GET")


class _GraphPost:
    """
    Offline double for the router's requests.post boundary. Models exactly one
    call shape -- POST to a graph.facebook.com URL with headers/json/timeout
    keywords -- and fails loudly on anything else, so an unmodelled call can
    never pass silently.
    """
    def __init__(self, status_code=200, text='{"error": {"message": "boom"}}', reason="Bad Request"):
        self.status_code = status_code
        self.text = text
        self.reason = reason
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not url.startswith("https://graph.facebook.com/"):
            raise AssertionError(f"Graph double only models graph.facebook.com, got {url!r}")
        if set(kwargs) != {"headers", "json", "timeout"}:
            raise AssertionError(f"Graph double models headers/json/timeout only, got {sorted(kwargs)}")
        return self


def _route(method):
    return next(r.endpoint for r in app.routes
                if getattr(r, "path", "") == "/webhook/whatsapp" and method in getattr(r, "methods", set()))


def _call_post(headers=None, body=TEST_BODY, request_class=_MetaJsonRequest):
    return asyncio.run(_route("POST")(request_class(body, headers or {})))


def _call_get(query):
    return asyncio.run(_route("GET")(_MetaVerifyRequest(query)))


# Credentials carrying one character a str compare_digest refuses: a latin-1
# byte, a non-latin-1 BMP character, an astral (emoji) character, a lone surrogate.
NON_ASCII_CREDENTIALS = [
    pytest.param("\xff", id="latin1"),
    pytest.param("中", id="bmp"),
    pytest.param("\U0001f600", id="astral"),
    pytest.param("\udcff", id="surrogate"),
]


# --- sending path -----------------------------------------------------------

def test_send_whatsapp_message_dispatches_by_provider():
    with patch.object(wa, "_send_via_twilio") as twilio, \
         patch.object(wa, "_send_via_gupshup") as gupshup, \
         patch.object(wa, "_send_via_meta") as meta:
        for provider, target in (("twilio", twilio), ("gupshup", gupshup), ("meta", meta)):
            target.return_value = True
            with patch.object(wa, "WHATSAPP_PROVIDER", provider):
                assert wa.send_whatsapp_message("+15551234567", "hi there") is True
    twilio.assert_called_once_with("+15551234567", "hi there")
    gupshup.assert_called_once_with("+15551234567", "hi there")
    meta.assert_called_once_with("+15551234567", "hi there")


def test_send_via_meta_posts_to_graph_messages_url_with_bearer_token():
    post = _GraphPost(status_code=200)
    with _meta_config(), patch.object(wa.requests, "post", post):
        assert wa._send_via_meta("whatsapp:+15551234567", "hello there") is True

    assert len(post.calls) == 1
    call = post.calls[0]
    assert call["url"] == "https://graph.facebook.com/v24.0/111222333/messages"
    assert call["headers"]["Authorization"] == "Bearer EAAG-test-access-token"
    assert call["json"] == {
        "messaging_product": "whatsapp",
        "to": "15551234567",
        "type": "text",
        "text": {"preview_url": False, "body": "hello there"},
    }
    assert call["timeout"] == 30


def test_send_via_meta_strips_the_whatsapp_prefix_from_numbers():
    post = _GraphPost(status_code=200)
    with _meta_config(), patch.object(wa.requests, "post", post):
        wa._send_via_meta("+15551234567", "hello there")
    assert post.calls[0]["json"]["to"] == "15551234567"


def test_send_via_meta_without_credentials_fails_without_a_request():
    post = _GraphPost(status_code=200)
    with _meta_config(META_ACCESS_TOKEN=None), patch.object(wa.requests, "post", post):
        assert wa._send_via_meta("+15551234567", "hello") is False
    assert post.calls == []

    post2 = _GraphPost(status_code=200)
    with _meta_config(META_PHONE_NUMBER_ID=None), patch.object(wa.requests, "post", post2):
        assert wa._send_via_meta("+15551234567", "hello") is False
    assert post2.calls == []


def test_send_via_meta_non_200_response_is_a_failure(caplog):
    """A non-200 Graph response fails the send, and the error log never carries the response body."""
    post = _GraphPost(status_code=400, text='{"error": {"message": "access token invalid"}}')
    with _meta_config(), patch.object(wa.requests, "post", post), \
            caplog.at_level(logging.ERROR, logger="channels.whatsapp.router"):
        assert wa._send_via_meta("+15551234567", "hello") is False

    records = [record for record in caplog.records
               if record.name == "channels.whatsapp.router" and record.levelno == logging.ERROR]
    assert records, "expected an ERROR record on the router logger"
    assert any("400" in record.getMessage() for record in records)
    assert all("access token invalid" not in record.getMessage() for record in records)


# --- webhook verification (GET) ---------------------------------------------

def test_meta_webhook_verification_echoes_challenge_for_the_right_token():
    with _meta_config():
        response = _call_get({"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN,
                              "hub.challenge": "1158201444"})
    assert response.status_code == 200
    assert response.body == b"1158201444"


def test_meta_webhook_verification_rejects_a_wrong_token():
    with _meta_config():
        with pytest.raises(HTTPException) as exc:
            _call_get({"hub.mode": "subscribe", "hub.verify_token": "wrong",
                       "hub.challenge": "1158201444"})
    assert exc.value.status_code == 403


def test_meta_webhook_verification_rejects_a_mode_other_than_subscribe():
    with _meta_config():
        with pytest.raises(HTTPException) as exc:
            _call_get({"hub.mode": "other", "hub.verify_token": VERIFY_TOKEN,
                       "hub.status": "not subscribed"})
    assert exc.value.status_code == 403


def test_meta_webhook_verification_fails_closed_without_a_configured_token():
    with _meta_config(META_VERIFY_TOKEN=None):
        with pytest.raises(HTTPException) as exc:
            _call_get({"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN,
                       "hub.challenge": "1158201444"})
    assert exc.value.status_code == 403


def test_meta_webhook_verification_rejects_a_non_ascii_verify_token():
    """A non-ASCII hub.verify_token is a failed verification (403), never a server error, so the challenge is not echoed."""
    with _meta_config():
        with pytest.raises(Exception) as excinfo:
            _call_get({"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN + "中",
                       "hub.challenge": "1158201444"})
    assert isinstance(excinfo.value, HTTPException)
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize("side", ["received", "configured"])
@pytest.mark.parametrize("credential", NON_ASCII_CREDENTIALS)
def test_meta_token_verifier_never_raises_on_non_ascii_credentials(credential, side):
    """Any non-ASCII character on either side of the verify-token comparison is a failed verification (False -> 403), never a raised error."""
    if side == "received":
        token, configured = VERIFY_TOKEN + credential, VERIFY_TOKEN
    else:
        token, configured = VERIFY_TOKEN, VERIFY_TOKEN + credential
    with _meta_config(META_VERIFY_TOKEN=configured):
        try:
            result = wa._verify_meta_webhook_token("subscribe", token)
        except Exception as exc:
            pytest.fail(f"verifier raised {type(exc).__name__}: {exc}")
    assert result is False


# --- webhook signature verification (POST) ----------------------------------

def test_meta_signature_matches_the_documented_hmac_shape():
    with _meta_config():
        assert wa._verify_meta_signature(EXPECTED_SIGNATURE, TEST_BODY) is True


def test_meta_signature_rejects_a_wrong_or_malformed_signature():
    with _meta_config():
        assert wa._verify_meta_signature(_sign(TEST_BODY, secret="example-other-secret"), TEST_BODY) is False
        assert wa._verify_meta_signature("sha256=" + "0" * 64, TEST_BODY) is False
        assert wa._verify_meta_signature("", TEST_BODY) is False
        assert wa._verify_meta_signature(EXPECTED_SIGNATURE + "ff", TEST_BODY) is False


def test_meta_signature_fails_closed_without_a_configured_secret():
    with _meta_config(META_APP_SECRET=None):
        assert wa._verify_meta_signature(EXPECTED_SIGNATURE, TEST_BODY) is False


@pytest.mark.parametrize("side", ["received", "configured"])
@pytest.mark.parametrize("credential", NON_ASCII_CREDENTIALS)
def test_meta_signature_verifier_never_raises_on_non_ascii_credentials(credential, side):
    """Any non-ASCII character on either side of the signature comparison is a failed verification (False -> 403), never a raised error."""
    if side == "received":
        with _meta_config():
            try:
                result = wa._verify_meta_signature("sha256=" + credential, TEST_BODY)
            except Exception as exc:
                pytest.fail(f"verifier raised {type(exc).__name__}: {exc}")
    else:
        with _meta_config(META_APP_SECRET=APP_SECRET + credential):
            try:
                result = wa._verify_meta_signature(EXPECTED_SIGNATURE, TEST_BODY)
            except Exception as exc:
                pytest.fail(f"verifier raised {type(exc).__name__}: {exc}")
    assert result is False


def test_webhook_post_with_valid_signature_is_processed():
    with _meta_config(), patch.object(wa, "handle_incoming_message") as handle:
        response = _call_post({"x-hub-signature-256": _sign(TEST_BODY)})
    assert response == {"ok": True}
    handle.assert_called_once_with("15551234567", "hello from Meta")


def test_webhook_post_with_invalid_signature_is_rejected_before_processing():
    with _meta_config(), patch.object(wa, "handle_incoming_message") as handle:
        with pytest.raises(HTTPException) as exc:
            _call_post({"x-hub-signature-256": _sign(TEST_BODY, secret="example-wrong-secret")})
    assert exc.value.status_code == 403
    handle.assert_not_called()


def test_webhook_post_without_a_signature_is_rejected_before_processing():
    with _meta_config(), patch.object(wa, "handle_incoming_message") as handle:
        with pytest.raises(HTTPException) as exc:
            _call_post({})
    assert exc.value.status_code == 403
    handle.assert_not_called()


def test_webhook_post_with_non_ascii_signature_is_rejected_before_processing():
    """A non-ASCII X-Hub-Signature-256 is an invalid credential, not a server error: 403 before any processing."""
    with _meta_config(), patch.object(wa, "handle_incoming_message") as handle:
        with pytest.raises(Exception) as excinfo:
            _call_post({"x-hub-signature-256": "sha256=\udcff"})
    assert isinstance(excinfo.value, HTTPException)
    assert excinfo.value.status_code == 403
    handle.assert_not_called()


def test_webhook_post_with_non_ascii_signature_stays_rejected_under_the_opt_out():
    """WHATSAPP_ALLOW_UNSIGNED covers missing signatures only: a non-ASCII signature is still a forgery and stays a 403."""
    clean = {k: v for k, v in os.environ.items() if k != "WHATSAPP_ALLOW_UNSIGNED"}
    clean["WHATSAPP_ALLOW_UNSIGNED"] = "true"
    with _meta_config(), patch.dict(os.environ, clean, clear=True), \
         patch.object(wa, "handle_incoming_message") as handle:
        with pytest.raises(Exception) as excinfo:
            _call_post({"x-hub-signature-256": "sha256=\udcff"})
    assert isinstance(excinfo.value, HTTPException)
    assert excinfo.value.status_code == 403
    handle.assert_not_called()


def test_webhook_post_without_a_signature_needs_the_explicit_opt_out():
    clean = {k: v for k, v in os.environ.items() if k != "WHATSAPP_ALLOW_UNSIGNED"}
    clean["WHATSAPP_ALLOW_UNSIGNED"] = "true"
    with _meta_config(), patch.dict(os.environ, clean, clear=True), \
         patch.object(wa, "handle_incoming_message") as handle:
        _call_post({})
    handle.assert_called_once_with("15551234567", "hello from Meta")


def test_webhook_post_with_invalid_signature_stays_rejected_under_the_opt_out():
    """WHATSAPP_ALLOW_UNSIGNED covers missing signatures only: a present but
    invalid signature is still a forgery and stays a 403 -- the same property
    the Twilio path's tests pin in tests/test_approval_sender.py."""
    clean = {k: v for k, v in os.environ.items() if k != "WHATSAPP_ALLOW_UNSIGNED"}
    clean["WHATSAPP_ALLOW_UNSIGNED"] = "true"
    with _meta_config(), patch.dict(os.environ, clean, clear=True), \
         patch.object(wa, "handle_incoming_message") as handle:
        with pytest.raises(HTTPException) as exc:
            _call_post({"x-hub-signature-256": _sign(TEST_BODY, secret="example-wrong-secret")})
    assert exc.value.status_code == 403
    handle.assert_not_called()


def test_webhook_post_ignores_non_text_and_status_only_payloads():
    with _meta_config(), patch.object(wa, "handle_incoming_message") as handle:
        image_then_text = TEST_BODY.replace(
            b'"messages": [{"from"',
            b'"messages": [{"from": "15550001234", "id": "wamid.IMG", "timestamp": "1", '
            b'"type": "image", "image": {"id": "1", "mime_type": "image/jpeg"}}, {"from"'
        )
        assert image_then_text != TEST_BODY  # bytes.replace no-ops silently if the fixture drifts
        _call_post({"x-hub-signature-256": _sign(image_then_text)}, body=image_then_text)
        status_only = json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15550001111", "phone_number_id": "111222333"},
                "statuses": [{"id": "wamid.TESTMSG001", "status": "delivered"}],
            }}]}],
        }).encode("utf-8")
        assert _call_post({"x-hub-signature-256": _sign(status_only)}, body=status_only) == {"ok": True}
    handle.assert_called_once_with("15551234567", "hello from Meta")


def test_webhook_post_routes_on_whatsapp_provider_not_payload_shape():
    """The same Meta-signed JSON POST is refused when WHATSAPP_PROVIDER is twilio:
    the branch must follow the provider setting, not the payload's shape."""
    with patch.object(wa, "WHATSAPP_PROVIDER", "twilio"), \
         patch.object(wa, "handle_incoming_message") as handle:
        with pytest.raises(HTTPException) as exc:
            _call_post({"x-hub-signature-256": _sign(TEST_BODY)}, request_class=_MetaAndTwilioRequest)
    assert exc.value.status_code == 403
    handle.assert_not_called()
