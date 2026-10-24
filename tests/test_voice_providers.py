"""
Voice provider dispatch tests: no network, provider functions mocked.
"""
import asyncio
import base64
import importlib
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channels.voice import audio as voice_audio
from channels.voice import router as voice_router

LOUD_FRAME = b"\x80" * 160   # mu-law max amplitude -> RMS far above the speech threshold
QUIET_FRAME = b"\xff" * 160  # mu-law near-silence -> below the threshold

_CONFIG_ENV_VARS = (
    "VOICE_BOT_NAME", "VOICE_GREETING", "VOICE_LANGUAGE",
    "VOICE_STT_PROVIDER", "OPENAI_API_KEY",
    "VOICE_TTS_PROVIDER", "VOICE_TTS_VOICE",
    "DEEPGRAM_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
)


class FakeWS:
    """Minimal async-iterable websocket: replays scripted events, records sends."""

    def __init__(self, events):
        self.events = [json.dumps(e) for e in events]
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)

    async def send(self, payload):
        self.sent.append(payload)


def _media_event(frame):
    """A Twilio media event carrying one 160-byte mu-law frame."""
    return {"event": "media", "media": {"payload": base64.b64encode(frame).decode("utf-8")}}


def _config_from_env(**env):
    """
    Resolve VOICE_CONFIG through the real config module with `env` applied and
    every config var absent from `env` removed, so no test depends on ambient
    env. The module is reloaded under ambient env afterwards.
    """
    import channels.voice.config as voice_config
    with patch.dict(os.environ, env):
        for name in _CONFIG_ENV_VARS:
            if name not in env:
                os.environ.pop(name, None)
        importlib.reload(voice_config)
        cfg = dict(voice_config.VOICE_CONFIG)
    importlib.reload(voice_config)
    return cfg


@pytest.fixture(autouse=True)
def _no_live_requests():
    """
    No test in this file may emit a live provider request. Patching the audio
    module's requests.post with a failing stand-in keeps the RED run (unmodified
    code, provider mocks not yet intercepting the router's direct bindings) and
    any future regression offline: the siblings catch the error and return empty.
    """
    with patch.object(voice_audio.requests, "post", side_effect=AssertionError("live request")):
        yield


def _stt_events():
    """A call: connect, start, 20 loud + 20 quiet frames, stop — one utterance."""
    events = [{"event": "connected"}, {"event": "start", "streamSid": "sid-stt"}]
    events += [_media_event(LOUD_FRAME) for _ in range(20)]
    events += [_media_event(QUIET_FRAME) for _ in range(20)]
    events.append({"event": "stop"})
    return events


def test_stt_dispatches_to_deepgram_when_configured():
    """VOICE_STT_PROVIDER=deepgram (env through config) must call Deepgram and never OpenAI."""
    cfg = _config_from_env(VOICE_STT_PROVIDER="deepgram", DEEPGRAM_API_KEY="your-deepgram-key")
    ws = FakeWS(_stt_events())
    with patch.object(voice_router, "get_voice_config", return_value=cfg), \
         patch.object(voice_audio, "transcribe_with_deepgram", create=True) as deepgram, \
         patch.object(voice_audio, "transcribe_audio") as openai_stt, \
         patch.object(voice_audio, "text_to_speech", return_value=b"greeting-audio") as openai_tts, \
         patch.object(voice_audio, "text_to_speech_elevenlabs", create=True) as elevenlabs:
        asyncio.run(voice_router.handle_call(ws))
    deepgram.assert_called_once()
    assert deepgram.call_args.args[1] == "your-deepgram-key"
    openai_stt.assert_not_called()
    openai_tts.assert_called()  # the greeting still speaks through the default TTS provider
    elevenlabs.assert_not_called()


def test_stt_keeps_openai_for_whisper_provider():
    """The recognized default provider keeps the OpenAI STT; Deepgram is never touched."""
    cfg = _config_from_env(VOICE_STT_PROVIDER="whisper", OPENAI_API_KEY="your-openai-key")
    ws = FakeWS(_stt_events())
    with patch.object(voice_router, "get_voice_config", return_value=cfg), \
         patch.object(voice_audio, "transcribe_with_deepgram", create=True) as deepgram, \
         patch.object(voice_audio, "transcribe_audio") as openai_stt, \
         patch.object(voice_audio, "text_to_speech", return_value=b"greeting-audio") as openai_tts:
        asyncio.run(voice_router.handle_call(ws))
    openai_stt.assert_called_once()
    assert openai_stt.call_args.args[1] == "your-openai-key"
    deepgram.assert_not_called()


