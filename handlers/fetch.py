#!/usr/bin/env python3
"""storage.fetch handler — read a file from the storage tree (T-127).

Payload: ``{"path": "..."}``. The file contents are returned base64-
encoded in the result so the small-file fetch works through the regular
task complete path. Large files should use the bridge download_channel
(Plan B Teil 4) instead.

Result::

    {"status": "fetched", "path": "...", "size_bytes": N, "data_base64": "..."}

A missing file fails the stage with ``{"error": "not found"}``.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import STORAGE_PATH, _emit, _fail, _read_payload, _require, _safe_path  # noqa: E402


def main() -> None:
    payload = _read_payload()
    raw_path = _require(payload, "path")
    try:
        target = _safe_path(str(raw_path))
    except ValueError:
        _fail("path traversal attempt")

    if not target.exists() or not target.is_file():
        _fail("not found")

    data = target.read_bytes()
    try:
        rel = str(target.relative_to(STORAGE_PATH.resolve()))
    except ValueError:
        rel = str(target)
    _emit(
        {
            "status": "fetched",
            "path": rel,
            "size_bytes": len(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
        }
    )


if __name__ == "__main__":
    main()
