"""
Voice channel configuration for RagLeap Core.
Single-tenant: all settings come from .env, no Workspace/TenantSettings lookup.
"""
import os

VOICE_CONFIG = {
    "bot_name": os.environ.get("VOICE_BOT_NAME", "Assistant"),
    "custom_greeting": os.environ.get("VOICE_GREETING", ""),
    "language": os.environ.get("VOICE_LANGUAGE", "en-US"),

    # STT provider: "whisper" (OpenAI, default) or "deepgram"
    "stt_provider": os.environ.get("VOICE_STT_PROVIDER", "whisper"),
    "stt_api_key": (
        os.environ.get("DEEPGRAM_API_KEY", "")
        if os.environ.get("VOICE_STT_PROVIDER") == "deepgram"
        else os.environ.get("OPENAI_API_KEY", "")
    ),

    # TTS provider: "openai" (default) or "elevenlabs"
    "tts_provider": os.environ.get("VOICE_TTS_PROVIDER", "openai"),
    "tts_api_key": (
        os.environ.get("ELEVENLABS_API_KEY", "")
        if os.environ.get("VOICE_TTS_PROVIDER") == "elevenlabs"
        else os.environ.get("OPENAI_API_KEY", "")
    ),
    "tts_voice": (
        os.environ.get("ELEVENLABS_VOICE_ID", "")
        if os.environ.get("VOICE_TTS_PROVIDER") == "elevenlabs"
        else os.environ.get("VOICE_TTS_VOICE", "nova")
    ),
}


def get_voice_config() -> dict:
    """Return the single, global voice configuration for this deployment."""
    return dict(VOICE_CONFIG)