def test_stt_keeps_openai_when_provider_unset():
    """No VOICE_STT_PROVIDER at all behaves exactly like the whisper default."""
    cfg = _config_from_env(OPENAI_API_KEY="your-openai-key")
    ws = FakeWS(_stt_events())
    with patch.object(voice_router, "get_voice_config", return_value=cfg), \
         patch.object(voice_audio, "transcribe_with_deepgram", create=True) as deepgram, \
         patch.object(voice_audio, "transcribe_audio") as openai_stt, \
         patch.object(voice_audio, "text_to_speech", return_value=b"greeting-audio") as openai_tts:
        asyncio.run(voice_router.handle_call(ws))
    openai_stt.assert_called_once()
    deepgram.assert_not_called()
    assert cfg["stt_provider"] == "whisper"
    assert cfg["stt_api_key"] == "your-openai-key"


def test_stt_keeps_openai_for_unrecognized_provider():
    """Anything unrecognized (not deepgram) must keep the existing OpenAI behavior."""
    cfg = _config_from_env(VOICE_STT_PROVIDER="carrier-pigeon", OPENAI_API_KEY="your-openai-key")
    ws = FakeWS(_stt_events())
    with patch.object(voice_router, "get_voice_config", return_value=cfg), \
         patch.object(voice_audio, "transcribe_with_deepgram", create=True) as deepgram, \
         patch.object(voice_audio, "transcribe_audio") as openai_stt, \
         patch.object(voice_audio, "text_to_speech", return_value=b"greeting-audio") as openai_tts:
        asyncio.run(voice_router.handle_call(ws))
    openai_stt.assert_called_once()
    deepgram.assert_not_called()
    assert cfg["stt_api_key"] == "your-openai-key"


def test_tts_dispatches_to_elevenlabs_when_configured():
    """VOICE_TTS_PROVIDER=elevenlabs (env through config) must call ElevenLabs and never OpenAI."""
    cfg = _config_from_env(
        VOICE_TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="your-elevenlabs-key",
        ELEVENLABS_VOICE_ID="your-voice-id",
    )
    assert cfg["tts_api_key"] == "your-elevenlabs-key"
    assert cfg["tts_voice"] == "your-voice-id"
    ws = FakeWS([])
    with patch.object(voice_audio, "text_to_speech_elevenlabs", create=True, return_value=b"tts-audio") as elevenlabs, \
         patch.object(voice_audio, "text_to_speech") as openai_tts:
        asyncio.run(voice_router.speak_reply(ws, "sid-tts", "hello there", cfg))
    elevenlabs.assert_called_once_with("hello there", "your-elevenlabs-key", "your-voice-id")
    openai_tts.assert_not_called()
    assert len(ws.sent) == 2  # media event + mark: the audio actually streamed


def test_tts_keeps_openai_for_openai_provider():
    """The recognized default provider keeps the OpenAI TTS; ElevenLabs is never touched."""
    cfg = _config_from_env(VOICE_TTS_PROVIDER="openai", OPENAI_API_KEY="your-openai-key")
    ws = FakeWS([])
    with patch.object(voice_audio, "text_to_speech_elevenlabs", create=True) as elevenlabs, \
         patch.object(voice_audio, "text_to_speech", return_value=b"tts-audio") as openai_tts:
        asyncio.run(voice_router.speak_reply(ws, "sid-tts", "hello there", cfg))
    openai_tts.assert_called_once_with("hello there", "your-openai-key", cfg["tts_voice"])
    elevenlabs.assert_not_called()
    assert len(ws.sent) == 2


def test_tts_keeps_openai_when_provider_unset():
    """No VOICE_TTS_PROVIDER at all behaves exactly like the openai default."""
    cfg = _config_from_env(OPENAI_API_KEY="your-openai-key")
    ws = FakeWS([])
    with patch.object(voice_audio, "text_to_speech_elevenlabs", create=True) as elevenlabs, \
         patch.object(voice_audio, "text_to_speech", return_value=b"tts-audio") as openai_tts:
        asyncio.run(voice_router.speak_reply(ws, "sid-tts", "hello there", cfg))
    openai_tts.assert_called_once()
    elevenlabs.assert_not_called()
    assert cfg["tts_provider"] == "openai"
    assert cfg["tts_api_key"] == "your-openai-key"
    assert cfg["tts_voice"] == "nova"
    assert len(ws.sent) == 2


def test_tts_keeps_openai_for_unrecognized_provider():
    """Anything unrecognized (not elevenlabs) must keep the existing OpenAI behavior."""
    cfg = _config_from_env(VOICE_TTS_PROVIDER="carrier-pigeon", OPENAI_API_KEY="your-openai-key")
    ws = FakeWS([])
    with patch.object(voice_audio, "text_to_speech_elevenlabs", create=True) as elevenlabs, \
         patch.object(voice_audio, "text_to_speech", return_value=b"tts-audio") as openai_tts:
        asyncio.run(voice_router.speak_reply(ws, "sid-tts", "hello there", cfg))
    openai_tts.assert_called_once()
    elevenlabs.assert_not_called()
    assert cfg["tts_provider"] == "carrier-pigeon"
    assert cfg["tts_api_key"] == "your-openai-key"


