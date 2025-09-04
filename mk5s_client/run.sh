#!/usr/bin/with-contenv sh
set -e
echo "[mk5s] starting container"
exec python3 /app/mk5s_client.py
