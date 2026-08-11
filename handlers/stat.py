#!/usr/bin/env python3
"""storage.stat handler — stat a single path (T-127).

Payload: ``{"path": "..."}``. Works for both files and directories.

Result::

    {"status": "stat", "path": "...", "size_bytes": N,
     "modified": "ISO-8601", "is_dir": bool}
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import STORAGE_PATH, _emit, _fail, _read_payload, _require, _safe_path  # noqa: E402


def main() -> None:
    payload = _read_payload()
    raw_path = _require(payload, "path")
    try:
        target = _safe_path(str(raw_path))
    except ValueError:
        _fail("path traversal attempt")

    if not target.exists():
        _fail("not found")

    stat = target.stat()
    try:
        rel = str(target.relative_to(STORAGE_PATH.resolve()))
    except ValueError:
        rel = str(target)
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    _emit(
        {
            "status": "stat",
            "path": rel,
            "size_bytes": stat.st_size,
            "modified": modified,
            "is_dir": target.is_dir(),
        }
    )


if __name__ == "__main__":
    main()
