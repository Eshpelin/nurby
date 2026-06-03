FROM python:3.12-slim

WORKDIR /app

# ffmpeg is required for the conversation-anchored clip builder
# (slices an mp4 covering the conversation window from the matching
# Recording row). libgl/libglib are needed by opencv-python-headless
# which the perception pipeline pulls for frame decoding.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg ca-certificates \
    cmake build-essential libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Pre-bake the default YOLO weights into the image. Without this, the
# first detection downloads yolov8n.pt from GitHub at runtime, which
# fails on offline or locked-down hosts and adds first-frame latency.
# WORKDIR is /app and the detector runs from /app, so a bare filename
# resolves to this cached file. no network needed at runtime.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY shared/ shared/
COPY services/__init__.py services/__init__.py
COPY services/perception/ services/perception/
COPY services/search/ services/search/
COPY services/api/ services/api/
# The pipeline and audio path import the rule engine and these siblings.
# Ship them so imports resolve at startup. heavy paths load lazily.
COPY services/events/ services/events/
COPY services/discovery/ services/discovery/
COPY services/notify/ services/notify/
COPY services/recap.py services/recap.py
COPY integrations/ integrations/

CMD ["python", "-m", "services.perception.main"]
