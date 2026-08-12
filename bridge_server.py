"""Storage-node bridge server (T-128).

A small Starlette HTTP server the storage node runs alongside the
node-daemon. The relay proxies upload/download channel requests to this
server through a temporary bridge route (T-124). The server's only job:

* accept POST /upload/{channel_id}  — stream the request body onto the
  NAS under ``/storage/channels/<channel_id>``.
* accept GET  /download/{channel_id} — stream a previously stored file
  back to the caller.

Security: every request's source IP is validated against the relay
server's IP (the only legitimate caller). The server IP is resolved at
startup from the ``RELAY_URL`` hostname (DNS) and cached, so a
Tailscale/mDNS deployment resolves to the Tailscale IP. An explicit
``RELAY_SERVER_IP`` env overrides the resolution. A non-matching source
IP gets 403 — no shared secret, no mTLS, just the network topology.

The server is intentionally framework-light (Starlette only) so the
storage image stays small; the node stack already pulls Starlette via
FastAPI.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Iterator
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

log = logging.getLogger("bridge-server")

# Base directory for channel files (under the storage tree).
STORAGE_PATH = Path(os.environ.get("RELAY_STORAGE_PATH", "/storage"))
CHANNELS_DIR = STORAGE_PATH / "channels"
BACKUPS_DIR = STORAGE_PATH / "backups"
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8791"))

# Chunk size for streaming reads/writes — keep memory bounded for large
# files (the whole point of the bridge channel vs. artifact upload).
_CHUNK = 64 * 1024


# ---------------------------------------------------------------------------
# Server-IP resolution
# ---------------------------------------------------------------------------


def _resolve_server_ip() -> str | None:
    """Resolve the relay server IP from RELAY_URL (or RELAY_SERVER_IP).

    Returns the first IPv4 the hostname resolves to, or ``None`` when
    resolution fails (the caller logs a warning and the allowlist is
    effectively empty — every request is 403, fail-closed).
    """
    explicit = os.environ.get("RELAY_SERVER_IP")
    if explicit and explicit.strip():
        return explicit.strip()
    relay_url = os.environ.get("RELAY_URL") or os.environ.get("RELAY_BASE_URL")
    if not relay_url:
        return None
    host = urlparse(relay_url).hostname
    if not host:
        return None
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    for fam, _type, _proto, _canon, sockaddr in infos:  # noqa: B007
        if fam == socket.AF_INET:
            return sockaddr[0]
    return None


# ---------------------------------------------------------------------------
# Source-IP allowlist middleware
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    """Return the request's source IP.

    Honours ``X-Forwarded-For`` only when an operator opts in via
    ``RELAY_TRUST_FORWARDED_FOR=1`` — by default the bridge server runs
    on a private docker/Tailscale network where the relay is the
    direct TCP peer, so the socket peer is authoritative. Trusting XFF
    by default would let any caller spoof the allowlist.
    """
    if os.environ.get("RELAY_TRUST_FORWARDED_FOR") == "1":
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    if request.client is None:
        return ""
    return request.client.host


class SourceIPAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject any request whose source IP is not the relay server.

    The allowed IP is resolved once at construction (startup) and cached
    for the process lifetime; a DNS change requires a restart. When the
    IP is unknown (resolution failed), every request is 403 — fail-closed
    so a misconfigured storage node never serves an open proxy.
    """

    def __init__(self, app, allowed_ip: str | None) -> None:
        super().__init__(app)
        self.allowed_ip = allowed_ip

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if self.allowed_ip is None:
            log.warning(
                "bridge server has no allowed server IP — rejecting request from %s",
                _client_ip(request),
            )
            return JSONResponse(
                {"error": "bridge server allowlist not configured"}, status_code=403
            )
        ip = _client_ip(request)
        if ip != self.allowed_ip:
            log.warning("rejected bridge request from %s (allowed: %s)", ip, self.allowed_ip)
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _channel_path(channel_id: str) -> Path:
    """Resolve the on-disk path for a channel file.

    The channel_id is used directly as a single path segment (it is a
    server-minted opaque id) and placed under ``channels/``. We reject
    any id that is not a plain filename so a crafted id cannot escape
    the channels dir.
    """
    if not channel_id or "/" in channel_id or "\\" in channel_id or channel_id in (".", ".."):
        raise ValueError("invalid channel_id")
    CHANNELS_DIR.mkdir(parents=True, exist_ok=True)
    return CHANNELS_DIR / channel_id


