#!/usr/bin/with-contenv sh
set -eu

# Read options
HOST=$(jq -r '.host // "10.60.23.11"' /data/options.json)
QUESTION=$(jq -r '.question' /data/options.json)
INTERVAL=$(jq -r '.interval // 10' /data/options.json)

export SUPERVISOR_TOKEN

echo "[mk5s] starting: host=${HOST} interval=${INTERVAL}s"
exec /opt/venv/bin/python /app/mk5s_client.py --host "${HOST}" --question "${QUESTION}" --interval "${INTERVAL}"
