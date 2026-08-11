#!/usr/bin/env python3
"""storage.delete handler — remove a file or directory (T-127).

Payload: ``{"path": "..."}``. Directories are removed recursively (like
``rm -rf``) so a stale tree can be cleaned in one call.

Result::

    {"status": "deleted"} | {"status": "not_found"}
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _read_payload, _require, _safe_path  # noqa: E402


def main() -> None:
    payload = _read_payload()
    raw_path = _require(payload, "path")
    try:
        target = _safe_path(str(raw_path))
    except ValueError:
        _fail("path traversal attempt")

    if not target.exists():
        _emit({"status": "not_found"})

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        _fail(f"delete failed: {exc}")

    _emit({"status": "deleted"})


if __name__ == "__main__":
    main()
