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
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    STORAGE_PATH,
    _emit,
    _fail,
    _note,
    _read_payload,
    _require,
    _safe_path,
)


def _display(target) -> str:
    try:
        return str(target.relative_to(STORAGE_PATH.resolve()))
    except ValueError:
        return str(target)


# Report a progress note to the relay every N entries (T-160). Keeps the
# Long-Run TTL alive while a large pack runs.
_PROGRESS_EVERY = 500


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
    """Pack ``src`` into a tar.gz at ``dst``. Returns entry count.

    Walks the source tree iteratively (not ``tarfile.add(recursive=True)``)
    so it can report progress to the relay as it goes — every
    ``_PROGRESS_EVERY`` entries resets the Long-Run stage TTL (T-154/T-160).
    """
    import tarfile  # noqa: PLC0415

    count = 0
    try:
        with tarfile.open(str(dst), mode="w:gz") as tf:
            for root, dirs, files in os.walk(src):
                root_path = Path(root)
                for name in files:
                    full = root_path / name
                    arcname = f"{src.name}/{full.relative_to(src)}"
                    tf.add(str(full), arcname=arcname, recursive=False)
                    count += 1
                    if count % _PROGRESS_EVERY == 0:
                        _note(f"storage.archive: {count} files packed")
                # Empty dirs still get an entry so extraction restores them.
                for d in dirs:
                    full = root_path / d
                    arcname = f"{src.name}/{full.relative_to(src)}"
                    if not any(full.rglob("*")):
                        ti = tarfile.TarInfo(arcname)
                        ti.type = tarfile.DIRTYPE
                        tf.addfile(ti)
                        count += 1
            _note(f"storage.archive: done, {count} entries")
    except (OSError, tarfile.TarError) as exc:
        _fail(f"archive failed: {exc}")
    return count


if __name__ == "__main__":
    main()
