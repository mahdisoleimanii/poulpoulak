# syntax=docker/dockerfile:1
# ---- builder ----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install into a prefix we copy into the runtime stage, isolating deps from the
# system Python and producing a lean image.
COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

# ---- runtime ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

# Non-root user for the runtime (req 19: run as non-root).
RUN groupadd --system --gid 1001 dong && \
    useradd  --system --uid 1001 --gid dong --home /app --shell /usr/sbin/nologin dong && \
    mkdir -p /data && chown -R dong:dong /data

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=dong:dong bot ./bot

USER dong
VOLUME ["/data"]
EXPOSE 8080

CMD ["python", "-m", "bot.main"]