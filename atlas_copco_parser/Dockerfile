ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

# Add bash, python, pip
RUN apk add --no-cache python3 py3-pip bash curl

# Copy files
WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

COPY atlas_copco_parser.py ./
COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
