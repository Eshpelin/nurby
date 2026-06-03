FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libpq-dev ffmpeg ca-certificates \
    cmake build-essential libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

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
