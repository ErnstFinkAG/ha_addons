ARG BUILD_FROM=ghcr.io/home-assistant/{arch}-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-requests py3-paho-mqtt

WORKDIR /app

COPY run.sh /run.sh
COPY atlas_copco_parser.py /app/atlas_copco_parser.py
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
