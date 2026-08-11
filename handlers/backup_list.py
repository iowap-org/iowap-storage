#!/usr/bin/env python3
"""backup.list handler — list backups, optionally filtered (T-131)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _read_payload  # noqa: E402
from backup_common import MANIFEST_NAME, backups_root  # noqa: E402


def main() -> None:
    payload = _read_payload()
    source = payload.get("source")
    btype = payload.get("type")

    root = backups_root()
    backups = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            mf = d / MANIFEST_NAME
            if not mf.is_file():
                continue
            try:
                manifest = json.loads(mf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if source and manifest.get("source") != source:
                continue
            if btype and manifest.get("type") != btype:
                continue
            # Exclude deleted backups (retention/delete keep the manifest
            # for audit but the backup is no longer available).
            if manifest.get("status") == "deleted":
                continue
            backups.append(manifest)

    _emit({"status": "listed", "count": len(backups), "backups": backups})


if __name__ == "__main__":
    main()