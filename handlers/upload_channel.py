#!/usr/bin/env python3
"""storage.upload_channel handler — open a temp bridge route for upload (T-129).

The handler runs as a claimable task: it registers a temporary bridge
route on the relay pointing at the storage node's bridge server
(T-128) and completes the task with the public upload URL + channel_id
+ ttl. The caller then POSTs the large file to that URL; the relay
streams the request body chunkwise to the bridge server (T-129 proxy
fix), which writes it onto the NAS.

Payload::

    {"channel_id": "ch_..."}            # optional; minted when absent

Result::

    {"status": "open", "upload_url": "<relay>/.../node-routes/<node>/upload/<channel_id>",
     "channel_id": "ch_...", "ttl": 3600}

The handler uses :class:`RelayClient.register_temp_route`. It reads the
relay base URL + token from the env vars handler_runner sets
(``RELAY_BASE_URL`` + ``RELAY_TOKEN_FILE``) and the node id from
``RELAY_NODE_ID``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow importing _common.py from the handlers dir.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import _emit, _fail, _read_payload, _bridge_upstream_base  # noqa: E402

# Default TTL the route stays open for the caller to upload through.
_DEFAULT_TTL = 3600


def main() -> None:
    payload = _read_payload()
    channel_id = str(payload.get("channel_id") or "").strip()
    if not channel_id:
        # Mint a simple unique channel id from the stage/task env so a
        # caller that omits channel_id still gets a stable, unique one.
        channel_id = f"ch_{os.environ.get('RELAY_TASK_ID', 'anon')}".replace(" ", "_")

    base_url = os.environ.get("RELAY_BASE_URL", "")
    token_file = os.environ.get("RELAY_TOKEN_FILE", "")
    node_id = os.environ.get("RELAY_NODE_ID", "")
    if not base_url or not token_file or not node_id:
        _fail("upload_channel requires RELAY_BASE_URL, RELAY_TOKEN_FILE, RELAY_NODE_ID")

    # The bridge server upstream: same host as the node's own reachable IP,
    # port BRIDGE_PORT. The bridge server listens on 0.0.0.0:BRIDGE_PORT; the
    # relay reaches it via the node's reachable endpoint. We derive the
    # upstream host automatically (the node knows its own IP) unless the
    # operator overrides with NODE_ENDPOINT.
    upstream_base = _bridge_upstream_base()

    upstream = f"{upstream_base}/upload/{channel_id}"
    path = f"/upload/{channel_id}"

    # Register the temp route via the relay client. We build a minimal
    # RelayClient so the handler is self-contained (the daemon already
    # imports it, but the handler runs in its own subprocess).
    result = _register(base_url, token_file, path, upstream, channel_id, _DEFAULT_TTL)

    upload_url = f"{base_url.rstrip('/')}/relay/v2/dashboard/api/node-routes/{node_id}{path}"
    _emit(
        {
            "status": "open",
            "upload_url": upload_url,
            "channel_id": channel_id,
            "ttl": _DEFAULT_TTL,
            "expires_at": result.get("expires_at"),
        }
    )


def _register(
    base_url: str, token_file: str, path: str, upstream: str, channel_id: str, ttl: int
) -> dict:
    """Call the relay register endpoint directly (no RelayClient dep).

    Returns the server response (contains ``expires_at``). On error
    fails the stage with the server's detail.
    """
    import httpx  # noqa: PLC0415

    try:
        token = Path(token_file).read_text().strip()
    except OSError as exc:
        _fail(f"cannot read RELAY_TOKEN_FILE: {exc}")
        return {}  # unreachable; _fail exits

    # The token file may store a JSON envelope {"token": "rt_..."} or the
    # bare token. Unwrap when it is JSON.
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
                "method": "POST",
                "upstream": upstream,
                "ttl_seconds": ttl,
                "channel_id": channel_id,
                "description": "storage upload channel (T-129)",
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
