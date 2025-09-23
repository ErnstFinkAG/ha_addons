#!/usr/bin/with-contenv sh
set -e
echo "[atlas] starting container"
exec python3 /app/atlas_copco_parser.py
