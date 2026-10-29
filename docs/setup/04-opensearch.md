# OpenSearch, Dashboards and Fluent Bit

The `logging` profile runs OpenSearch 2.19, OpenSearch Dashboards and Fluent Bit. `tracing` also needs
OpenSearch, because Jaeger stores its spans there.

## OpenSearch

| | |
|--|--|
| Access | `http://localhost:9080/opensearch/` (9080 is published on 127.0.0.1 only; APISIX answers 404 on 9443; 9200 is not published) |
| User | `admin` / `OPENSEARCH_ADMIN_PASSWORD`. This is the only internal user; there is no demo config |
| Heap | `OPENSEARCH_JAVA_OPTS` (default `-Xms512m -Xmx512m`; 2 GB or more for production) |
| Data | volume `dockerelasticsearch_opensearch-data` |

Startup (`scripts/opensearch-start.sh`, the container entrypoint):
- On the first start, it creates the node's own self-signed certificate (`keytool`, stored in the data volume) and
  writes `opensearch.yml` (single node: `cluster.default_number_of_replicas: 0` and ISM history replicas 0, so the
  cluster stays green). No demo certificates or demo users are installed.
- It writes `internal_users.yml` with `admin` only. The password is applied **only when the security index is
  first created**: to change it later, you must wipe the `opensearch-data` volume.
- It runs `scripts/setup-opensearch.sh` in the background on every start (idempotent). That script creates the
  index templates `mule-logs-template` and `logstash-template` and the DLS roles `tenant_viewer_template`,
  `tenant_acme-corp` and `tenant_globex`.

Common calls (load `.env` first):

```bash
set -a; . ./.env; set +a
OS="curl -s -u admin:$OPENSEARCH_ADMIN_PASSWORD http://localhost:9080/opensearch"
$OS"/_cluster/health?pretty"
$OS"/_cat/indices?v"
$OS"/mule-logs-*/_search?pretty" -H 'Content-Type: application/json' \
  -d '{"query":{"bool":{"must":[{"term":{"tenant_id":"acme-corp"}},{"match":{"level":"ERROR"}}]}},"size":10}'
```

Inside the container, use `docker exec opensearch curl -sk -u "admin:$OPENSEARCH_ADMIN_PASSWORD" https://localhost:9200/...`.

## Indices

| Pattern | Written by | Notes |
|---------|------------|-------|
| `mule-logs-YYYY.MM.DD` | Fluent Bit | Mule events (`log_type: mule` or an `application` field); `tenant_id`, `level`, `application`, `worker_id`, `correlationId` are `keyword` |
| `logstash-YYYY.MM.DD` | Fluent Bit | any other event (the name is kept for the templates, DLS roles and log-archiver) |
| `jaeger-span-*`, `jaeger-service-*` | Jaeger | traces |

Retention (log-archiver: archive + delete by age or disk): see [RETENTION_POLICY_GUIDE.md](../RETENTION_POLICY_GUIDE.md). Snapshots: see
[BACKUP_SETUP.md](../BACKUP_SETUP.md).

## Multi-tenancy (DLS)

Each `tenant_<id>` role limits `mule-logs-*` and `logstash-*` to documents with `tenant_id` = `<id>`. You add
tenants and users with `config/scripts/tenants/manage-tenants.sh`. See
[MULTITENANCY_SETUP.md](../MULTITENANCY_SETUP.md) and the demo in [DEMO_MULTITENANCY.md](../../DEMO_MULTITENANCY.md).

## OpenSearch Dashboards

`https://localhost:9443/dashboards/`. Keycloak sign-in (client `dashboards`): realm role `admin` sees everything,
other users only the documents of their token's `tenant_id` (Global tenant read-only). With `GATEWAY_AUTH=off` you sign
in with an OpenSearch user (`admin` or a tenant user). To get started, create index patterns `mule-logs-*` and `logstash-*` (time field `@timestamp`), and
optionally `jaeger-span-*` (time field `startTimeMillis`). The Runtime Manager's app overview also shows recent
errors from `mule-logs-*`.

## Fluent Bit

| | |
|--|--|
| Config | `config/fluent-bit/` (`fluent-bit.conf`, `parsers.conf`, `pipeline.lua`), image `ce-fluent-bit:5.1.4` |
| Input | JSON, one object per line, on TCP/UDP 5000 (`log-ingest:5000` inside the network, `<gateway>:9100` from outside) |
| Health | `fluent-bit:2020/api/v1/health`; metrics at `/api/v1/metrics/prometheus` |

The pipeline:
1. Merges a JSON object found in `message` into the event.
2. Drops the event unless `auth_token` = `LOG_INGEST_TOKEN`, then removes the token.
3. Cleans `tenant_id` (letters, digits, `_`, `-`, lowercase). The raw value is kept in `tenant_id_original`; a
   missing value becomes `unknown`.
4. Sets the event time from log4j's `instant` or `timeMillis`. Renames `host` to `source_host`.
5. Writes to `mule-logs-*` or `logstash-*`.

After editing, run `docker compose up -d --build fluent-bit`. The Mule-side setup (log4j appender, CloudHub) is in
[08-logging-integration.md](08-logging-integration.md).

## Problems

| Symptom | Check |
|---------|-------|
| OpenSearch exits at start | `vm.max_map_count` (see [07](07-troubleshooting.md#opensearch-does-not-start)) |
| No new logs | `docker compose logs fluent-bit` (OpenSearch errors appear here); is the sender's token equal to `LOG_INGEST_TOKEN`? |
| A tenant user sees nothing | `$OS/_plugins/_security/api/roles/tenant_<id>`, and whether the documents' `tenant_id` matches exactly (lowercase) |
| Disk | `$OS"/_cat/allocation?v"` |
