"""Network primitives for downloading models from Hugging Face. Standard library only.

Security properties (each one has a test):
- HTTPS only, hosts restricted to huggingface.co and hf.co (and subdomains), no URL credentials.
- Redirects are followed manually: every hop is re-validated, at most 5 hops.
- The access token (HF_TOKEN) is sent only on the first request, only to huggingface.co, and
  never on a redirect (CDN links carry their own signed query strings).
- URLs and query strings are never printed; messages name hosts only.
- Downloads are streamed, capped at the expected size, and checked against size and SHA-256.
The Policy object can be relaxed only from Python (the tests use a local fake server); the
command line has no switch for it.
"""
import hashlib
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import __version__

DEFAULT_BASE = "https://huggingface.co"
MAX_FILE_BYTES = 64 * 1024 ** 3
_REDIRECTS = (301, 302, 303, 307, 308)
_REPO = re.compile(r"^https://huggingface\.co/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)/?$")


class FetchError(Exception):
    """A network or download problem. Messages never contain URLs with query strings or tokens."""


@dataclass(frozen=True)
class Policy:
    allowed_suffixes: tuple = ("huggingface.co", "hf.co")
    token_hosts: tuple = ("huggingface.co",)
    require_https: bool = True
    max_redirects: int = 5
    timeout: float = 30.0


def repo_id_from_url(source_url):
    """'https://huggingface.co/OWNER/REPO' -> 'OWNER/REPO'; anything else -> None."""
    m = _REPO.match(source_url or "")
    return None if m is None else m.group(1) + "/" + m.group(2)


def resolve_url(base, repo_id, revision, path):
    return "%s/%s/resolve/%s/%s" % (base.rstrip("/"), repo_id, revision, urllib.parse.quote(path, safe="/"))


def check_url(url, policy):
    """Validate one URL against the policy and return its lowercase host name."""
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        raise FetchError("malformed URL")
    if p.username is not None or p.password is not None or "@" in p.netloc:
        raise FetchError("refusing a URL that contains credentials")
    if policy.require_https:
        if p.scheme != "https":
            raise FetchError("refusing non-HTTPS URL to host " + (host or "?"))
        if port not in (None, 443):
            raise FetchError("refusing non-standard port for host " + (host or "?"))
    elif p.scheme not in ("http", "https"):
        raise FetchError("refusing URL with unsupported scheme")
    if not any(host == s or host.endswith("." + s) for s in policy.allowed_suffixes):
        raise FetchError("host not allowed: " + (host or "?"))
    return host


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # redirects are handled (and validated) by open_url


def open_url(url, policy, token=None, opener=None):
    """Open url and return the response. Follows at most policy.max_redirects redirects."""
    opener = opener or urllib.request.build_opener(_NoRedirect)
    current = url
    for hop in range(policy.max_redirects + 1):
        host = check_url(current, policy)
        headers = {"User-Agent": "ragleap-voice/" + __version__}
        if hop == 0 and token and host in policy.token_hosts:
            headers["Authorization"] = "Bearer " + token
        try:
            return opener.open(urllib.request.Request(current, headers=headers), timeout=policy.timeout)
        except urllib.error.HTTPError as exc:
            code = exc.code
            location = exc.headers.get("Location") if exc.headers else None
            exc.close()
            if code in _REDIRECTS:
                if not location:
                    raise FetchError("redirect without a Location header from " + host)
                current = urllib.parse.urljoin(current, location)
                continue
            if code in (401, 403):
                raise FetchError("access denied by %s (HTTP %d): the repository may be gated; "
                                 "accept its conditions on the website and set HF_TOKEN" % (host, code))
            if code == 404:
                raise FetchError("not found at " + host + " (HTTP 404)")
            raise FetchError("HTTP %d from %s" % (code, host))
        except urllib.error.URLError as exc:
            reason = getattr(exc.reason, "strerror", None) or type(exc.reason).__name__
            raise FetchError("network error contacting " + host + ": " + str(reason)[:100])
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise FetchError("network error contacting " + host + ": " + type(exc).__name__)
    raise FetchError("too many redirects")


def get_json(url, policy, token=None, max_bytes=16 * 1024 * 1024):
    resp = open_url(url, policy, token)
    try:
        data = resp.read(max_bytes + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise FetchError("download interrupted (" + type(exc).__name__ + ")")
    finally:
        resp.close()
    if len(data) > max_bytes:
        raise FetchError("response too large")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise FetchError("response is not valid JSON")


def download_file(url, dest, policy, token=None, size=None, sha256=None, max_bytes=MAX_FILE_BYTES):
    """Stream url to dest (a pathlib.Path; None means hash only, write nothing).

    With size/sha256 given the download is capped at size and verified; without them it is capped
    at max_bytes. Returns (size, sha256 hex digest)."""
    cap = size if size is not None else max_bytes
    resp = open_url(url, policy, token)
    out = None
    try:
        length = resp.headers.get("Content-Length")
        if size is not None and length is not None and length.strip().isdigit() and int(length) != size:
            raise FetchError("Content-Length %s does not match the locked size %d" % (length.strip(), size))
        if dest is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            out = open(dest, "xb")
        h = hashlib.sha256()
        total = 0
        while True:
            try:
                chunk = resp.read(1 << 20)
            except (OSError, http.client.HTTPException) as exc:
                raise FetchError("download interrupted (" + type(exc).__name__ + ")")
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise FetchError("more data than expected (limit %d bytes)" % cap)
            h.update(chunk)
            if out is not None:
                out.write(chunk)
    finally:
        resp.close()
        if out is not None:
            out.close()
    digest = h.hexdigest()
    if size is not None and total != size:
        raise FetchError("%d bytes received, expected %d" % (total, size))
    if sha256 is not None and digest != sha256:
        raise FetchError("sha256 mismatch")
    return total, digest
