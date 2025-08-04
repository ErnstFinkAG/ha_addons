FROM python:3.12-alpine

COPY mqtt_tcp_bridge.py /mqtt_tcp_bridge.py
COPY requirements.txt /requirements.txt

RUN pip install --no-cache-dir -r /requirements.txt

CMD ["python3", "/mqtt_tcp_bridge.py"]
