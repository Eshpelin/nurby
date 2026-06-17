import logging
import secrets

from pydantic_settings import BaseSettings

_logger = logging.getLogger("nurby.config")

_DEFAULT_JWT_SECRET = "change-me-in-production-use-a-real-secret"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nurby:nurby_dev@localhost:5433/nurby"
    redis_url: str = "redis://localhost:6379/0"
    mediamtx_api_url: str = "http://localhost:9997"
    mediamtx_rtsp_url: str = "rtsp://localhost:8554"  # target for webcam bridge publishes
    # Webcam bridge. spawns ffmpeg against local camera devices. Runs on the
    # host that physically owns the camera. Must be disabled inside the
    # ingestion container because Docker Desktop cannot forward AVFoundation
    # or v4l2 devices from the host into a Linux container.
    disable_webcam_bridge: bool = False

    # Audio subsystem. Master feature flag. When false, no audio capture
    # task spawns, no STT runs, audio API routes 404. Schema migrations
    # still apply (cheap). Default off while audio ships behind flag.
    audio_enabled: bool = False
    # Override the STT provider kind. Defaults to faster_whisper. Set to
    # "mock" in tests for fixture-driven runs.
    audio_stt_provider: str = "faster_whisper"
    # faster-whisper model name. tiny.en | base.en | small.en | medium.en
    # | large-v3. Default chosen per the resolved decisions in the plan.
    audio_stt_model: str = "small.en"
    # STT accuracy/speed knobs. Defaults match the original hardcoded
    # values, so leaving them alone changes nothing. Raise audio_stt_beam_size
    # (e.g. 5) for better accuracy on noisy audio at a CPU cost. Enable
    # audio_stt_condition_on_previous_text to carry context across segments
    # (more coherent long speech, but can amplify a transcription error
    # across following segments). no_speech_threshold gates near-silence.
    audio_stt_beam_size: int = 1
    audio_stt_condition_on_previous_text: bool = False
    audio_stt_no_speech_threshold: float = 0.6
    # Filesystem root for opt-in raw audio storage.
    audio_storage_path: str = "./audio_clips"

    # ONVIF clock-skew workaround. Some cameras have no NTP or a drifted
    # RTC and reject WS-Security UsernameToken requests when the Created
    # timestamp differs from their own clock by more than a few seconds.
    # When true, PTZ/auth calls first query the camera's
    # GetSystemDateAndTime (no auth) and offset the Created timestamp to
    # match the camera's clock. Per-camera override: set the camera's
    # onvif_ignore_time_mismatch attribute (None falls back to this global).
    onvif_ignore_time_mismatch: bool = False

    recordings_path: str = "./recordings"
    thumbnails_path: str = "./thumbnails"
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_expiry_hours: int = 24
    cors_origins: str = ""  # comma-separated additional origins

    # Starred-person recap
    recap_ttl_seconds: int = 300
    recap_timeout_seconds: float = 20.0
    recap_default_provider: str = ""  # openai|anthropic|google|ollama. empty = auto

    # Public base URL of this backend. Used by Phase 2's {event_url}
    # template variable in notification bodies AND by Phase 3's
    # Telegram webhook delivery mode (setWebhook target). Must not
    # have a trailing slash. None disables features that require an
    # externally-reachable URL.
    public_base_url: str | None = None

    # SMTP settings for email notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# Warn loudly if JWT secret is the insecure default
if settings.jwt_secret == _DEFAULT_JWT_SECRET:
    _generated = secrets.token_urlsafe(32)
    _logger.warning(
        "JWT_SECRET is the insecure default. Generating a random secret for this session. "
        "Set JWT_SECRET in your .env file for persistent tokens. Generated secret (add to .env). JWT_SECRET=%s",
        _generated,
    )
    settings.jwt_secret = _generated

# Warn if SMTP is partially configured
if settings.smtp_host and not settings.smtp_user:
    _logger.warning("SMTP_HOST is set but SMTP_USER is empty. Email sending may fail.")
