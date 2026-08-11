#!/usr/bin/env python3
"""storage.list handler — list files under a prefix (T-127).

Payload: ``{"prefix": "..."}`` (default: "" = list everything under the
storage base). The prefix is itself run through :func:`_safe_path` so a
``../`` prefix cannot escape the tree.

Result::

    {"status": "listed", "count": N,
     "files": [{"path": "...", "size_bytes": N, "modified": "ISO-8601"}]}
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import STORAGE_PATH, _emit, _fail, _read_payload, _safe_path  # noqa: E402


def main() -> None:
    payload = _read_payload()
    prefix = str(payload.get("prefix", "") or "")
    try:
        base = _safe_path(prefix)
    except ValueError:
        _fail("path traversal attempt")

    if not base.exists():
        _emit({"status": "listed", "count": 0, "files": []})

    storage_root = STORAGE_PATH.resolve()
    files = []
    for p in sorted(base.rglob("*")):
        if p.is_file():
            stat = p.stat()
            try:
                rel = str(p.relative_to(storage_root))
            except ValueError:
                continue
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            files.append(
                {
                    "path": rel,
                    "size_bytes": stat.st_size,
                    "modified": modified,
                }
            )

    _emit({"status": "listed", "count": len(files), "files": files})


if __name__ == "__main__":
    main()
