#!/usr/bin/with-contenv bash
set -euo pipefail

OPTS_FILE=/data/options.json

HOST_DEFAULT="10.60.23.11"
INTERVAL_DEFAULT=10
TIMEOUT_DEFAULT=5
VERBOSE_DEFAULT=true

read_opt() {
  local key="$1" def="$2"
  local val
  if [[ -f "$OPTS_FILE" ]]; then
    val="$(jq -r --arg k "$key" '.[$k] // empty' "$OPTS_FILE" 2>/dev/null || true)"
  else
    val=""
  fi
  if [[ -z "$val" || "$val" == "null" ]]; then
    echo "$def"
  else
    echo "$val"
  fi
}

host="$(read_opt host "$HOST_DEFAULT")"
interval="$(read_opt interval "$INTERVAL_DEFAULT")"
timeout="$(read_opt timeout "$TIMEOUT_DEFAULT")"
verbose="$(read_opt verbose "$VERBOSE_DEFAULT")"

echo "[mk5s] starting: host=${host} interval=${interval}s"
exec /usr/bin/python3 /app/mk5s_client.py   --host "${host}"   --interval "${interval}"   --timeout "${timeout}"   $( [ "$verbose" = "true" ] && echo "--verbose" )
