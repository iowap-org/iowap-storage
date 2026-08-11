#!/usr/bin/env python3
"""backup.delete handler — mark a backup as deleted (T-131).

Sets the manifest ``status`` to ``deleted``. The data file is removed;
the manifest is kept (audit trail). A deleted backup is excluded from
``backup.list`` and cannot be restored.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _read_payload, _require  # noqa: E402
from backup_common import backup_dir, read_manifest, write_manifest  # noqa: E402


def main() -> None:
    payload = _read_payload()
    backup_id = str(_require(payload, "backup_id"))
    manifest = read_manifest(backup_id)
    manifest["status"] = "deleted"
    write_manifest(backup_id, manifest)
    # Remove the data file (keep the manifest for audit).
    data_file = backup_dir(backup_id) / "data.bin"
    if data_file.is_file():
        data_file.unlink()
    _emit({"status": "deleted", "backup_id": backup_id})


if __name__ == "__main__":
    main()