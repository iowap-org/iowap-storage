#!/usr/bin/env python3
"""storage.download_channel handler — open a temp bridge route for download (T-129).

Symmetric to :mod:`upload_channel`: registers a temporary bridge route
pointing at the storage node's bridge server GET /download/{channel_id}
and completes the task with the public download URL. The caller then
GETs that URL; the relay streams the upstream response back chunkwise
(T-129 proxy fix).

Payload::

    {"channel_id": "ch_..."}            # required; the channel a prior
                                        # upload_channel stored under.

Result::

    {"status": "open", "download_url": "<relay>/.../node-routes/<node>/download/<channel_id>",
     "channel_id": "ch_...", "ttl": 3600}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _read_payload, _require, _bridge_upstream_base  # noqa: E402

_DEFAULT_TTL = 3600


def main() -> None:
    payload = _read_payload()
    channel_id = str(_require(payload, "channel_id")).strip()

    base_url = os.environ.get("RELAY_BASE_URL", "")
    token_file = os.environ.get("RELAY_TOKEN_FILE", "")
    node_id = os.environ.get("RELAY_NODE_ID", "")
    if not base_url or not token_file or not node_id:
        _fail("download_channel requires RELAY_BASE_URL, RELAY_TOKEN_FILE, RELAY_NODE_ID")

    # The bridge server upstream: same host as the node's own reachable IP,
    # port BRIDGE_PORT. Derived automatically (the node knows its own IP)
    # unless the operator overrides with NODE_ENDPOINT.
    upstream_base = _bridge_upstream_base()

    upstream = f"{upstream_base}/download/{channel_id}"
    path = f"/download/{channel_id}"

    result = _register(base_url, token_file, path, upstream, channel_id, _DEFAULT_TTL)

    download_url = f"{base_url.rstrip('/')}/relay/v2/dashboard/api/node-routes/{node_id}{path}"
    _emit(
        {
            "status": "open",
            "download_url": download_url,
            "channel_id": channel_id,
            "ttl": _DEFAULT_TTL,
            "expires_at": result.get("expires_at"),
        }
    )


def _register(
    base_url: str, token_file: str, path: str, upstream: str, channel_id: str, ttl: int
) -> dict:
    import httpx  # noqa: PLC0415

    try:
        token = Path(token_file).read_text().strip()
    except OSError as exc:
        _fail(f"cannot read RELAY_TOKEN_FILE: {exc}")
        return {}

    if token.startswith("{"):
        try:
            token = json.loads(token).get("token", token)
        except json.JSONDecodeError:
            pass

    url = f"{base_url.rstrip('/')}/relay/v2/dashboard/api/node-routes/register"
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "path": path,
                "method": "GET",
                "upstream": upstream,
                "ttl_seconds": ttl,
                "channel_id": channel_id,
                "description": "storage download channel (T-129)",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        _fail(f"register request failed: {exc}")
        return {}
    if r.status_code != 200:
        _fail(f"register failed ({r.status_code}): {r.text}")
    return r.json()


if __name__ == "__main__":
    main()
