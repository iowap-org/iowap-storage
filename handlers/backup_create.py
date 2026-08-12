#!/usr/bin/env python3
"""backup.create handler — declare an upload as a backup (T-131).

Writes the backup data into ``<STORAGE_PATH>/backups/<backup_id>/`` next to
a JSON manifest (T-130). Two data modes:

* ``data_base64``  — small payloads inlined; written directly as ``data.bin``.
* ``artifact_id``  — large payloads staged as a relay artifact; streamed
  down chunkwise (same pattern as ``store.py``).

For ``type: incremental`` the ``base_backup_id`` must reference an existing
backup (full or incremental) of the same source.

Result::

    {"status": "created", "backup_id": "bk_...", "path": "backups/bk_...",
     "size_bytes": N, "type": "full"}
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _read_payload, _require, _safe_filename  # noqa: E402
from backup_common import (  # noqa: E402
    backup_dir,
    new_manifest,
    open_backup_bridge_route,
    read_manifest,
    write_manifest,
)


def main() -> None:
    payload = _read_payload()
    source = str(_require(payload, "source"))
    btype = str(_require(payload, "type"))
    base_backup_id = payload.get("base_backup_id")

    if btype == "incremental":
        if not base_backup_id:
            _fail("incremental backup requires base_backup_id")
        # Verify the base exists (and is not deleted). read_manifest exits
        # on a missing manifest; translate its generic error into the
        # base-specific message the contract promises.
        try:
            base = read_manifest(str(base_backup_id))
        except SystemExit:  # noqa: PERF203 — _fail exits
            _fail(f"base backup not found: {base_backup_id}")
        if base.get("status") == "deleted":
            _fail(f"base backup not found: {base_backup_id}")

    manifest = new_manifest(source, btype, str(base_backup_id) if base_backup_id else None)
    # T-162: preserve the original filename so a restore can write it back
    # with the right name/suffix (e.g. ``sims4-save.tar.gz``).
    filename = _safe_filename(payload.get("filename"))
    if filename:
        manifest["filename"] = filename
    backup_id = manifest["backup_id"]
    target_dir = backup_dir(backup_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    data_file = target_dir / "data.bin"

    bridge_mode = payload.get("mode") == "bridge"
    if bridge_mode:
        # Bridge mode: open a temp route so the caller streams the large
        # backup straight onto backups/<id>/data.bin (no artifact staging,
        # no RAM load). The manifest is minted now; the data file is filled
        # by the caller's POST to the returned upload_url.
        data_file = target_dir / "data.bin"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        upload_url = open_backup_bridge_route(
            backup_id,
            method="POST",
            description="backup.create bridge upload (T-154)",
        )
        write_manifest(backup_id, manifest)
        _emit(
            {
                "status": "created",
                "backup_id": backup_id,
                "path": f"backups/{backup_id}",
                "type": btype,
                "mode": "bridge",
                "upload_url": upload_url,
            }
        )
    elif "data_base64" in payload:
        try:
            data = base64.b64decode(payload["data_base64"])
        except Exception as exc:  # noqa: BLE001
            _fail(f"invalid data_base64: {exc}")
        data_file.write_bytes(data)
        manifest["size_bytes"] = len(data)
    elif "artifact_id" in payload:
        size = _stream_artifact(str(payload["artifact_id"]), data_file)
        manifest["size_bytes"] = size
    else:
        _fail("payload must contain either data_base64 or artifact_id")

    write_manifest(backup_id, manifest)
    _emit(
        {
            "status": "created",
            "backup_id": backup_id,
            "path": f"backups/{backup_id}",
            "size_bytes": manifest["size_bytes"],
            "type": btype,
        }
    )


def _stream_artifact(artifact_id: str, target: Path) -> int:
    """Stream a relay artifact into ``target`` chunkwise (no full-RAM load)."""
    import httpx  # noqa: PLC0415

    base_url = os.environ.get("RELAY_BASE_URL", "")
    token_file = os.environ.get("RELAY_TOKEN_FILE", "")
    if not base_url or not token_file:
        _fail("artifact_id mode requires RELAY_BASE_URL and RELAY_TOKEN_FILE")
    try:
        token = Path(token_file).read_text().strip()
    except OSError as exc:
        _fail(f"cannot read RELAY_TOKEN_FILE: {exc}")
    url = f"{base_url.rstrip('/')}/relay/v2/storage/files/{artifact_id}"
    try:
        with httpx.stream(
            "GET", url,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True, timeout=300,
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