"""
Voice provider dispatch tests: no network, provider functions mocked.
"""
import asyncio
import base64
import importlib
import io
import json
import os
import random
import struct
import sys
import wave
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


# --------------------------------------------------------------------------
# Regression (issue #950): every request the router hands to an STT provider
# must declare a format its body actually has, and the body — decoded by that
# declaration — must be exactly the mu-law utterance the scripted media
# events carried, in order, nothing dropped or added. The reference expansion
# below is derived in this file and checked against the published G.711
# fixed points on every use; it shares nothing with the code under test.
# --------------------------------------------------------------------------

_CORPUS_SEED = 20261025
_FRAME = 160              # one mu-law frame at Twilio's 8 kHz capture rate
_SILENCE_TAIL = 20        # router SILENCE_END_FRAMES: 400 ms of silence ends an utterance
_HARD_CAP_FRAMES = 240    # router MAX_SPEECH_FRAMES: 5 s cap hands off even without silence


def _mu_law_reference():
    """
    The 256-entry G.711 mu-law expansion table, derived here and verified
    against the published fixed points on every use; it shares nothing with
    the implementation under test (no audioop, no implementation helper).
    """
    table = []
    for code in range(256):
        stored = code ^ 0xFF  # mu-law bytes are stored bit-complemented
        magnitude = (((stored & 0x0F) << 3) + 0x84) << ((stored >> 4) & 0x07)
        table.append((0x84 - magnitude) if stored & 0x80 else (magnitude - 0x84))
    assert table[0xFF] == 0 and table[0x7F] == 0
    assert table[0x80] == 32124 and table[0x00] == -32124
    return table


def _utterance_payloads():
    """
    The two utterance byte strings the stream carries, and the media chunks
    they are cut into, in call order. A seeded shuffle of all 256 mu-law
    codes leads utterance one — both zero codes (0x7F, 0xFF), both extremes
    (0x80, 0x00) and every code on which the A-law and mu-law tables
    disagree — and a seeded pseudo-random stream fills both utterances out.
    Utterance one ends in 20 silent frames so the end-of-speech trigger
    fires; utterance two runs to the 240-frame hard cap. One chunk is
    deliberately 77 bytes, so a frame-alignment mistake cannot pass.
    """
    rng = random.Random(_CORPUS_SEED)
    alphabet = bytes(rng.sample(range(256), 256))
    body1 = alphabet + bytes(rng.randrange(256) for _ in range(_FRAME * 28 - 256 + 77))
    body2 = bytes(rng.randrange(256) for _ in range(_FRAME * _HARD_CAP_FRAMES))
    chunks1 = [body1[o:o + _FRAME] for o in range(0, _FRAME * 28, _FRAME)] + [body1[_FRAME * 28:]]
    chunks2 = [body2[o:o + _FRAME] for o in range(0, len(body2), _FRAME)]
    return (chunks1 + [QUIET_FRAME] * _SILENCE_TAIL,
            body1 + QUIET_FRAME * _SILENCE_TAIL), (chunks2, body2)


def _two_utterance_events():
    """Connect, start, two utterances — each ends in a VAD handoff — then stop."""
    (chunks1, _), (chunks2, _) = _utterance_payloads()
    events = [{"event": "connected"}, {"event": "start", "streamSid": "sid-stt"}]
    events += [_media_event(c) for c in chunks1]
    events += [_media_event(c) for c in chunks2]
    events.append({"event": "stop"})
    return events


def _samples_from_wav(body):
    """Decode a declared-WAV body: RIFF/WAVE, mono, 8 kHz, 16-bit linear PCM."""
    try:
        with wave.open(io.BytesIO(body)) as wav:
            channels, rate, width = wav.getnchannels(), wav.getframerate(), wav.getsampwidth()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AssertionError(
            f"request declares WAV but the body is not a decodable RIFF/WAVE file: {exc}")
    assert channels == 1, f"a declared WAV body must be mono, got {channels} channels"
    assert rate == 8000, f"a declared WAV body must be 8 kHz, got {rate} Hz"
    assert width == 2, f"a declared WAV body must be 16-bit linear PCM, got {width}-byte samples"
    return list(struct.unpack(f"<{len(frames) // 2}h", frames))


def _stt_request_samples(url, kwargs):
    """
    Decode one captured STT request strictly by its own declared metadata
    (headers, multipart file-part metadata, query params) and return its
    linear-PCM samples. A declaration this suite does not cover is an
    AssertionError — never a silent pass — so a request must declare either
    a WAV container or raw mu-law (encoding=mulaw, sample_rate=8000).
    """
    table = _mu_law_reference()
    try:
        headers = {str(k).lower(): v for k, v in (kwargs.get("headers") or {}).items()}
        params = kwargs.get("params") or {}
        if "/audio/transcriptions" in url:
            # OpenAI takes a multipart upload; the audio is the file part.
            filename, payload, part_type = kwargs["files"]["file"]
            assert part_type == "audio/wav" or str(filename).lower().endswith(".wav"), (
                f"OpenAI accepts no raw form: the file part must declare WAV, "
                f"got type {part_type!r} filename {filename!r}")
            assert not params, (
                f"no query parameters may ride on a WAV declaration, got {params}")
            return _samples_from_wav(payload.read())
        content_type = headers.get("content-type", "")
        if content_type.split(";")[0].strip() == "audio/wav":
            assert "encoding" not in params, (
                f"an encoding parameter must not ride on a WAV body, got params {params}")
            return _samples_from_wav(kwargs["data"])
        if content_type in ("", "audio/mulaw", "audio/basic", "application/octet-stream"):
            assert params.get("encoding") == "mulaw", (
                f"a containerless body must declare encoding=mulaw, got params {params}")
            assert str(params.get("sample_rate")) == "8000", (
                f"a raw mu-law body must declare sample_rate=8000, got params {params}")
            if "channels" in params:
                assert str(params["channels"]) == "1", (
                    f"the stream is mono, got channels={params['channels']!r}")
            body = kwargs["data"]
            assert isinstance(body, (bytes, bytearray)), (
                f"a containerless body must be plain bytes, got {type(body).__name__}")
            return [table[b] for b in body]
        raise AssertionError(
            f"uncovered Content-Type declaration {content_type!r}: a request must declare "
            f"WAV (audio/wav) or raw mu-law, so the receiver can decode the body it carries")
    except AssertionError:
        raise
    except Exception as exc:
        raise AssertionError(f"request metadata unreadable against its body: {exc!r}")


