#!/usr/bin/env python3
"""storage.store handler — write a file into the storage tree (T-127).

Two modes selected by the payload:

* ``data_base64``  — small files inlined in the payload; written directly.
* ``artifact_id``   — large files staged as a relay artifact; the handler
  streams it down via :class:`RelayClient.download_artifact` so the body
  never lands fully in RAM. Needs ``RELAY_BASE_URL`` + ``RELAY_TOKEN_FILE``
  (set by handler_runner) plus a writable token file.

Result::

    {"status": "stored", "path": "...", "size_bytes": N}

Every caller-supplied path is run through :func:`_safe_path`; a traversal
attempt fails the stage with ``{"error": "path traversal attempt"}``.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# Allow importing _common.py whether the script is run from /app/handlers
# (Docker) or the repo root (tests).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    STORAGE_PATH,
    _emit,
    _ensure_base,
    _fail,
    _read_payload,
    _require,
    _safe_path,
)


def main() -> None:
    payload = _read_payload()
    raw_path = _require(payload, "path")
    action = payload.get("action", "store_as_is")
    try:
        target = _safe_path(str(raw_path))
    except ValueError:
        _fail("path traversal attempt")

    _ensure_base()
    target.parent.mkdir(parents=True, exist_ok=True)

    if "data_base64" in payload:
        # Inline mode — decode + write directly.
        try:
            data = base64.b64decode(payload["data_base64"])
        except Exception as exc:  # noqa: BLE001
            _fail(f"invalid data_base64: {exc}")
        if action == "extract":
            _extract_tar(data, target)
            _emit({"status": "stored", "path": _display(target), "action": "extract"})
        else:
            target.write_bytes(data)
            _emit({"status": "stored", "path": _display(target), "size_bytes": len(data)})

    if "artifact_id" in payload:
        # Stream mode — download an artifact chunkwise from the relay.
        artifact_id = str(payload["artifact_id"])
        base_url = os.environ.get("RELAY_BASE_URL", "")
        token_file = os.environ.get("RELAY_TOKEN_FILE", "")
        if not base_url or not token_file:
            _fail("artifact_id mode requires RELAY_BASE_URL and RELAY_TOKEN_FILE")
        if action == "extract":
            # Stream to a temp file, then extract (tar needs a seekable source).
            tmp = target.with_suffix(target.suffix + ".tmp")
            _stream_artifact(artifact_id, tmp, base_url, token_file)
            _extract_tar(tmp.read_bytes(), target)
            tmp.unlink(missing_ok=True)
            _emit({"status": "stored", "path": _display(target), "action": "extract"})
        else:
            size = _stream_artifact(artifact_id, target, base_url, token_file)
            _emit({"status": "stored", "path": _display(target), "size_bytes": size})

    _fail("payload must contain either data_base64 or artifact_id")


def _extract_tar(data: bytes, target: Path) -> None:
    """Extract a tar.gz into ``target``, rejecting path-traversal entries.

    Every archive entry is resolved against ``target`` and rejected if it
    escapes after ``..``/symlink resolution (T-133). The target dir is
    created if needed.
    """
    import io
    import tarfile

    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                # Reject absolute paths and traversal.
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
    except tarfile.TarError as exc:
        _fail(f"invalid tar.gz: {exc}")


def _display(target: Path) -> str:
    """Return a human-friendly path (relative to storage base when inside)."""
    try:
        return str(target.relative_to(STORAGE_PATH.resolve()))
    except ValueError:
        return str(target)


def _stream_artifact(artifact_id: str, target: Path, base_url: str, token_file: str) -> int:
    """Download ``artifact_id`` from the relay into ``target`` chunkwise.

    Uses a minimal inline httpx streaming call so the handler does not
    depend on RelayClient (which needs the full node meta/config). Returns
    the number of bytes written.
    """
    import httpx  # noqa: PLC0415 — imported lazily so the handler still works for inline mode when httpx is absent

    token = ""
    try:
        token = Path(token_file).read_text().strip()
    except OSError:
        _fail(f"cannot read RELAY_TOKEN_FILE: {token_file}")

    url = f"{base_url.rstrip('/')}/relay/v2/storage/files/{artifact_id}"
    try:
        with httpx.stream(
            "GET",
            url,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
            timeout=300,
        ) as resp:
            resp.raise_for_status()
            total = 0
            with target.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
                    total += len(chunk)
            return total
    except Exception as exc:  # noqa: BLE001
        _fail(f"artifact download failed: {exc}")


if __name__ == "__main__":
    main()