def _backup_data_path(backup_id: str) -> Path:
    """Resolve the on-disk ``data.bin`` path for a backup id.

    The backup_id is used as a single path segment under ``backups/``
    (mirrors ``backup_common.backup_dir``). Rejects any id that is not a
    plain segment so a crafted id cannot escape the backups root.
    """
    if not backup_id or "/" in backup_id or "\\" in backup_id or backup_id in (".", ".."):
        raise ValueError("invalid backup_id")
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR / backup_id / "data.bin"


async def upload_channel(request: Request) -> Response:
    """POST /upload/{channel_id} — stream the body onto the NAS."""
    channel_id = request.path_params["channel_id"]
    try:
        target = _channel_path(channel_id)
    except ValueError:
        return JSONResponse({"error": "invalid channel_id"}, status_code=400)

    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    # Stream the body to disk chunkwise — never hold the whole file in RAM.
    with target.open("wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            total += len(chunk)
    return JSONResponse({"status": "stored", "channel_id": channel_id, "size_bytes": total})


async def download_channel(request: Request) -> Response:
    """GET /download/{channel_id} — stream a stored channel file back."""
    channel_id = request.path_params["channel_id"]
    try:
        target = _channel_path(channel_id)
    except ValueError:
        return JSONResponse({"error": "invalid channel_id"}, status_code=400)

    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    size = target.stat().st_size

    async def _iter() -> "AsyncIterator[bytes]":
        # T-156: async generator (NOT sync). A sync generator in a
        # StreamingResponse breaks under an httpx/uvicorn proxy — the
        # upstream stream aborts with httpx.ReadError and the caller sees
        # a Content-Length header but an empty body. An async generator
        # streams cleanly through the relay proxy.
        with target.open("rb") as f:
            while True:
                buf = f.read(_CHUNK)
                if not buf:
                    break
                yield buf

    return StreamingResponse(
        _iter(),
        media_type="application/octet-stream",
        headers={"Content-Length": str(size)},
    )


async def upload_backup(request: Request) -> Response:
    """POST /backup/{backup_id} — stream the body straight onto a backup's data.bin.

    Mirrors ``upload_channel`` but targets ``backups/<id>/data.bin`` so a
    large backup streams directly to its final location (no channel
    staging / copy). The manifest is written separately by
    ``backup.create``; here we only fill the data file.
    """
    backup_id = request.path_params["backup_id"]
    try:
        target = _backup_data_path(backup_id)
    except ValueError:
        return JSONResponse({"error": "invalid backup_id"}, status_code=400)

    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with target.open("wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
            total += len(chunk)
    return JSONResponse({"status": "stored", "backup_id": backup_id, "size_bytes": total})


async def download_backup(request: Request) -> Response:
    """GET /backup/{backup_id} — stream a backup's data.bin back to the caller."""
    backup_id = request.path_params["backup_id"]
    try:
        target = _backup_data_path(backup_id)
    except ValueError:
        return JSONResponse({"error": "invalid backup_id"}, status_code=400)

    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    size = target.stat().st_size

    async def _iter() -> "AsyncIterator[bytes]":
        with target.open("rb") as f:
            while True:
                buf = f.read(_CHUNK)
                if not buf:
                    break
                yield buf

    return StreamingResponse(
        _iter(),
        media_type="application/octet-stream",
        headers={"Content-Length": str(size)},
    )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(allowed_ip: str | None = None) -> Starlette:
    """Build the bridge server app.

    ``allowed_ip`` is the relay server IP the allowlist checks against.
    When None the caller should pass ``_resolve_server_ip()``; tests pass
    a fixed value to keep the suite hermetic.
    """
    routes = [
        Route("/upload/{channel_id}", upload_channel, methods=["POST"]),
        Route("/download/{channel_id}", download_channel, methods=["GET"]),
        Route("/backup/{backup_id}", upload_backup, methods=["POST"]),
        Route("/backup/{backup_id}", download_backup, methods=["GET"]),
    ]
    middleware = [Middleware(SourceIPAllowlistMiddleware, allowed_ip=allowed_ip)]
    return Starlette(routes=routes, middleware=middleware)


def main() -> None:
    """Entry point: resolve the server IP, build the app, run on uvicorn."""
    import uvicorn  # noqa: PLC0415 — lazy import so the test path does not require uvicorn

    logging.basicConfig(level=os.environ.get("RELAY_LOG_LEVEL", "INFO"))
    allowed = _resolve_server_ip()
    if allowed is None:
        log.warning(
            "could not resolve relay server IP from RELAY_URL — bridge server will reject all requests "
            "(set RELAY_SERVER_IP explicitly if needed)"
        )
    else:
        log.info("bridge server allowing relay server IP: %s", allowed)
    app = create_app(allowed_ip=allowed)
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT, log_level="warning")


if __name__ == "__main__":
    main()
