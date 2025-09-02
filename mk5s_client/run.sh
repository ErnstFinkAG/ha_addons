#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

if [[ -f "$OPTIONS_FILE" ]]; then
  HOST=$(jq -r '.host' "$OPTIONS_FILE")
  INTERVAL=$(jq -r '.interval' "$OPTIONS_FILE")
  TIMEOUT=$(jq -r '.timeout' "$OPTIONS_FILE")
  VERBOSE=$(jq -r '.verbose' "$OPTIONS_FILE")
else
  # fallbacks (shouldn't happen in Supervisor)
  HOST="10.60.23.11"
  INTERVAL=10
  TIMEOUT=5
  VERBOSE=true
fi

echo "[mk5s] starting: host=${HOST} interval=${INTERVAL}s"
exec python /app/mk5s_client.py   --host "${HOST}"   --interval "${INTERVAL}"   --timeout "${TIMEOUT}"   $( [[ "${VERBOSE}" == "true" ]] && echo "--verbose" || true )
