#!/usr/bin/env python3
"""storage.extract handler — unpack a stored tar.gz into a directory (T-135).

Payload: ``{"path": "bundle.tar.gz"}``. The archive is extracted into a
directory named after the archive (minus the ``.tar.gz`` suffix) next to
it. Path-traversal entries and symlinks are rejected.

Result::

    {"status": "extracted", "path": "bundle", "entries": N}
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _note, _read_payload, _require, _safe_path  # noqa: E402


# Report a progress note to the relay every N entries (T-160).
_PROGRESS_EVERY = 500


def main() -> None:
    payload = _read_payload()
    raw_path = _require(payload, "path")
    try:
        archive = _safe_path(str(raw_path))
    except ValueError:
        _fail("path traversal attempt")

    if not archive.is_file():
        _fail("not found")

    # Target dir = archive name minus .tar.gz / .tgz suffix.
    name = archive.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    target = archive.parent / name

    data = archive.read_bytes()
    _extract_tar(data, target)
    _emit({"status": "extracted", "path": _display(target), "entries": _count_entries(data)})


def _display(target) -> str:
    from _common import STORAGE_PATH  # noqa: PLC0415

    try:
        return str(target.relative_to(STORAGE_PATH.resolve()))
    except ValueError:
        return str(target)


def _count_entries(data: bytes) -> int:
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            return len(tf.getmembers())
    except tarfile.TarError:
        return 0


def _extract_tar(data: bytes, target) -> None:
    """Extract a tar.gz into ``target``, rejecting traversal + links."""
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    _count = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                _count += 1
                if _count % _PROGRESS_EVERY == 0:
                    _note(f"storage.extract: {_count} entries extracted")
                if member.name.startswith("/") or ".." in member.name.split("/"):
                    _fail(f"archive entry escapes target: {member.name}")
                dest = (resolved_target / member.name).resolve()
                try:
                    dest.relative_to(resolved_target)
                except ValueError:
                    _fail(f"archive entry escapes target: {member.name}")
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif member.issym() or member.islnk():
                    _fail(f"archive entry is a link (not allowed): {member.name}")
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    f = tf.extractfile(member)
                    if f is not None:
                        with dest.open("wb") as out:
                            out.write(f.read())
            _note(f"storage.extract: done, {_count} entries")
    except tarfile.TarError as exc:
        _fail(f"invalid tar.gz: {exc}")


if __name__ == "__main__":
    main()
