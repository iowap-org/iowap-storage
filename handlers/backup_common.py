"""Shared helpers for the storage node backup handlers (T-130/T-131/T-132).

Imported by every ``handlers/backup_*.py`` script. Provides
the JSON-manifest model (one manifest per backup, next to the data — see
DECISIONS 2026-08-06), backup-id minting, path resolution and manifest
read/write helpers. Reuses ``_common._safe_path`` for traversal safety.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow importing _common.py whether run from /app/handlers (Docker) or repo root (tests).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import STORAGE_PATH, _fail, _safe_path  # noqa: E402

# Backups live under <STORAGE_PATH>/backups/<backup_id>/.
BACKUPS_DIR = STORAGE_PATH / "backups"

# Manifest filename inside each backup dir.
MANIFEST_NAME = "manifest.json"

# Valid backup types.
VALID_TYPES = ("full", "incremental")

# Valid statuses.
VALID_STATUSES = ("active", "expired", "deleted")


def _utcnow() -> str:
    """Return an ISO-8601 UTC timestamp (RFC3339, Z-suffix)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def mint_backup_id() -> str:
    """Mint a unique backup id: ``bk_<16 hex>``."""
    return f"bk_{secrets.token_hex(8)}"


def backups_root() -> Path:
    """Return the backups root dir, creating it if needed."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR


def backup_dir(backup_id: str) -> Path:
    """Resolve the on-disk dir for a backup id, rejecting traversal.

    The backup_id is used as a single path segment; a crafted id cannot
    escape the backups root.
    """
    if not backup_id or "/" in backup_id or "\\" in backup_id or backup_id in (".", ".."):
        _fail(f"invalid backup_id: {backup_id!r}")
    return _safe_path(str(backup_id), base=backups_root())


def manifest_path(backup_id: str) -> Path:
    """Return the manifest path for a backup id."""
    return backup_dir(backup_id) / MANIFEST_NAME


def write_manifest(backup_id: str, manifest: dict[str, Any]) -> None:
    """Write a manifest atomically (tmp + rename) next to the data."""
    target = manifest_path(backup_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.replace(target)


def read_manifest(backup_id: str) -> dict[str, Any]:
    """Read a manifest, failing cleanly if missing or invalid."""
    path = manifest_path(backup_id)
    if not path.is_file():
        _fail(f"backup not found: {backup_id}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        _fail(f"corrupt manifest for {backup_id}: {exc.msg}")
    if not isinstance(data, dict):
        _fail(f"corrupt manifest for {backup_id}: not an object")
    return data


def new_manifest(source: str, btype: str, base_backup_id: str | None = None) -> dict[str, Any]:
    """Build a fresh manifest dict with defaults."""
    if btype not in VALID_TYPES:
        _fail(f"invalid type: {btype!r} (expected {', '.join(VALID_TYPES)})")
    return {
        "backup_id": mint_backup_id(),
        "source": source,
        "type": btype,
        "base_backup_id": base_backup_id,
        "created_at": _utcnow(),
        "size_bytes": 0,
        "retention": None,
        "status": "active",
        # T-162: original filename of the uploaded data (preserved so a
        # restore can write it back with the right name/suffix).
        "filename": None,
    }


def open_backup_bridge_route(
    backup_id: str,
    *,
    method: str,
    description: str,
    ttl_seconds: int = 3600,
) -> str:
    """Register a temp bridge route on the relay for a backup's data.bin.

    Used by ``backup.create`` (``method="POST"`` → upload_url) and
    ``backup.restore`` (``method="GET"`` → download_url). The route points
    at this node's bridge server ``/backup/{backup_id}`` (T-129 proxy) so
    the caller streams straight onto/from ``backups/<id>/data.bin`` with no
    channel staging.

    Returns the public URL the caller should use.
    """
    import json as _json

    import httpx  # noqa: PLC0415

    base_url = os.environ.get("RELAY_BASE_URL", "")
    token_file = os.environ.get("RELAY_TOKEN_FILE", "")
    node_id = os.environ.get("RELAY_NODE_ID", "")
    if not base_url or not token_file or not node_id:
        _fail("backup bridge route requires RELAY_BASE_URL, RELAY_TOKEN_FILE, RELAY_NODE_ID")

    from _common import _bridge_upstream_base  # noqa: PLC0415

    token = ""
    try:
        token = Path(token_file).read_text().strip()
    except OSError as exc:
        _fail(f"cannot read RELAY_TOKEN_FILE: {exc}")
    if token.startswith("{"):
        try:
            token = _json.loads(token).get("token", token)
        except _json.JSONDecodeError:
            pass

    upstream_base = _bridge_upstream_base()
    upstream = f"{upstream_base}/backup/{backup_id}"
    path = f"/backup/{backup_id}"

    url = f"{base_url.rstrip('/')}/relay/v2/dashboard/api/node-routes/register"
    r = None
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "path": path,
                "method": method,
                "upstream": upstream,
                "ttl_seconds": ttl_seconds,
                "channel_id": f"bk_{backup_id}",
                "description": description,
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        _fail(f"register request failed: {exc}")
    assert r is not None
    if r.status_code != 200:
        _fail(f"register failed ({r.status_code}): {r.text}")
    return f"{base_url.rstrip('/')}/relay/v2/dashboard/api/node-routes/{node_id}{path}"