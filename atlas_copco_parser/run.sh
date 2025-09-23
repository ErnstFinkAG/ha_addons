#!/usr/bin/with-contenv sh
set -e
echo "[atlas] starting container"
exec python3 /app/mk5s_client.py
