# syntax=docker/dockerfile:1
# IOWAP — Storage service node image (T-120).
#
# Builds ``FROM ai-relay-node-base`` and only adds the storage node's
# ``node.yaml`` (capability declarations) + ``handlers/`` directory. The
# whole node stack (node-daemon, relay_client, handler_runner, ...) is
# already installed in the base image, so this Dockerfile has no Python
# install step — it is a thin layer on top of the base.
#
# The handlers themselves are stubs that return ``{"error": "not implemented
# yet"}`` (Plan A). The real storage handlers (storage.store/fetch/delete/
# list/quota/stat/move, storage.upload_channel/download_channel, backup.*)
# land in Plan B (Phase 30). The stubs let the node register + heartbeat so
# the relay-side plumbing (bridge routes, discovery) can be exercised end
# to end without a working handler.
#
# Build context is the repo root (like docker/server and docker/nodes/base) so
# the base image reference can be overridden via a build arg for CI.

# The base image name. Override with --build-arg NODE_BASE_IMAGE=... when
# a different registry/tag is used. Default matches what `docker build -t
# ai-relay-node-base ...` produces locally.
ARG NODE_BASE_IMAGE=iowap-node-base:latest
FROM ${NODE_BASE_IMAGE}

# The storage node serves its bridge-route upstream on this port (the relay
# proxies upload/download channel requests here). The port is informational
# only — the container does not expose it to the host; the relay reaches it
# over the docker network.
ENV NODE_PORT=8791 \
    STORAGE_PATH=/storage

WORKDIR /app

# Copy the storage node's capability profile + handlers. The profile is
# placed in the IMAGE (not the persistent ~/.relay volume) so an image
# update ships a fresh capability set; the base entrypoint copies it to
# ~/.relay/node.yaml on every start (T-163: long_run flag was missing on
# the QNAP node because the old profile lived in the persistent volume).
COPY --chown=appuser:appuser docker/nodes/storage/node.yaml /app/profiles/storage.yaml
COPY --chown=appuser:appuser docker/nodes/storage/handlers/ /app/handlers/
# The bridge server (T-128) is the HTTP server the relay proxies
# upload/download channel requests to. It runs alongside node-daemon.
COPY --chown=appuser:appuser docker/nodes/storage/bridge_server.py /app/bridge_server.py
# The retention watchdog (T-132) applies configured retention policies
# periodically. It runs alongside node-daemon + bridge server.
COPY --chown=appuser:appuser docker/nodes/storage/retention_watchdog.py /app/retention_watchdog.py
# Storage entrypoint launches the bridge server in the background, then
# execs the base entrypoint (which execs node-daemon). Both processes
# share the container; tini (PID 1) reaps the background child.
COPY --chown=appuser:appuser docker/nodes/storage/docker-entrypoint-storage.sh /app/docker-entrypoint-storage.sh

# Publish the storage profile on startup so node.yaml carries the storage
# capabilities, and tell the base entrypoint the node role is "service".
# Default NODE_NAME so the node shows up as "storage-node" in the dashboard
# instead of the container hostname (which may be an opaque container id).
ENV NODE_NAME=storage-node \
    NODE_PROFILE=storage \
    NODE_ROLE=service \
    BRIDGE_PORT=8791

# Where the storage handlers read/write files. Bind-mount this to your NAS
# export. Created at runtime by the handlers; we pre-create it so a bind
# mount lands on an existing dir owned by appuser. The base image already
# switched to USER appuser, so we temporarily become root to create /storage
# (a root-owned path), then drop back to appuser.
USER root
RUN mkdir -p "${STORAGE_PATH}" && chown -R appuser:appuser "${STORAGE_PATH}"
USER appuser

# Healthcheck inherited from the base image (reads the daemon status file).
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python3", "/app/healthcheck.py"]

# Override the base entrypoint with the storage entrypoint (which starts
# the bridge server then chains into the base entrypoint + node-daemon).
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint-storage.sh"]
CMD ["node-daemon"]