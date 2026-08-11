#!/usr/bin/env python3
"""backup.retention handler — apply a retention policy to a source (T-132).

The policy comes as a task payload (not hardcoded). Supported formats:

* ``keep_last: N``        — keep the N most recent, delete older.
* ``max_age_days: N``     — delete backups older than N days.
* GFS: ``keep_daily/keep_weekly/keep_monthly`` — keep the newest per
  day/week/month bucket, delete the rest.

Backups are ordered by ``created_at`` (newest first). Deleted backups
are marked ``status: deleted`` (manifest kept for audit) and their data
file removed.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _read_payload, _require  # noqa: E402
from backup_common import MANIFEST_NAME, backup_dir, backups_root, write_manifest  # noqa: E402


def _parse_ts(iso: str) -> datetime:
    """Parse an ISO-8601 timestamp (with Z suffix) to a tz-aware datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _load_backups(source: str) -> list[dict]:
    """Load all active backups for a source, newest first."""
    root = backups_root()
    out = []
    if root.is_dir():
        for d in root.iterdir():
            if not d.is_dir():
                continue
            mf = d / MANIFEST_NAME
            if not mf.is_file():
                continue
            try:
                m = json.loads(mf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if m.get("source") != source or m.get("status") != "active":
                continue
            out.append(m)
    out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return out


def _mark_deleted(backup_id: str) -> None:
    """Mark a backup deleted and remove its data file."""
    mf = backup_dir(backup_id) / MANIFEST_NAME
    m = json.loads(mf.read_text())
    m["status"] = "deleted"
    write_manifest(backup_id, m)
    data_file = backup_dir(backup_id) / "data.bin"
    if data_file.is_file():
        data_file.unlink()


def _apply(backups: list[dict], policy: dict) -> list[str]:
    """Return the list of backup_ids to delete per the policy."""
    deleted: list[str] = []
    if "keep_last" in policy:
        keep = int(policy["keep_last"])
        for m in backups[keep:]:
            deleted.append(m["backup_id"])
    if "max_age_days" in policy:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(policy["max_age_days"]))
        for m in backups:
            try:
                created = _parse_ts(m["created_at"])
            except (ValueError, TypeError):
                continue
            if created < cutoff:
                deleted.append(m["backup_id"])
    # GFS: keep newest per day/week/month bucket.
    if any(k in policy for k in ("keep_daily", "keep_weekly", "keep_monthly")):
        keep_daily = int(policy.get("keep_daily", 0))
        keep_weekly = int(policy.get("keep_weekly", 0))
        keep_monthly = int(policy.get("keep_monthly", 0))
        seen_daily: set[str] = set()
        seen_weekly: set[str] = set()
        seen_monthly: set[str] = set()
        for m in backups:
            try:
                created = _parse_ts(m["created_at"])
            except (ValueError, TypeError):
                continue
            day = created.strftime("%Y-%m-%d")
            week = created.strftime("%Y-%W")
            month = created.strftime("%Y-%m")
            if keep_daily and day not in seen_daily:
                seen_daily.add(day)
                continue
            if keep_weekly and week not in seen_weekly:
                seen_weekly.add(week)
                continue
            if keep_monthly and month not in seen_monthly:
                seen_monthly.add(month)
                continue
            deleted.append(m["backup_id"])
    # Dedupe, preserve order.
    return list(dict.fromkeys(deleted))


def main() -> None:
    payload = _read_payload()
    source = str(_require(payload, "source"))
    policy = _require(payload, "policy")
    if not isinstance(policy, dict):
        _fail("policy must be an object")

    backups = _load_backups(source)
    to_delete = _apply(backups, policy)
    for backup_id in to_delete:
        _mark_deleted(backup_id)

    _emit({"status": "applied", "source": source, "deleted": to_delete, "count": len(to_delete)})


if __name__ == "__main__":
    main()
