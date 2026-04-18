FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# libgl1/libglib2.0-0: opencv-python-headless runtime
# libpq-dev: asyncpg build hint
# ffmpeg: RTSP/codec support for the stream worker
# No build toolchain needed: ingestion has no native build deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching. --frozen pins transitive deps to
# uv.lock so container builds match local `uv sync` resolutions.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra ingestion

COPY shared/ shared/
COPY services/ingestion/ services/ingestion/
COPY services/__init__.py services/__init__.py

CMD ["uv", "run", "--no-sync", "python", "-m", "services.ingestion.main"]
