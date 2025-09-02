# syntax=docker/dockerfile:1
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# Install deps
RUN apk add --no-cache python3 py3-pip jq curl bash

# Create virtualenv (avoid PEP 668 system-protected environment)
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements & install into venv
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY run.sh /run.sh
COPY mk5s_client.py /app/mk5s_client.py

# Make scripts executable
RUN chmod +x /run.sh

# Entrypoint
CMD ["/run.sh"]
