# Backup and Restore (OpenSearch snapshots)

Logs (`mule-logs-*`, `logstash-*`) and traces (`jaeger-*`) live in OpenSearch. Backups are OpenSearch snapshots
of `BACKUP_INDICES` (default `daily`: today's `mule-logs-*` + `logstash-*`; traces only if the pattern includes them),
made by the scripts in `config/scripts/backup/`. They read `.env` and talk to OpenSearch as `admin` through
`http://localhost:9080/opensearch` (loopback only), so run them on the platform host.

## Where snapshots go

The default repository type is `fs`: snapshots are written to `/usr/share/opensearch/data/snapshots` inside the
container (registered as `path.repo` by `scripts/opensearch-start.sh`). That directory is part of the
`opensearch-data` volume, so snapshots protect against deleted or corrupt indices, **not** against losing the
volume (`docker compose down -v`, disk failure). For that, copy them off the host:

```bash
docker cp opensearch:/usr/share/opensearch/data/snapshots ./opensearch-snapshots-$(date +%F)
```

`configure-backup.sh` also knows `s3`, `azure` and `gcs`, but the stock OpenSearch image has none of those
repository plugins; they need a custom image (`opensearch-plugin install repository-s3`, ...).

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `BACKUP_REPOSITORY_NAME` | `backup-repo` | snapshot repository |
| `BACKUP_REPOSITORY_TYPE` | `fs` | see above |
| `BACKUP_INDICES` | `daily` | `daily` = today's `mule-logs-*` + `logstash-*`; or a pattern such as `*` or `mule-logs-*` |
| `BACKUP_COMPRESS` | `true` | compress snapshot metadata |
| `BACKUP_RETENTION_DAYS` | `30` | `backup-cleanup.sh` deletes older snapshots |
| `BACKUP_MAX_COUNT` | `30` | ... and the oldest beyond this count |
| `BACKUP_SCHEDULE` | `0 2 * * *` | cron schedule used by `setup-backup-cron.sh` |

## Commands

```bash
./config/scripts/backup/configure-backup.sh            # once: register (and verify) the repository; --force recreates it
./config/scripts/backup/backup.sh                      # take a snapshot now
./config/scripts/backup/backup-cleanup.sh --dry-run    # show what retention would delete; without --dry-run deletes it
./config/scripts/backup/setup-backup-cron.sh           # cron job for backup + cleanup (Linux host); --remove undoes it

set -a; . ./.env; set +a                               # list snapshots
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "http://localhost:9080/opensearch/_cat/snapshots/backup-repo?v"
```

## Restore

```bash
./config/scripts/backup/restore.sh <snapshot> [pattern]    # pattern defaults to every index in the snapshot
```

It asks for confirmation, **closes the existing open indices that match** (OpenSearch cannot restore over an open
index), restores them from the snapshot, and waits for recovery. Data written after the snapshot in those indices is
lost. System indices (names starting with `.`, e.g. the security config) are never closed or restored.

To look at old data without touching the live index, restore under another name with the OpenSearch API directly:

```bash
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" -X POST -H 'Content-Type: application/json' \
  "http://localhost:9080/opensearch/_snapshot/backup-repo/<snapshot>/_restore" \
  -d '{"indices":"mule-logs-2026.10.22","rename_pattern":"(.+)","rename_replacement":"restored-$1"}'
```

## What is not covered

Snapshots cover OpenSearch only. Other state lives in Docker volumes and bind mounts: Keycloak's Postgres
(`keycloak-db-data`), MySQL, Grafana, Prometheus, ActiveMQ, and the Runtime Manager's `mule/volumes/` (apps, pools,
encrypted properties, API tokens). Back those up with volume copies (`docker run --rm -v <volume>:/v -v "$PWD":/b
alpine tar czf /b/<volume>.tgz -C /v .`) while the service is stopped, and keep `.env` (it holds the keys,
`RM_SECRETS_KEY` included) somewhere safe.
