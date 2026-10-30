# Log and Trace Retention (Log Archiver)

The **log archiver** (`log-archiver/`, profiles `logging` and `tracing`) is the only thing that deletes logs and traces
in OpenSearch: there are no ISM policies (it removes old ones on start). Open it from the home page or at
https://localhost:9443/log-archiver/ (Keycloak sign-in, realm role `admin`).

Fluent Bit writes one index per day (`mule-logs-YYYY.MM.DD`, `logstash-YYYY.MM.DD`), Jaeger too (`jaeger-span-YYYY-MM-DD`).
Every `interval` seconds (default 300, or **Run now**) the archiver:

1. for each log index older than today and each **app** in it (field `application`; logs without it count as
   **(no application)**, global rules): when the index is older than the app's retention, exports the app's logs that
   match its **archive filters** to its **destinations**, then deletes them: the whole index once every app in it is
   due, otherwise only those apps' logs (`_delete_by_query`, then the space is reclaimed);
2. size limits, oldest day first, archived as usual: while **all logs** in OpenSearch are bigger than the **max log
   size**; while **one app's** logs are bigger than its own **max size** (only that app's logs of the day go);
3. while OpenSearch's disk is above the **disk limit**: removes the oldest day (traces before logs of the same day),
   archiving each app first; today's indices are never removed;
4. deletes trace indices older than the trace retention (not archived);
5. trims every disk destination to its own retention (days) and size (GB), then **all disk folders together** to the
   archive space limits (below), oldest files first.

Logs and archives use different space and are limited separately: logs live in OpenSearch (its disk is Docker's
volume; with Docker Desktop the virtual disk), archive files in `./volumes/log-archive` on the server's own disk. The
Overview shows both ("Logs in OpenSearch", "Archives on disk" with that disk's use and free space). S3 doesn't count.

An app's size is an estimate: OpenSearch reports sizes per index only, so an app's share is its share of the day's logs
times the index size.

Logs are only deleted after their export is complete (exported count = matching count). If an upload fails the logs
stay and the next pass retries only the destinations that are still missing (state in `/data/state.json`).

## Usage tab

Where the space goes, with the recent growth:

- **OpenSearch disk**: free of total; one bar split into logs, traces, OpenSearch's own data (`.kibana`, security, ...),
  other files on that disk and free, with the disk limit as a line; a second bar of OpenSearch's data alone; how long
  until the disk limit (and the max log size, if set) at the average of the last 7 complete days.
- **Archive disk** (`./volumes/log-archive`): archive files, other files, free, and the archive disk limit.
- **Logs per app**: logs, days, estimated size and share of all logs.
- **Per day**: log and trace size per calendar day (last 30; empty days show as 0), with a table view.
- **Destinations**: files and size on disk now (disk folders) and everything sent so far (files, size, logs; S3 too:
  counted by the archiver, the bucket itself isn't scanned).

`GET /log-archiver/api/usage` returns the same data.

## Rules tab (global)

| Setting | Default | |
|---|---|---|
| Keep logs (days) | 365 | per app overridable |
| Max log size (GB) | 0 (none) | all logs in OpenSearch together |
| OpenSearch disk limit (%) | 80 | OpenSearch blocks writes at 95% (flood stage), 85% stops new shards |
| Keep traces (days) | 7 | today plus the 7 previous days; the largest consumer of space (one span per flow step) |
| Check every (seconds) | 300 | |
| Archive to | `local` | default destinations; none = delete without archive |
| Archive filters | none | which logs get archived (below) |
| Max archive size (GB) | 0 (none) | all disk-folder destinations together (each also has its own limits) |
| Archive disk limit (%) | 0 (off) | of the disk holding `./volumes/log-archive`; above it the oldest archive files go |

`LOGS_RETENTION_DAYS`, `LOGS_DISK_MAX_PERCENT`, `JAEGER_RETENTION_DAYS`, `LOG_ARCHIVE_INTERVAL` in `.env` only seed the
config on the very first start; afterwards the UI's config (`/data/config.json`, volume `log-archiver-data`) wins.

### Archive filters

A list of rules: a log is archived when it matches **any** rule; inside a rule **every** condition must match. Logs that
match no rule are deleted at retention without an archive. No rules = every log is archived.

Conditions: field (`level`, `message`, `loggerName`, `tenant_id`, `environment`, `worker_id`, `correlationId`, `thread`,
`log_type`, `source_host`, `tags`), operator (`is`, `is not`: comma-separated list = any of; `contains`; `starts with`)
and a value. Example: rule 1 `level is ERROR, WARN`; rule 2 `tenant_id is acme` and `message contains refund`.

## Apps tab

Every app seen in the logs (and every app with settings), with its log count and estimated size. Pick one to override,
independently: retention days, max size (GB; only its own logs go, oldest day first), its own destinations (none
checked = no archive for that app) and its own archive filters. Unset = the global rule (no per-app size limit).

## Destinations tab

| Destination | Settings | Files |
|---|---|---|
| **Disk folder** | folder under `./volumes/log-archive/`, format, keep files (days, 0 = forever), max size (GB, 0 = no limit) | `<folder>/<index>/<app>.<ext>` |
| **S3 folder** | S3 connection, folder (prefix) in the bucket, format | `s3://<bucket>/<folder>/<index>/<app>.<ext>` |

Formats: `raw` (`.ndjson`, one JSON log per line), `gzip` (`.ndjson.gz`), `zip` (`.zip` with one `.ndjson`).

**S3 connections** are separate: bucket, region, endpoint (empty = AWS; an S3-compatible store such as MinIO is
`http://minio:9000`, path-style), access key and secret key. Several S3 destinations can share one connection (same
bucket, different folders) or use their own. Secret keys are encrypted with `LOG_ARCHIVER_SECRETS_KEY` and never shown
again (type a new one to replace it). **Test** writes and deletes a small object. The key needs `s3:PutObject` (and
`s3:DeleteObject` for the test). One object is one PUT: at most 5 GB per app per day.

Reading an archive:

```bash
zcat volumes/log-archive/local/mule-logs-2025.10.28/orders-api.ndjson.gz | grep '"level":"ERROR"' | head
unzip -p volumes/log-archive/zip/mule-logs-2025.10.28/orders-api.zip | wc -l
```

## API

Same paths as the UI, through the gateway with an admin token (`ADMIN_TOKEN`, see CLAUDE.md):

```bash
H="Authorization: Bearer $ADMIN_TOKEN"; B=https://localhost:9443/log-archiver/api
curl -sk -H "$H" $B/status                 # last pass, disk, recent actions, disk-folder usage
curl -sk -H "$H" $B/config                 # rules, apps, destinations, connections (secret keys as secret_key_set)
curl -sk -H "$H" $B/indices                # each index: age, logs, size, apps with their retention and what is due
curl -sk -H "$H" -X POST $B/run            # a pass now
curl -sk -H "$H" -X PUT $B/config -H 'Content-Type: application/json' -d @config.json   # whole config, validated
```

The archiver answers only requests carrying the gateway's `X-Gateway-Key` (`LOG_ARCHIVER_TOKEN` in `.env`; `./install.sh`
adds missing secrets to an existing `.env`), so other containers on the network can't use it.

Snapshots taken by the backup scripts are separate and have their own retention (`BACKUP_RETENTION_DAYS`, see
[BACKUP_SETUP.md](BACKUP_SETUP.md)).
