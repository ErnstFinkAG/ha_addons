#!/usr/bin/env bash
set -euo pipefail

# Read options.json
HOST=$(jq -r '.host' /data/options.json)
INTERVAL=$(jq -r '.interval' /data/options.json)
TIMEOUT=$(jq -r '.timeout' /data/options.json)
VERBOSE=$(jq -r '.verbose' /data/options.json)

export SUPERVISOR_TOKEN

echo "[mk5s] starting: host=$HOST interval=${INTERVAL}s"

exec /opt/venv/bin/python /app/mk5s_client.py   --host "$HOST"   --interval "$INTERVAL"   --timeout "$TIMEOUT"   $( [ "$VERBOSE" = "true" ] && echo "--verbose" || true )
