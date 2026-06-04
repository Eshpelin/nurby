# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Pip downloads (notably the ~426MB torch wheel) are cached in a BuildKit
# cache mount so a killed or retried build resumes instead of re-pulling
# the whole ML stack. Bump the network timeout for flaky/slow mirrors.
ENV PIP_DEFAULT_TIMEOUT=120

# ffmpeg is required for the conversation-anchored clip builder
# (slices an mp4 covering the conversation window from the matching
# Recording row). libgl/libglib are needed by opencv-python-headless
# which the perception pipeline pulls for frame decoding.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg ca-certificates \
    cmake build-essential libboost-all-dev \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install CPU-only torch first, from PyTorch's own CDN. these containers
# have no GPU (InsightFace, faster-whisper, and YOLO all run on CPU), so
# the default CUDA torch wheel is ~426MB of unused GPU libs that also
# stalled repeatedly on slow networks. The CPU wheel is ~190MB and once
# torch is satisfied, the main install below won't pull it again.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN --mount=type=cache,target=/root/.cache/pip pip install .

# Pre-bake the default YOLO weights into the image. Without this, the
# first detection downloads yolov8n.pt from GitHub at runtime, which
# fails on offline or locked-down hosts and adds first-frame latency.
# WORKDIR is /app and the detector runs from /app, so a bare filename
# resolves to this cached file. no network needed at runtime.
RUN PYTHONHTTPSVERIFY=0 python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" || echo "prebake skipped (downloads at first runtime use)"

# Face recognition engine. faces.py uses InsightFace (buffalo_l ArcFace)
# over onnxruntime, but these are not in pyproject, so face recognition
# (and the People tab) was silently disabled in the image. Install here
# (perception-only, to keep api/ingestion lean) and pre-bake the model so
# first use needs no network. without the pre-bake the model downloads at
# runtime and fails on offline / locked-down hosts.
RUN --mount=type=cache,target=/root/.cache/pip pip install insightface onnxruntime
RUN PYTHONHTTPSVERIFY=0 python -c "from insightface.app import FaceAnalysis; a=FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); a.prepare(ctx_id=0, det_size=(640, 640))" || echo "prebake skipped (downloads at first runtime use)"

# License-plate OCR engine. plates.py uses EasyOCR but it was not in
# pyproject, so plate reading (and the Vehicles feature) was disabled in
# the image. Install it and pre-download the detection + recognition
# models so first read needs no network.
RUN --mount=type=cache,target=/root/.cache/pip pip install easyocr
RUN PYTHONHTTPSVERIFY=0 python -c "import easyocr; easyocr.Reader(['en'], gpu=False, verbose=False)" || echo "prebake skipped (downloads at first runtime use)"

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
