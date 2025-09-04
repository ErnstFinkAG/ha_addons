#!/usr/bin/env bash
set -euo pipefail

echo "[mk5s] starting add-on"
exec python3 /app/mk5s_client.py
