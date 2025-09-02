ARG BUILD_FROM
FROM $BUILD_FROM

# Add minimal tools
RUN apk add --no-cache python3 py3-pip curl jq

# Create and use a virtual environment (PEP 668 safe)
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
COPY requirements.txt /app/

# Install python deps into venv
RUN pip install --no-cache-dir -r /app/requirements.txt

# App + entry
COPY mk5s_client.py /app/
COPY run.sh /
RUN chmod +x /run.sh

CMD [ "/run.sh" ]
