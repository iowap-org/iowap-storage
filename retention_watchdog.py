#!/usr/bin/env python3
"""Storage-node retention watchdog (T-132).

A small periodic loop (analogous to the server's MaintenanceScheduler)
that applies configured retention policies to the local backups. Policies
are read from ``~/.relay/retention.yaml`` (or ``RELAY_RETENTION_CONFIG``):

    projects:
      keep_last: 2
    photos:
      max_age_days: 30

The watchdog reuses the same policy logic as the ``backup.retention``
handler by importing it. It runs as a background process alongside the
node-daemon (started by the storage entrypoint).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "handlers"))

from backup_retention import _apply, _load_backups, _mark_deleted  # noqa: E402

log = logging.getLogger("retention-watchdog")

# Default interval between runs (seconds).
INTERVAL = int(os.environ.get("RELAY_RETENTION_INTERVAL", "3600"))
# Config path: ~/.relay/retention.yaml or RELAY_RETENTION_CONFIG.
CONFIG_PATH = Path(
    os.environ.get("RELAY_RETENTION_CONFIG", os.path.expanduser("~/.relay/retention.yaml"))
)


def load_policies(path: Path) -> dict:
    """Load the retention config as a {source: policy} dict."""
    if not path.is_file():
        return {}
    import yaml  # noqa: PLC0415

    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def apply_policies(config_path: str | Path, storage_path: str | Path | None = None) -> dict:
    """Apply all configured policies once. Returns {source: deleted_ids}."""
    if storage_path is not None:
        os.environ["RELAY_STORAGE_PATH"] = str(storage_path)
        # backup_common caches STORAGE_PATH at import time; re-point it so
        # the watchdog honours a test/local storage root.
        import backup_common  # noqa: PLC0415

        backup_common.STORAGE_PATH = Path(str(storage_path))
        backup_common.BACKUPS_DIR = backup_common.STORAGE_PATH / "backups"
    policies = load_policies(Path(config_path))
    result: dict = {}
    for source, policy in policies.items():
        if not isinstance(policy, dict):
            continue
        backups = _load_backups(source)
        to_delete = _apply(backups, policy)
        for backup_id in to_delete:
            _mark_deleted(backup_id)
        result[source] = to_delete
    return result


def main() -> None:
    logging.basicConfig(level=os.environ.get("RELAY_LOG_LEVEL", "INFO"))
    log.info("retention watchdog starting (interval=%ss, config=%s)", INTERVAL, CONFIG_PATH)
    while True:
        try:
            result = apply_policies(CONFIG_PATH)
            for source, deleted in result.items():
                if deleted:
                    log.info("retention[%s]: deleted %s", source, deleted)
        except Exception as exc:  # noqa: BLE001
            log.error("retention run failed: %s", exc)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
