#!/usr/bin/env bash
# IOWAP — storage node entrypoint (T-128).
#
# Starts the bridge server (T-128) in the background, then chains into
# the base image's docker-entrypoint.sh which sets up relay_config.json
# + node.yaml, registers the node on first start, and execs node-daemon
# (SSE, event-driven). tini (PID 1) reaps the background bridge process.
#
# The bridge server resolves the relay server IP from RELAY_URL at
# startup (DNS) and only accepts requests from that IP, so a bind to
# 0.0.0.0:8791 is safe — only the relay can reach it.
#
# Environment variables (besides the base ones):
#   RELAY_SERVER_IP — explicit relay server IP override (skips DNS)
#   RELAY_TRUST_FORWARDED_FOR — set to "1" to honour X-Forwarded-For

set -euo pipefail

# Start the bridge server in the background. It inherits the env so
# RELAY_URL / RELAY_STORAGE_PATH / RELAY_SERVER_IP are visible.
echo "[storage-entrypoint] starting bridge server on 0.0.0.0:${BRIDGE_PORT:-8791}"
python3 /app/bridge_server.py &

# Start the retention watchdog in the background (T-132). It applies
# configured retention policies from ~/.relay/retention.yaml periodically.
echo "[storage-entrypoint] starting retention watchdog"
python3 /app/retention_watchdog.py &

# Hand off to the base entrypoint, which execs node-daemon as PID 1's
# foreground child (tini reaps the bridge background process).
exec /app/docker-entrypoint.sh "$@"