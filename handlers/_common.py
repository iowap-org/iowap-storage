"""Shared helpers for the storage handlers (T-127).

Imported by every ``docker/nodes/storage/handlers/*.py`` script. Provides the
``_safe_path`` path-traversal guard (ported byte-for-byte from the legacy
``storage_node.py`` — see REFERENCE_safe_path.md), stdin/stdout JSON
helpers and a small ``_emit``/``_fail`` pair that respects the
``handler_runner`` contract (exit != 0 on error).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Base directory for all storage paths. Override via env for tests/local
# runs; the Dockerfile sets STORAGE_PATH=/storage.
STORAGE_PATH = Path(os.environ.get("RELAY_STORAGE_PATH", "/storage"))


def _local_ip() -> str:
    """Best-effort local IPv4 of this host (no packets sent).

    Uses the classic UDP-connect trick: connecting a UDP socket to a
    non-routable address makes the kernel pick the outbound interface
    without sending anything. Falls back to ``127.0.0.1``.
    """
    import socket  # noqa: PLC0415

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def _bridge_upstream_base() -> str:
    """Resolve the bridge-server upstream base the relay should reach.

    Prefers an explicit ``NODE_ENDPOINT`` (operator override), else derives
    the node's own reachable IP + ``BRIDGE_PORT``. This removes the need to
    set ``NODE_ENDPOINT`` in the docker env — the node knows its own IP.
    """
    node_endpoint = os.environ.get("NODE_ENDPOINT", "").strip()
    if node_endpoint:
        return node_endpoint.rstrip("/")
    port = os.environ.get("BRIDGE_PORT", "8791")
    return f"http://{_local_ip()}:{port}"


def _safe_path(target_path: str | None, base: Path = STORAGE_PATH) -> Path:
    """Resolve ``target_path`` relative to ``base`` and reject escapes.

    The target may contain subdirectories (e.g. ``projects/2026/file.png``)
    but must stay inside ``base`` after resolving symlinks and ``..``
    segments. Raises :class:`ValueError` on a traversal attempt so the
    caller can turn it into a clean ``{"error": "..."}`` result.

    Ported byte-for-byte from the legacy storage_node.py (T-121) — this
    is the security boundary for every storage handler.
    """
    resolved_base = base.resolve()
    candidate = (resolved_base / (target_path or "")).resolve()
    try:
        candidate.relative_to(resolved_base)
    except ValueError as exc:
        raise ValueError("path traversal attempt") from exc
    return candidate


def _read_payload() -> dict[str, Any]:
    """Read the stage payload JSON from stdin and return it as a dict."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"invalid JSON payload: {exc.msg}")
    if not isinstance(data, dict):
        _fail("payload must be a JSON object")
    return data


def _emit(result: dict[str, Any]) -> None:
    """Write the result dict as JSON to stdout and exit 0."""
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    sys.exit(0)


def _fail(msg: str) -> None:
    """Write ``{"error": msg}`` to stdout and exit 1 (handler failure)."""
    sys.stdout.write(json.dumps({"error": msg}))
    sys.stdout.flush()
    sys.exit(1)


def _require(payload: dict[str, Any], key: str) -> Any:
    """Return ``payload[key]`` or fail with a clean error if missing."""
    if key not in payload or payload[key] is None:
        _fail(f"missing required field: {key}")
    return payload[key]


def _ensure_base() -> None:
    """Create the storage base directory if it does not exist yet."""
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)