def _deepgram_response(transcript):
    """A Deepgram listen response carrying `transcript`."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "results": {"channels": [{"alternatives": [{"transcript": transcript}]}]}
    }
    return resp


def test_deepgram_success_posts_listen_and_parses_transcript():
    """Success posts to the listen endpoint with the documented call shape and parses the transcript."""
    with patch.object(voice_audio.requests, "post", return_value=_deepgram_response("caller speaks now")) as post:
        assert voice_audio.transcribe_with_deepgram(b"audio-bytes", "your-deepgram-key") == "caller speaks now"
    assert post.call_args.args[0] == "https://api.deepgram.com/v1/listen"
    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Token your-deepgram-key"
    assert kwargs["headers"]["Content-Type"] == "audio/wav"
    assert kwargs["params"] == {"model": "nova-2", "smart_format": "true"}
    assert kwargs["data"] == b"audio-bytes"


def test_deepgram_strips_surrounding_whitespace():
    """The transcript is stripped like the OpenAI sibling returns it."""
    with patch.object(voice_audio.requests, "post", return_value=_deepgram_response("  padded utterance  ")):
        assert voice_audio.transcribe_with_deepgram(b"audio", "your-deepgram-key") == "padded utterance"


def test_deepgram_missing_key_sends_no_request():
    with patch.object(voice_audio.requests, "post") as post:
        assert voice_audio.transcribe_with_deepgram(b"audio", "") == ""
    post.assert_not_called()


def test_deepgram_http_error_returns_empty():
    resp = _deepgram_response("ignored")
    resp.raise_for_status.side_effect = Exception("500 server error")
    with patch.object(voice_audio.requests, "post", return_value=resp):
        assert voice_audio.transcribe_with_deepgram(b"audio", "your-deepgram-key") == ""


def test_deepgram_request_exception_returns_empty():
    with patch.object(voice_audio.requests, "post", side_effect=Exception("connection died")):
        assert voice_audio.transcribe_with_deepgram(b"audio", "your-deepgram-key") == ""


def test_deepgram_empty_transcript_returns_empty_string():
    with patch.object(voice_audio.requests, "post", return_value=_deepgram_response("")):
        assert voice_audio.transcribe_with_deepgram(b"audio", "your-deepgram-key") == ""


def test_deepgram_malformed_shape_returns_empty_string():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"unexpected": "shape"}
    with patch.object(voice_audio.requests, "post", return_value=resp):
        assert voice_audio.transcribe_with_deepgram(b"audio", "your-deepgram-key") == ""


def _elevenlabs_response():
    """An ElevenLabs TTS response carrying raw mp3 bytes."""
    resp = MagicMock(status_code=200)
    resp.content = b"mp3-bytes"
    return resp


def test_elevenlabs_success_posts_voice_in_path():
    """Success posts to the convert endpoint with the voice id in the path and returns the audio bytes."""
    with patch.object(voice_audio.requests, "post", return_value=_elevenlabs_response()) as post:
        result = voice_audio.text_to_speech_elevenlabs("hello there", "your-elevenlabs-key", "your-voice-id")
    assert result == b"mp3-bytes"
    assert post.call_args.args[0] == "https://api.elevenlabs.io/v1/text-to-speech/your-voice-id"
    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["xi-api-key"] == "your-elevenlabs-key"
    assert kwargs["json"] == {"text": "hello there", "model_id": "eleven_multilingual_v2"}


def test_elevenlabs_missing_key_sends_no_request():
    with patch.object(voice_audio.requests, "post") as post:
        assert voice_audio.text_to_speech_elevenlabs("hello", "", "your-voice-id") == b""
    post.assert_not_called()


def test_elevenlabs_http_error_returns_empty_bytes():
    resp = _elevenlabs_response()
    resp.raise_for_status.side_effect = Exception("422 validation error")
    with patch.object(voice_audio.requests, "post", return_value=resp):
        assert voice_audio.text_to_speech_elevenlabs("hello", "your-elevenlabs-key", "your-voice-id") == b""


def test_elevenlabs_request_exception_returns_empty_bytes():
    with patch.object(voice_audio.requests, "post", side_effect=Exception("connection died")):
        assert voice_audio.text_to_speech_elevenlabs("hello", "your-elevenlabs-key", "your-voice-id") == b""


def test_elevenlabs_empty_text_still_posts_and_returns_content():
    """No client-side input guard, like the OpenAI sibling: empty text still reaches the API."""
    with patch.object(voice_audio.requests, "post", return_value=_elevenlabs_response()) as post:
        result = voice_audio.text_to_speech_elevenlabs("", "your-elevenlabs-key", "your-voice-id")
    assert result == b"mp3-bytes"
    assert post.call_args.kwargs["json"]["text"] == ""