ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache     python3     py3-requests     jq     curl     ca-certificates

WORKDIR /app
COPY run.sh /run.sh
COPY mk5s_client.py /app/mk5s_client.py
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
