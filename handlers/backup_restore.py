#!/usr/bin/env python3
"""backup.restore handler — return a backup's data (T-131).

Small backups are returned inline as ``data_base64``. Large backups would
use a bridge download route (T-129) — for V1 the inline path covers the
Homelab use case; a ``download_url`` is returned when the data file is
too large for an inline payload.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _read_payload, _require  # noqa: E402
from backup_common import backup_dir, open_backup_bridge_route, read_manifest  # noqa: E402

# Inline payload cap — above this we'd need a bridge route (future).
_INLINE_CAP = 10 * 1024 * 1024  # 10 MB


def main() -> None:
    payload = _read_payload()
    backup_id = str(_require(payload, "backup_id"))
    manifest = read_manifest(backup_id)
    if manifest.get("status") == "deleted":
        _fail(f"backup deleted: {backup_id}")

    data_file = backup_dir(backup_id) / "data.bin"
    if not data_file.is_file():
        _fail(f"backup data missing: {backup_id}")
    size = data_file.stat().st_size
    # T-162: original filename preserved in the manifest (may be None for
    # backups created before this field existed).
    filename = manifest.get("filename")
    if size > _INLINE_CAP:
        # Large backup — open a temp bridge route so the caller streams
        # the data.bin directly (no inline base64, no artifact staging).
        download_url = open_backup_bridge_route(
            backup_id,
            method="GET",
            description="backup.restore bridge download (T-154)",
        )
        _emit(
            {
                "status": "restored",
                "backup_id": backup_id,
                "size_bytes": size,
                "mode": "bridge",
                "download_url": download_url,
                "filename": filename,
            }
        )
    data = data_file.read_bytes()
    _emit(
        {
            "status": "restored",
            "backup_id": backup_id,
            "size_bytes": size,
            "data_base64": base64.b64encode(data).decode(),
            "filename": filename,
        }
    )


if __name__ == "__main__":
    main()