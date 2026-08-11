#!/usr/bin/env python3
"""storage.archive handler — pack a directory into a tar.gz (T-135).

Payload: ``{"path": "proj", "target": "proj.tar.gz"}``. The directory is
packed into a tar.gz at ``target`` (relative to the storage root). Both
paths are run through :func:`_safe_path`.

Result::

    {"status": "archived", "path": "proj.tar.gz", "size_bytes": N, "entries": N}
"""

from __future__ import annotations

import os
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
    src_raw = _require(payload, "path")
    dst_raw = _require(payload, "target")
    try:
        src = _safe_path(str(src_raw))
        dst = _safe_path(str(dst_raw))
    except ValueError:
        _fail("path traversal attempt")

    if not src.exists():
        _fail("not found")

    dst.parent.mkdir(parents=True, exist_ok=True)
    entries = _pack_tar(src, dst)
    size = dst.stat().st_size
    _emit({"status": "archived", "path": _display(dst), "size_bytes": size, "entries": entries})


def _pack_tar(src, dst) -> int:
    """Pack ``src`` into a tar.gz at ``dst``. Returns entry count."""
    import tarfile  # noqa: PLC0415

    count = 0
    try:
        with tarfile.open(str(dst), mode="w:gz") as tf:
            # Add the source dir under its own name so extraction restores
            # the top-level folder (e.g. proj/ -> proj/a.txt).
            tf.add(str(src), arcname=src.name, recursive=True)
            count = len(tf.getmembers())
    except (OSError, tarfile.TarError) as exc:
        _fail(f"archive failed: {exc}")
    return count


if __name__ == "__main__":
    main()
