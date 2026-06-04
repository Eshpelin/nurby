# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=120
# Point Python's ssl at the system CA bundle so model downloads (whisper,
# panns) don't fail with CERTIFICATE_VERIFY_FAILED in the slim image.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_DIR=/etc/ssl/certs

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg ca-certificates \
    cmake build-essential libboost-all-dev \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# CPU-only torch first (no GPU in these containers). avoids the ~426MB
# CUDA wheel that stalled on slow networks; the main install reuses it.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN --mount=type=cache,target=/root/.cache/pip pip install .

# Speech transcription engine. the audio pipeline (run here) uses
# faster-whisper as its STT provider, but it was not in pyproject, so
# transcription was silently disabled. Install it and pre-bake the default
# small.en model so first transcription needs no network. transcription is
# still opt-in per camera (audio_transcribe_enabled) and privacy-sensitive.
RUN --mount=type=cache,target=/root/.cache/pip pip install faster-whisper
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"

COPY shared/ shared/
COPY services/__init__.py services/__init__.py
COPY services/ingestion/ services/ingestion/
# The audio worker and manager pull the rule engine and the perception
# audio pipeline, which transitively import these siblings. Ship them so
# imports resolve at startup. heavy paths load lazily when called.
COPY services/events/ services/events/
COPY services/perception/ services/perception/
COPY services/search/ services/search/
COPY services/discovery/ services/discovery/
COPY services/notify/ services/notify/
COPY services/api/ services/api/
COPY services/recap.py services/recap.py
COPY integrations/ integrations/

CMD ["python", "-m", "services.ingestion.main"]
