"""Language detection model setting: lite works without any download; auto keeps the library default."""
import pytest


def test_model_setting_values():
    from core import language
    f = language._model_setting
    assert f(None) == "auto" and f("") == "auto" and f("AUTO") == "auto"
    assert f("lite") == "lite" and f(" Lite ") == "lite" and f("full") == "full"
    assert f("bogus") == "auto"


def test_auto_keeps_the_library_default(monkeypatch):
    from core import language
    calls = []
    monkeypatch.setattr(language, "detect", lambda *a, **k: calls.append((a, k)) or [{"lang": "en", "score": 0.9}])
    monkeypatch.setattr(language, "LANGUAGE_MODEL", "auto")
    assert language.language_detector._fasttext_detect("hello there")[0] == "en"
    assert calls == [(("hello there",), {})]


@pytest.mark.parametrize("setting", ["lite", "full"])
def test_lite_and_full_are_passed_to_the_library(monkeypatch, setting):
    from core import language
    calls = []
    monkeypatch.setattr(language, "detect", lambda *a, **k: calls.append((a, k)) or [{"lang": "en", "score": 0.9}])
    monkeypatch.setattr(language, "LANGUAGE_MODEL", setting)
    language.language_detector._fasttext_detect("hello there")
    assert calls == [(("hello there",), {"model": setting})]


def test_lite_works_without_any_download(monkeypatch):
    infer = pytest.importorskip("fast_langdetect.infer")

    def no_internet(*a, **k):
        raise RuntimeError("no internet in this test")

    monkeypatch.setattr(infer, "download", no_internet)
    from core import language
    monkeypatch.setattr(language, "LANGUAGE_MODEL", "lite")
    lang, conf = language.language_detector._fasttext_detect("Hello world, this is plainly an English sentence.")
    assert lang == "en" and conf > 0.5
    lang, conf = language.language_detector._fasttext_detect("नमस्ते, यह एक परीक्षण है")
    assert lang == "hi" and conf > 0.5


def test_failure_logs_one_hint_and_falls_back(monkeypatch, caplog):
    from core import language

    def fail(*a, **k):
        raise RuntimeError("Download failed")

    monkeypatch.setattr(language, "detect", fail)
    monkeypatch.setattr(language, "LANGUAGE_MODEL", "auto")
    monkeypatch.setattr(language, "_warned_download", False)
    with caplog.at_level("WARNING"):
        assert language.language_detector._fasttext_detect("x") == (language.DEFAULT_LANGUAGE, 0.0)
        language.language_detector._fasttext_detect("y")
    hints = [r.getMessage() for r in caplog.records if "LANGUAGE_DETECTION_MODEL=lite" in r.getMessage()]
    assert len(hints) == 1
