#!/usr/bin/with-contenv sh
set -e
echo "[mk5s] starting container"
exec python3 /app/atlas_copco_parser.py
