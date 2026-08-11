#!/usr/bin/env python3
"""backup.info handler — return details for a single backup (T-131)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _read_payload, _require  # noqa: E402
from backup_common import read_manifest  # noqa: E402


def main() -> None:
    payload = _read_payload()
    backup_id = str(_require(payload, "backup_id"))
    manifest = read_manifest(backup_id)
    # ``status`` in the manifest is the backup lifecycle status
    # (active/expired/deleted); the handler result status is "info".
    # Manifest fields win, but the result status is forced to "info".
    result = {"status": "info"}
    result.update(manifest)
    result["status"] = "info"
    _emit(result)


if __name__ == "__main__":
    main()