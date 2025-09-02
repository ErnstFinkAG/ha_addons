#!/usr/bin/env bash
set -euo pipefail

# Read options
if [[ -f /data/options.json ]]; then
  HOST="$(jq -r '.host' /data/options.json)"
  SCAN_INTERVAL="$(jq -r '.scan_interval // 15' /data/options.json)"
  REQ_TIMEOUT="$(jq -r '.request_timeout // 5' /data/options.json)"
  LOG_RAW="$(jq -r '.log_raw_frames // true' /data/options.json)"
else
  HOST="10.60.23.11"
  SCAN_INTERVAL="15"
  REQ_TIMEOUT="5"
  LOG_RAW="true"
fi

export MK5S_HOST="${HOST}"
export MK5S_SCAN_INTERVAL="${SCAN_INTERVAL}"
export MK5S_REQUEST_TIMEOUT="${REQ_TIMEOUT}"
export MK5S_LOG_RAW="${LOG_RAW}"

echo "[mk5s] starting… host=${MK5S_HOST} interval=${MK5S_SCAN_INTERVAL}s timeout=${MK5S_REQUEST_TIMEOUT}s log_raw=${MK5S_LOG_RAW}"

exec python3 /app/mk5s_client.py
