"""Shared helpers for the storage node backup handlers (T-130/T-131/T-132).

Imported by every ``docker/nodes/storage/handlers/backup_*.py`` script. Provides
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
    }