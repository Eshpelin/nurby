# syntax=docker/dockerfile:1
#
# FindAnything / visual grounding inference service (LocateAnything-3B).
#
# Unlike the other Nurby services this one is GPU-only: the model needs a
# datacenter NVIDIA card (Ampere/Hopper/Lovelace/Blackwell) and BF16. It is
# built and started behind the `grounding` compose profile, so a plain
# `docker compose up` never pulls this multi-GB image. Weights are NOT baked
# in (gated + ~6GB); they are fetched once on first use from the Nurby mirror
# (GROUNDING_MIRROR_URL) into a persistent volume, then the runtime is offline.
FROM python:3.12-slim

WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=120
ENV HF_HUB_OFFLINE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CUDA torch (this service has a real GPU, so we want the GPU wheel, not the
# CPU one the other services use).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision
# Pinned set (notably transformers==4.57.1 — newer majors break the model's
# custom modeling code). See services/grounding/requirements.txt.
COPY services/grounding/requirements.txt /tmp/grounding-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/grounding-requirements.txt

COPY shared/ shared/
COPY services/__init__.py services/__init__.py
COPY services/grounding/ services/grounding/

# Persistent weights volume (mounted by compose).
ENV GROUNDING_WEIGHTS_DIR=/data/grounding
VOLUME ["/data/grounding"]
EXPOSE 8800

CMD ["python", "-m", "services.grounding.server"]
