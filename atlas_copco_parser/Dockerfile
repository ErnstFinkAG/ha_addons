ARG BUILD_FROM=ghcr.io/home-assistant/{arch}-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-requests py3-paho-mqtt

WORKDIR /app

COPY run.sh /run.sh
COPY mk5s_client.py /app/mk5s_client.py
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
