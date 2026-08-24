"""Shared helpers for the storage handlers (T-127).

Imported by every ``handlers/*.py`` script. Provides the
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


def _note(message: str, kind: str = "info") -> None:
    """Best-effort progress note to the relay (T-154/T-160).

    Reads the task context from the environment (set by ``node_daemon``
    when it launches the handler: ``RELAY_TASK_ID``, ``RELAY_BASE_URL``,
    ``RELAY_TOKEN_FILE``). Sends ``POST /relay/v2/scheduler/tasks/{id}/notes``
    with a Bearer token. Every note resets the Long-Run stage TTL on the
    relay, so a long archive/extract that reports progress keeps its
    2h lease alive.

    Fully fail-tolerant: any missing env, HTTP error or exception is
    swallowed — a progress note must never block or fail the pack. Without
    a ``RELAY_TASK_ID`` this is a silent no-op (e.g. local handler runs).
    """
    task_id = os.environ.get("RELAY_TASK_ID", "").strip()
    base_url = os.environ.get("RELAY_BASE_URL", "").strip()
    token_file = os.environ.get("RELAY_TOKEN_FILE", "").strip()
    if not task_id or not base_url or not token_file:
        return
    try:
        token = Path(token_file).read_text().strip()
        if token.startswith("{"):
            token = json.loads(token).get("token", token)
    except (OSError, json.JSONDecodeError):
        return
    try:
        import httpx  # noqa: PLC0415

        url = f"{base_url.rstrip('/')}/relay/v2/scheduler/tasks/{task_id}/notes"
        httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message, "kind": kind},
            timeout=15,
        )
    except Exception:  # noqa: BLE001 — best-effort, never break the pack
        pass


def _ensure_base() -> None:
    """Create the storage base directory if it does not exist yet."""
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)


def _safe_filename(name: str | None) -> str:
    """Sanitize a caller-supplied filename to a single safe path segment.

    Strips any directory components and control chars so a crafted
    filename (from an ``X-Filename`` header or a task payload) cannot
    escape its target directory. Returns an empty string when nothing
    usable remains (the caller falls back to a default name).
    """
    if not name:
        return ""
    name = str(name).strip().replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    # Reject empty, dotfiles, and anything with remaining separators.
    if not base or base in (".", "..") or "/" in base or "\x00" in base:
        return ""
    return base
