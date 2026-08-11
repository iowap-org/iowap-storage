#!/usr/bin/env python3
"""storage.move handler — rename/move a file or directory (T-127).

Payload: ``{"from": "...", "to": "..."}``. Both paths are run through
:func:`_safe_path`; the destination parent is created if needed.

Result::

    {"status": "moved", "from": "...", "to": "..."}
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import STORAGE_PATH, _emit, _fail, _read_payload, _require, _safe_path  # noqa: E402


def _display(target) -> str:
    try:
        return str(target.relative_to(STORAGE_PATH.resolve()))
    except ValueError:
        return str(target)


def main() -> None:
    payload = _read_payload()
    src_raw = _require(payload, "from")
    dst_raw = _require(payload, "to")
    try:
        src = _safe_path(str(src_raw))
        dst = _safe_path(str(dst_raw))
    except ValueError:
        _fail("path traversal attempt")

    if not src.exists():
        _fail("source not found")

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
    except OSError as exc:
        _fail(f"move failed: {exc}")

    _emit({"status": "moved", "from": _display(src), "to": _display(dst)})


if __name__ == "__main__":
    main()
