FROM python:3.11-slim

WORKDIR /app

COPY mk5s_client.py .
COPY run.sh .

RUN pip install --no-cache-dir paho-mqtt requests \
    && chmod +x /app/run.sh

CMD ["/app/run.sh"]