def _assert_utterance_arrives(request, utterance, label):
    """The request, decoded by its own declared metadata, is exactly `utterance` mu-law-decoded."""
    samples = _stt_request_samples(request[0], request[1])
    expected = [_mu_law_reference()[b] for b in utterance]
    assert samples == expected, (
        f"{label}: the request decoded to {len(samples)} samples but the utterance is "
        f"{len(expected)} samples — audio lost, added or mistranslated in transit")


def _stt_requests_from_call(cfg):
    """
    Drive the real handle_call over the two-utterance stream and return the
    two captured STT requests, in order. Only STT endpoints are kept; the
    greeting's TTS request is not under test here.
    """
    stt_calls = []

    def record_post(url, **kwargs):
        stt_calls.append((url, kwargs))
        resp = MagicMock(status_code=200)
        if "audio/speech" in url:
            resp.content = b"example-tts-bytes"
        elif "/v1/listen" in url:
            resp.json.return_value = {"results": {"channels": [{"alternatives": [{"transcript": ""}]}]}}
        else:
            resp.json.return_value = {"text": ""}
        return resp

    ws = FakeWS(_two_utterance_events())
    with patch.object(voice_router, "get_voice_config", return_value=cfg), \
         patch.object(voice_audio.requests, "post", side_effect=record_post):
        asyncio.run(voice_router.handle_call(ws))
    stt = [(u, k) for (u, k) in stt_calls if "/v1/listen" in u or "/audio/transcriptions" in u]
    assert len(stt) == 2, (
        f"expected one STT request per utterance (2), got {len(stt)} — "
        f"the VAD triggers did not hand both utterances off")
    return stt


def test_stt_deepgram_request_declares_and_carries_the_utterance_both_triggers():
    """Deepgram requests must declare their true format and carry the decoded utterance, across both VAD triggers."""
    cfg = _config_from_env(VOICE_STT_PROVIDER="deepgram", DEEPGRAM_API_KEY="your-deepgram-key")
    (_, payload1), (_, payload2) = _utterance_payloads()
    stt = _stt_requests_from_call(cfg)
    _assert_utterance_arrives(stt[0], payload1, "deepgram end-of-speech utterance")
    _assert_utterance_arrives(stt[1], payload2, "deepgram hard-cap utterance")


def test_stt_whisper_request_declares_and_carries_the_utterance_both_triggers():
    """Whisper (multipart) requests must declare their true format and carry the decoded utterance, across both VAD triggers."""
    cfg = _config_from_env(VOICE_STT_PROVIDER="whisper", OPENAI_API_KEY="your-openai-key")
    (_, payload1), (_, payload2) = _utterance_payloads()
    stt = _stt_requests_from_call(cfg)
    _assert_utterance_arrives(stt[0], payload1, "whisper end-of-speech utterance")
    _assert_utterance_arrives(stt[1], payload2, "whisper hard-cap utterance")


def test_stt_unset_provider_request_declares_and_carries_the_utterance():
    """No VOICE_STT_PROVIDER at all: the OpenAI request must still declare and carry the utterance."""
    cfg = _config_from_env(OPENAI_API_KEY="your-openai-key")
    assert cfg["stt_provider"] == "whisper"
    (_, payload1), (_, payload2) = _utterance_payloads()
    stt = _stt_requests_from_call(cfg)
    _assert_utterance_arrives(stt[0], payload1, "unset-provider end-of-speech utterance")
    _assert_utterance_arrives(stt[1], payload2, "unset-provider hard-cap utterance")


def test_stt_unrecognized_provider_request_declares_and_carries_the_utterance():
    """An unrecognized VOICE_STT_PROVIDER keeps OpenAI, whose request must still declare and carry the utterance."""
    cfg = _config_from_env(VOICE_STT_PROVIDER="carrier-pigeon", OPENAI_API_KEY="your-openai-key")
    assert cfg["stt_api_key"] == "your-openai-key"
    (_, payload1), (_, payload2) = _utterance_payloads()
    stt = _stt_requests_from_call(cfg)
    _assert_utterance_arrives(stt[0], payload1, "unrecognized-provider end-of-speech utterance")
    _assert_utterance_arrives(stt[1], payload2, "unrecognized-provider hard-cap utterance")
