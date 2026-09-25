# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

ENV PIP_DEFAULT_TIMEOUT=120

# Exact build commit, surfaced by /api/system/version. Set by CI on
# release; harmless when unset for local builds.
ARG NURBY_BUILD_SHA=""
ENV NURBY_BUILD_SHA=$NURBY_BUILD_SHA

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg \
    postgresql-client \
    cmake build-essential libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# CPU-only torch first (no GPU here). avoids the ~426MB CUDA wheel that
# stalls on slow networks; the main install reuses the satisfied torch.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN --mount=type=cache,target=/root/.cache/pip pip install .

COPY shared/ shared/
# One copy of the whole services tree. The previous per-package
# list drifted from what those packages import: services/voice was
# never added and the image could not start (#181). The packages are
# pure Python and this image already carried most of them, so the
# cost is a slightly larger layer against a whole class of bug.
COPY services/ services/
# Several api routes pull helpers from sibling services. Ship them so
# the api process can import them. Each module is light at import time;
# heavy paths (torch/torchreid/insightface) only load when their
# functions are called.
# FindAnything grounding: search/scan.py and events/actions.py import it.
# Device alert presets. routes/devices.py imports integrations.devices.
COPY integrations/ integrations/
COPY alembic/ alembic/
COPY alembic.ini .
COPY VERSION .

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
