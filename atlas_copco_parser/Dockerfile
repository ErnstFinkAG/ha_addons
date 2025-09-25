FROM python:3.11-slim

WORKDIR /app

COPY main.py .
COPY run.sh .

RUN pip install --no-cache-dir paho-mqtt \
    && chmod +x /app/run.sh

CMD ["/app/run.sh"]
