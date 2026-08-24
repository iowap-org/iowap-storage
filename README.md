# iowap-storage

**IOWAP Storage Node — Reference implementation of a file storage node**

A ready-to-run Docker image that provides file storage, archiving, and backup capabilities. Deploy on your NAS or any server with disk space.

## Running with Docker

The storage node runs as a Docker container. Build instructions and compose files are in **[iowap-org/iowap-docker](https://github.com/iowap-org/iowap-docker)**:

```bash
# 1. Build base image (one-time)
docker build -t iowap-node-base -f base/Dockerfile https://github.com/iowap-org/iowap-docker.git

# 2. Build storage image
docker build -t iowap-storage -f storage/Dockerfile https://github.com/iowap-org/iowap-docker.git

# 3. Run
RELAY_URL=http://your-relay:8788 docker compose -f storage/docker-compose.yml up -d
```

## Quick Start (manual)

You can run the handlers directly for testing:

```bash
# Source the environment and run a handler directly
echo '{"args": {}}' | python3 handlers/list.py
```

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

The handlers and Python source are designed to run inside the **iowap-node-base** container. See [iowap-docker](https://github.com/iowap-org/iowap-docker) for the Dockerfiles.

## Docs

Full documentation in [iowap-org/iowap-docs](https://github.com/iowap-org/iowap-docs):

- `docs/storage/storage.md` — storage capabilities & bridge mode
- `docs/storage/qnap-storage-node.md` — QNAP deployment

## License

AGPL-3.0