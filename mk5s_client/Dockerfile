ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install Python and curl
RUN apk add --no-cache python3 py3-pip curl

# Copy files
WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY run.sh /
RUN chmod +x /run.sh
COPY mk5s_client.py /app/

# Create data dir for logs
RUN mkdir -p /data

CMD [ "/run.sh" ]
