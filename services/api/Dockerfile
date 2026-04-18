FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# libgl1/libglib2.0-0: opencv-python-headless runtime
# libpq-dev: psycopg/asyncpg build hint
# build-essential + cmake + pkg-config: required to build dlib (face_recognition)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev \
    build-essential cmake pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install deps first for layer caching. --no-install-project avoids needing the
# source tree in this layer; we copy it below. --frozen pins transitive deps to
# uv.lock so container builds match local `uv sync` resolutions.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra api

COPY shared/ shared/
COPY services/api/ services/api/
COPY services/digest/ services/digest/
COPY services/discovery/ services/discovery/
COPY services/events/ services/events/
COPY services/perception/ services/perception/
COPY services/search/ services/search/
COPY services/streaming/ services/streaming/
COPY services/__init__.py services/__init__.py
COPY alembic/ alembic/
COPY alembic.ini .

CMD ["uv", "run", "--no-sync", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
