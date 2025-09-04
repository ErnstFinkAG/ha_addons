ARG BUILD_FROM=ghcr.io/home-assistant/{arch}-base:latest
FROM $BUILD_FROM

# Avoid pip in system interpreter (PEP 668): use distro packages
RUN apk add --no-cache python3 py3-requests py3-paho-mqtt bash

WORKDIR /app
COPY run.sh /run.sh
COPY mk5s_client.py /app/mk5s_client.py
COPY README.md /app/README.md

# S6 overlay expects executable
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
