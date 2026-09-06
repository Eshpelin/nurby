FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg \
    cmake build-essential libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY shared/ shared/
# The agent tool registry transitively imports the analyzer, which pulls
# perception + search + events + notify. Ship the same light-at-import
# subtrees the api image does so every tool the registry can dispatch
# resolves. Heavy paths (torch/insightface/clip) only load when an
# analyze_* tool is actually called.
# One copy of the whole services tree. The previous per-package
# list drifted from what those packages import: services/voice was
# never added and the image could not start (#181). The packages are
# pure Python and this image already carried most of them, so the
# cost is a slightly larger layer against a whole class of bug.
COPY services/ services/
# FindAnything grounding: search/events import it at runtime.

CMD ["python", "-m", "services.mcp.server"]
