# Log and Trace Retention (log-archiver)

Fluent Bit writes one index per day (`mule-logs-YYYY.MM.DD`, `logstash-YYYY.MM.DD`) and Jaeger does the same
(`jaeger-span-YYYY-MM-DD`, `jaeger-service-YYYY-MM-DD`). The `log-archiver` service (profiles `logging` and
`tracing`, started by `./install.sh` / `docker compose up -d`) checks them every `LOG_ARCHIVE_INTERVAL` seconds:

| Indices | Deleted when | Before deleting |
|---|---|---|
| `mule-logs-*`, `logstash-*` | older than `LOGS_RETENTION_DAYS` (365), or the oldest ones while OpenSearch's disk is above `LOGS_DISK_MAX_PERCENT` (80) | exported to `./volumes/log-archive/<index>.ndjson.gz` |
| `jaeger-span-*`, `jaeger-service-*` | older than `JAEGER_RETENTION_DAYS` (30), or the oldest ones under disk pressure | nothing (traces aren't archived) |

- Age is the date in the index name (UTC day), so a restored old index is still recognised as old.
- Under disk pressure the oldest index goes first (traces before logs of the same day), one at a time, until the
  disk is below the limit. 80% stays under OpenSearch's own watermarks (85%: no new shards, 95%: indices go
  read-only and new logs are rejected).
- Today's indices are never deleted, by age or by disk.
- A log index is only deleted once its archive is complete: the number of exported documents must match the
  index's count. If the export fails the index stays and the next pass tries again (`ERROR` line in the log).

Change a value in `.env`, then `docker compose up -d` (recreates the service with the new values).

## The archive

One gzip file per index, one JSON document (`_source`) per line, readable without OpenSearch:

```bash
zcat volumes/log-archive/mule-logs-2025.10.28.ndjson.gz | head
zcat volumes/log-archive/mule-logs-2025.10.28.ndjson.gz | grep '"level":"ERROR"' | wc -l
```

Without S3 the files stay in `./volumes/log-archive` for good (that is the history): about 5-10x smaller than the
index was. They are on the host disk, outside OpenSearch's volume, so the disk limit above doesn't count them;
copy them off or enable S3 if the host disk is small.

## S3 (optional)

```bash
LOG_ARCHIVE_S3_BUCKET=my-log-archive
LOG_ARCHIVE_S3_REGION=us-east-1
LOG_ARCHIVE_S3_PREFIX=log-archive          # key = <prefix>/<index>.ndjson.gz
LOG_ARCHIVE_S3_ACCESS_KEY=AKIA...
LOG_ARCHIVE_S3_SECRET_KEY=...
LOG_ARCHIVE_S3_ENDPOINT=                   # only for S3-compatible stores, e.g. http://minio:9000 (path-style)
```

Each pass uploads every archive in `./volumes/log-archive` and removes the local copy once S3 has accepted it, so a
failed upload is simply retried. The key needs `s3:PutObject` on the bucket/prefix, nothing else. One upload is a
single PUT, so one archive (one day of one index) can be at most 5 GB.

## Check

```bash
docker compose logs log-archiver          # start line with the settings, then archived / deleted / uploaded
set -a; . ./.env; set +a
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "http://localhost:9080/opensearch/_cat/indices/mule-logs-*,logstash-*,jaeger-*?v&s=index"
curl -s -u "admin:$OPENSEARCH_ADMIN_PASSWORD" "http://localhost:9080/opensearch/_cat/allocation?v"   # disk.percent
```

Snapshots taken by the backup scripts are separate and have their own retention (`BACKUP_RETENTION_DAYS`, see
[BACKUP_SETUP.md](BACKUP_SETUP.md)).
