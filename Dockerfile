FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TUNEUP_MODEL_DIR=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY scripts/fetch-models.sh /usr/local/bin/fetch-models.sh
RUN sh /usr/local/bin/fetch-models.sh /models

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[analysis]"

ENTRYPOINT ["tuneup-tag"]
CMD ["--help"]
