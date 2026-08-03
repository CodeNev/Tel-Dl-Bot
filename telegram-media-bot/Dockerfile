# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and buffering stdout, which keeps
# Railway's log stream real-time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg is required for merging separate audio/video streams; git is used by
# yt-dlp for some extractor update checks.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Directories used for cache and temporary downloads at runtime.
RUN mkdir -p /tmp/cache /tmp/downloads

# Run as a non-root user for defense in depth.
RUN useradd --create-home --shell /bin/bash botuser && \
    chown -R botuser:botuser /app /tmp/cache /tmp/downloads
USER botuser

CMD ["python", "main.py"]
