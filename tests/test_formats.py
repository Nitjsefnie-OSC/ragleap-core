"""More document formats and web pages by address (needs the ragleap-rag package, as in requirements.txt)."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("ragleap.parsers")

KEY = {"x-api-key": "k-test"}


def _client(monkeypatch, calls=None):
    from core import api
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    store = calls if calls is not None else []

    def fake_ingest(name, text):
        store.append((name, text))
        return {"document_id": "d-1", "chunks_stored": 1}

    monkeypatch.setattr(api, "ingest_document", fake_ingest)
    return TestClient(api.app), store


def _upload(c, name, data):
    return c.post("/upload", headers=KEY, files={"file": (name, data, "application/octet-stream")})


def test_supported_extensions_include_the_package_formats():
    from core import api, parsers
    assert {".txt", ".pdf", ".docx", ".md", ".csv", ".xlsx", ".pptx", ".html", ".epub"} <= parsers.SUPPORTED_EXTENSIONS
    assert len(parsers.SUPPORTED_EXTENSIONS) >= 28
    assert api.ALLOWED_EXTENSIONS == parsers.SUPPORTED_EXTENSIONS


def test_upload_accepts_text_like_formats(monkeypatch):
    c, calls = _client(monkeypatch)
    assert _upload(c, "a.csv", b"name,age\nAna,31\n").status_code == 200
    assert _upload(c, "a.md", b"# Heading\nbody text").status_code == 200
    assert _upload(c, "a.json", b'{"colour": "teal"}').status_code == 200
    texts = " ".join(t for _, t in calls)
    assert "Ana" in texts and "Heading" in texts and "teal" in texts


def test_upload_accepts_html_and_zip(monkeypatch):
    pytest.importorskip("bs4")
    c, calls = _client(monkeypatch)
    assert _upload(c, "page.html", b"<html><body><p>Hello readable world</p></body></html>").status_code == 200
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("inner.txt", "zipped words")
    assert _upload(c, "bundle.zip", buf.getvalue()).status_code == 200
    texts = " ".join(t for _, t in calls)
    assert "Hello readable world" in texts and "zipped words" in texts


def test_upload_still_rejects_other_types(monkeypatch):
    c, calls = _client(monkeypatch)
    for name in ("run.exe", "song.mp3", "clip.mp4", "photo.png", "noextension"):
        r = _upload(c, name, b"x")
        assert r.status_code == 400 and "Unsupported file type" in r.json()["detail"], name
    assert calls == []


def test_documents_lists_formats_and_url_flag(monkeypatch):
    c, _ = _client(monkeypatch)
    monkeypatch.setattr("core.document_store.list_documents", lambda limit=100: [])
    r = c.get("/documents", headers=KEY)
    assert r.status_code == 200
    body = r.json()
    assert ".csv" in body["formats"] and ".txt" in body["formats"]
    assert isinstance(body["url_ingest"], bool) and body["max_mb"] == 20 and body["documents"] == []


def test_ingest_url_needs_the_key(monkeypatch):
    c, calls = _client(monkeypatch)
    assert c.post("/ingest/url", json={"url": "http://example.com/"}).status_code == 401
    assert calls == []


def test_ingest_url_rejects_bad_input(monkeypatch):
    c, calls = _client(monkeypatch)
    monkeypatch.setattr("core.parsers.url_ingest_available", lambda: True)
    for bad in ("", "   ", "ftp://example.com/x", "example.com", "javascript:alert(1)", "http://" + "a" * 3000):
        r = c.post("/ingest/url", headers=KEY, json={"url": bad})
        assert r.status_code == 400, bad
    assert calls == []


def test_ingest_url_refuses_private_and_internal_addresses(monkeypatch):
    pytest.importorskip("trafilatura")
    from core import parsers
    if not parsers.url_ingest_available():
        pytest.skip("the installed ragleap-rag is too old for URL ingestion (needs >= 0.13.0)")
    c, calls = _client(monkeypatch)
    monkeypatch.delenv("INGEST_ALLOW_PRIVATE_URLS", raising=False)
    for url in ("http://127.0.0.1:9/", "http://169.254.169.254/latest/meta-data/", "http://localhost/",
                "http://[::1]/", "http://10.0.0.5/", "http://2130706433/"):
        r = c.post("/ingest/url", headers=KEY, json={"url": url})
        assert r.status_code == 400 and "refused" in r.json()["detail"], url
    assert calls == []


def test_ingest_url_adds_the_page(monkeypatch):
    c, calls = _client(monkeypatch)
    monkeypatch.setattr("core.parsers.url_ingest_available", lambda: True)
    monkeypatch.setattr("core.parsers.fetch_url_text", lambda url: "page words")
    r = c.post("/ingest/url", headers=KEY, json={"url": "https://example.com/a"})
    assert r.status_code == 200 and r.json() == {"document_id": "d-1", "chunks_stored": 1}
    assert calls == [("https://example.com/a", "page words")]


def test_ingest_url_without_web_support_is_501(monkeypatch):
    c, calls = _client(monkeypatch)
    monkeypatch.setattr("core.parsers.url_ingest_available", lambda: False)
    assert c.post("/ingest/url", headers=KEY, json={"url": "https://example.com/"}).status_code == 501
    assert calls == []


def test_private_addresses_are_allowed_only_by_the_env_setting(monkeypatch):
    from core import parsers
    seen = []
    monkeypatch.setattr("ragleap.web.fetch_url_text", lambda url, allow_private=False: seen.append(allow_private) or "text")
    monkeypatch.delenv("INGEST_ALLOW_PRIVATE_URLS", raising=False)
    parsers.fetch_url_text("http://intranet.example/")
    monkeypatch.setenv("INGEST_ALLOW_PRIVATE_URLS", "true")
    parsers.fetch_url_text("http://intranet.example/")
    assert seen == [False, True]


def test_empty_page_text_is_a_400(monkeypatch):
    c, calls = _client(monkeypatch)
    monkeypatch.setattr("core.parsers.url_ingest_available", lambda: True)
    monkeypatch.setattr("ragleap.web.fetch_url_text", lambda url, allow_private=False: None)
    r = c.post("/ingest/url", headers=KEY, json={"url": "https://example.com/empty"})
    assert r.status_code == 400 and "readable text" in r.json()["detail"]
    assert calls == []


def test_dashboard_has_the_url_box_and_dynamic_formats():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "core" / "office_static" / "app.js").read_text(encoding="utf-8")
    assert '"/ingest/url"' in js and "Add web page" in js and "info.formats" in js


def test_url_ingest_needs_a_package_that_can_refuse_private_addresses(monkeypatch):
    pytest.importorskip("trafilatura")
    pytest.importorskip("ragleap._net")
    from core import parsers
    monkeypatch.setattr("ragleap.web.fetch_url_text", lambda url: "text")
    assert parsers.url_ingest_available() is False
    monkeypatch.setattr("ragleap.web.fetch_url_text", lambda url, allow_private=False: "text")
    assert parsers.url_ingest_available() is True
