ARG BUILD_FROM
FROM $BUILD_FROM

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Add runtime deps
RUN apk add --no-cache python3 py3-pip bash jq curl

# Create & activate a virtualenv (avoid PEP 668 issues)
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"  && "$VIRTUAL_ENV/bin/pip" install --no-cache-dir --upgrade pip  && ln -s "$VIRTUAL_ENV/bin/pip" /usr/local/bin/pip  && ln -s "$VIRTUAL_ENV/bin/python" /usr/local/bin/python

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY run.sh /run.sh
COPY mk5s_client.py /app/mk5s_client.py
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
