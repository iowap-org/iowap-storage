#!/usr/bin/env python3
"""storage.quota handler — report disk usage + threshold (T-127).

Payload: ``{}`` (no arguments). Uses :func:`shutil.disk_usage` on the
storage base. The threshold is read from ``RELAY_STORAGE_QUOTA_THRESHOLD``
(a ratio 0.0–1.0, default 0.9); ``threshold_exceeded`` is True when the
usage ratio is at or above it so the scheduler can trigger a cleanup task.

Result::

    {"status": "quota", "total_bytes": N, "used_bytes": N, "free_bytes": N,
     "usage_ratio": 0.xx, "threshold": 0.9, "threshold_exceeded": bool}
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import STORAGE_PATH, _emit, _read_payload  # noqa: E402


def main() -> None:
    _read_payload()  # no fields expected; still drain stdin
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(str(STORAGE_PATH))

    try:
        threshold = float(os.environ.get("RELAY_STORAGE_QUOTA_THRESHOLD", "0.9"))
    except ValueError:
        threshold = 0.9

    usage_ratio = usage.used / usage.total if usage.total else 0.0
    _emit(
        {
            "status": "quota",
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "usage_ratio": round(usage_ratio, 4),
            "threshold": threshold,
            "threshold_exceeded": usage_ratio >= threshold,
        }
    )


if __name__ == "__main__":
    main()
