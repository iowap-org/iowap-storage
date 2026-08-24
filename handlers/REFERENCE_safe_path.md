# Storage handler reference — _safe_path (from legacy storage_node.py).
#
# This file is NOT a handler — it is a reference note for Plan B (Phase 30),
# which ports the path-traversal guard from the legacy nodes/storage-node/
# storage_node.py (deleted in T-121) into the new storage handlers.
#
# The new handlers (handlers/*.py) MUST resolve every
# caller-supplied path relative to /storage and reject anything that
# escapes the base after resolving symlinks and ``..`` segments.
# Keep this logic byte-for-byte; it is the security boundary.

# Original implementation (storage_node.py, deleted T-121):
#
#   from pathlib import Path
#
#   STORAGE_PATH = Path(os.environ.get("RELAY_STORAGE_PATH", "/storage"))
#
#   def _safe_path(target_path: str | None, base: Path = STORAGE_PATH) -> Path:
#       """Resolve a path relative to base and reject path traversal attempts.
#
#       The target may contain subdirectories (e.g. "projects/2026/file.png")
#       but must stay inside ``base`` after resolving symlinks and ``..``
#       segments.
#       """
#       resolved_base = base.resolve()
#       candidate = (resolved_base / (target_path or "")).resolve()
#       try:
#           candidate.relative_to(resolved_base)
#       except ValueError as exc:
#           raise ValueError("path traversal attempt") from exc
#       return candidate
#
# Also preserve for Plan B:
#   - handle_archive: download artifact by id + write to _safe_path(target)
#   - handle_delete: unlink _safe_path(target)
#   - handle_list: rglob under _safe_path(prefix)
#   - handle_quota: shutil.disk_usage(STORAGE_PATH) + threshold check
#   - post_cleanup_request: post a service task when quota is exceeded
#     (posts an llm.decide_cleanup task — keep the pattern, review the cap
#      name in Plan B)