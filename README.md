# iowap-storage

**IOWAP Storage Node — Reference implementation of a file storage node**

A ready-to-run Docker image that provides file storage, archiving, and backup capabilities. Deploy on your NAS or any server with disk space.

## Quick Start

```bash
docker run -d --name iowap-storage \
  -e RELAY_URL=http://your-relay-server:8788 \
  -e NODE_NAME=my-storage \
  -v /path/to/storage:/storage \
  ghcr.io/iowap-org/iowap-storage:latest
```

Then approve the node on your relay dashboard. It will heartbeat the following capabilities:

| Capability | Description |
|------------|-------------|
| `storage.store` | Upload and store a file |
| `storage.fetch` | Retrieve a stored file |
| `storage.delete` | Delete a stored file |
| `storage.list` | List stored files |
| `storage.quota` | Check storage quota/usage |
| `storage.stat` | Get file metadata |
| `storage.move` | Move/rename a file |
| `storage.archive` | Pack a directory into tar.gz |
| `storage.extract` | Extract tar.gz archive |
| `backup.create` | Create a backup (with bridge mode for large data) |
| `backup.list` | List backups |
| `backup.info` | Backup metadata |
| `backup.restore` | Restore from backup |
| `backup.delete` | Delete a backup |

## Bridge Mode

For files >50 MB, the storage node uses **ephemeral bridge routes** — direct streaming between caller and storage without relay buffering:

```bash
node-cli bridge upload bigfile.iso --channel
node-cli backup create --source /data --mode bridge
```

## Running on QNAP

See `docs/qnap-storage-node.md` for QNAP-specific setup (Container Station, volume mounts, persistence).

## Building

```bash
docker build -t iowap-storage .
```

## Docs

Full documentation in [iowap-org/iowap-docs](https://github.com/iowap-org/iowap-docs):

- `docs/storage/storage.md` — storage capabilities & bridge mode
- `docs/storage/qnap-storage-node.md` — QNAP deployment

## License

AGPL-3.0